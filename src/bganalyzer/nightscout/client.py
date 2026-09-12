"""Bounded, read-only Nightscout v1 transport with credential-safe errors."""

import hashlib
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from bganalyzer.config import NightscoutConfig, SyncConfig


class NightscoutError(Exception):
    def __init__(self, message: str, status_code=None, error_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def interruptible_wait(seconds, cancelled):
    deadline = time.monotonic() + seconds
    while True:
        if cancelled():
            raise NightscoutError("Synchronization cancelled", error_code="CANCELLED")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def validate_origin(origin: str) -> str:
    try:
        parts = urlsplit(origin.strip())
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTPS Nightscout URL") from exc
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Use an HTTPS URL without credentials, query, or fragment")
    return origin.strip().rstrip("/")


class NightscoutClient:
    def __init__(self, config: NightscoutConfig, sync_config: SyncConfig, credential_provider):
        self.config = config
        self.sync_config = sync_config
        self.credential_provider = credential_provider
        self.origin = validate_origin(config.origin)
        self._client = None
        self.cancelled = lambda: False

    def _get_client(self):
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.origin + "/",
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10, read=30, write=10, pool=5),
                limits=httpx.Limits(max_connections=2),
                verify=True,
            )
        return self._client

    @staticmethod
    def _sha1_digest(secret):
        return hashlib.sha1(secret.encode()).hexdigest()

    def _request(self, method, path, **kwargs):
        if method.upper() != "GET":
            raise NightscoutError("Only GET requests are allowed", error_code="READ_ONLY")
        if not path.startswith("api/") or ".." in path or "?" in path or "#" in path:
            raise NightscoutError("Invalid API path", error_code="INVALID_PATH")
        headers = {"Accept": "application/json", "User-Agent": "BGAnalyzer/0.1.0"}
        if self.config.auth_mode != "public":
            if self.config.auth_mode != "api_secret":
                raise NightscoutError(
                    "This build supports public reads or API-secret authentication",
                    error_code="UNSUPPORTED_AUTH",
                )
            token = self.credential_provider.get_token()
            if not token:
                raise NightscoutError(
                    "Enter an API secret for this source", error_code="AUTH_REQUIRED"
                )
            headers["api-secret"] = self._sha1_digest(token)

        # Defense in depth even if a future caller bypasses the pagination policy.
        request = self._get_client().build_request("GET", path, params=kwargs.get("params"))
        if len(str(request.url).encode("utf-8")) > 4096:
            raise NightscoutError(
                "Query exceeds the supported URL length", error_code="REQUEST_TOO_LONG"
            )
        backoffs = [min(max(float(delay), 0), 10) for delay in self.sync_config.retry_backoff[:2]]
        for attempt in range(len(backoffs) + 1):
            interruptible_wait(0, self.cancelled)
            retry_delay = None
            try:
                with self._get_client().stream("GET", path, headers=headers, **kwargs) as response:
                    status = response.status_code
                    if status == 200:
                        if (
                            "application/json"
                            not in response.headers.get("content-type", "").lower()
                        ):
                            raise NightscoutError(
                                "Expected JSON response", error_code="INVALID_CONTENT_TYPE"
                            )
                        chunks = []
                        size = 0
                        for chunk in response.iter_bytes():
                            interruptible_wait(0, self.cancelled)
                            size += len(chunk)
                            if size > self.config.max_body_size:
                                raise NightscoutError(
                                    "Response exceeds size limit", error_code="RESPONSE_TOO_LARGE"
                                )
                            chunks.append(chunk)
                        return httpx.Response(
                            200,
                            content=b"".join(chunks),
                            headers={"content-type": "application/json"},
                        )
                    code = (
                        "AUTH_FAILED"
                        if status in (401, 403)
                        else "RATE_LIMITED"
                        if status == 429
                        else "REQUEST_TOO_LONG"
                        if status in (413, 414)
                        else "HTTP_ERROR"
                    )
                    if status in (429, 500, 502, 503, 504) and attempt < len(backoffs):
                        retry_delay = backoffs[attempt]
                        after = response.headers.get("Retry-After", "")
                        if after.isdigit():
                            # Long server backoffs should surface to the scheduler, not freeze a worker.
                            if int(after) > 10:
                                raise NightscoutError(
                                    f"Nightscout returned HTTP {status}; retry later", status, code
                                )
                            retry_delay = max(retry_delay, int(after))
                    else:
                        raise NightscoutError(f"Nightscout returned HTTP {status}", status, code)
            except httpx.RequestError:
                if attempt == len(backoffs):
                    raise NightscoutError(
                        "Network request failed; check connection and certificate",
                        error_code="NETWORK_ERROR",
                    ) from None
                retry_delay = backoffs[attempt]
            # Close the previous response before waiting; cancellation is checked every 100 ms.
            interruptible_wait(retry_delay, self.cancelled)

    def _json(self, path, expected, params=None):
        try:
            data = self._request("GET", path, params=params).json()
        except ValueError:
            raise NightscoutError("Invalid JSON response", error_code="INVALID_JSON") from None
        if not isinstance(data, expected) or (
            expected is list and any(not isinstance(x, dict) for x in data)
        ):
            raise NightscoutError("Unexpected response structure", error_code="INVALID_SCHEMA")
        return data

    def get_status(self):
        return self._json("api/v1/status.json", dict)

    def get_version(self):
        return self._json("api/v3/version", dict)

    def fetch_entries(self, start_ms, end_ms, count=1000, excluded_ids=None):
        return self._json(
            "api/v1/entries.json",
            list,
            {
                "find[date][$gte]": start_ms,
                "find[date][$lt]": end_ms,
                "count": count,
                **({"find[_id][$nin][]": excluded_ids} if excluded_ids else {}),
            },
        )

    def _dated(self, collection, start_ms, end_ms, count, excluded_ids=None):
        def iso(ms):
            return (
                datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            )

        return self._json(
            f"api/v1/{collection}.json",
            list,
            {
                "find[created_at][$gte]": iso(start_ms),
                "find[created_at][$lt]": iso(end_ms),
                "count": count,
                **({"find[_id][$nin][]": excluded_ids} if excluded_ids else {}),
            },
        )

    def fetch_treatments(self, start_ms, end_ms, count=1000, excluded_ids=None):
        return self._dated("treatments", start_ms, end_ms, count, excluded_ids)

    def fetch_devicestatus(self, start_ms, end_ms, count=1000, excluded_ids=None):
        return self._dated("devicestatus", start_ms, end_ms, count, excluded_ids)

    def fetch_profiles(self):
        return self._json("api/v1/profile.json", list, {"count": 1000})

    def fetch_food(self):
        return self._json("api/v1/food.json", list, {"count": 1000})

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
