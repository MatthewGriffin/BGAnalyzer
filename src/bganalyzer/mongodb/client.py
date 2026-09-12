"""Direct MongoDB client for BG data - replaces Nightscout API."""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, parse_qs

from bson import ObjectId, Decimal128
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from bganalyzer.contracts.domain import SyncCollection
from bganalyzer.nightscout.client import NightscoutError


def midnight_ms(zone, now=None):
    now = now or datetime.now(ZoneInfo(zone))
    return int(
        datetime.combine(now.astimezone(ZoneInfo(zone)).date(), time(), ZoneInfo(zone)).timestamp()
        * 1000
    )


def validate_mongodb_uri(uri):
    try:
        parts = urlsplit(uri)
        options = {k.lower(): v for k, v in parse_qs(parts.query).items()}
        if parts.scheme not in ("mongodb", "mongodb+srv") or not parts.hostname:
            raise ValueError()
        if not parts.username or not parts.password or parts.fragment:
            raise ValueError()
        for key in ("tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames"):
            if any(v.lower() != "false" for v in options.get(key, [])):
                raise ValueError()
        for key in ("tls", "ssl"):
            if parts.scheme == "mongodb+srv" and any(v.lower() != "true" for v in options.get(key, [])):
                raise ValueError()
    except ValueError:
        raise ValueError(
            "Enter a MongoDB URI with credentials and verified TLS."
        ) from None
    return uri


def normalize(value):
    """Match Nightscout JSON representations so IDs/revisions share one local source."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


class MongoDBClient:
    """Read-only MongoDB client for glucose, treatments, devicestatus, and profile collections."""

    def __init__(self, config, uri, cancelled=lambda: False):
        if not uri:
            raise NightscoutError(
                "Enter the MongoDB connection URI in Connection.", error_code="AUTH_REQUIRED"
            )
        self.client = None
        try:
            if not config.database:
                raise ValueError()
            validate_mongodb_uri(uri)
            self.client = MongoClient(
                uri,
                tls=True,
                tz_aware=True,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=15000,
                timeoutMS=30000,
                maxPoolSize=2,
                appname="BGAnalyzer",
            )
            self.database = self.client[config.database]
        except (ValueError, PyMongoError):
            if self.client is not None:
                self.client.close()
            raise NightscoutError(
                "Check MongoDB connection settings.", error_code="MONGODB_CONFIG"
            ) from None
        self.config = config
        self.cancelled = cancelled
        self._verified = set()

    def pages(self, collection, start=None, end=None):
        if self.cancelled():
            raise NightscoutError("Synchronization cancelled", error_code="CANCELLED")
        name = getattr(self.config, collection)
        try:
            if name not in self._verified:
                if name not in self.database.list_collection_names():
                    raise NightscoutError(
                        "Configured MongoDB collection does not exist.", error_code="MONGODB_COLLECTION"
                    )
                self._verified.add(name)
            field = "date" if collection == "entries" else "created_at"
            query = {}
            if start is not None:
                if field == "date":
                    query = {field: {"$gte": start, "$lt": end}}
                else:
                    lo = datetime.fromtimestamp(start / 1000, timezone.utc)
                    hi = datetime.fromtimestamp(end / 1000, timezone.utc)
                    query = {
                        "$expr": {
                            "$let": {
                                "vars": {
                                    "event": {
                                        "$convert": {
                                            "input": "$created_at",
                                            "to": "date",
                                            "onError": None,
                                            "onNull": None,
                                        }
                                    }
                                },
                                "in": {
                                    "$and": [{"$gte": ["$$event", lo]}, {"$lt": ["$$event", hi]}]
                                },
                            }
                        }
                    }
            with self.database[name].find(query, batch_size=1000).max_time_ms(30000) as cursor:
                page = []
                for record in cursor:
                    if self.cancelled():
                        raise NightscoutError("Synchronization cancelled", error_code="CANCELLED")
                    page.append(normalize(record))
                    if len(page) == 1000:
                        yield page
                        page = []
                if page:
                    yield page
        except PyMongoError as exc:
            code = "AUTH_FAILED" if getattr(exc, "code", None) in (13, 18) else "MONGODB_READ_FAILED"
            raise NightscoutError(
                "MongoDB read failed; check database permissions and network access.", error_code=code
            ) from None

    def fetch_profiles(self):
        return [record for page in self.pages("profile") for record in page]

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()