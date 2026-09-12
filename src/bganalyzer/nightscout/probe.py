"""Nightscout connection probe and capability detection."""

import json
import time
from dataclasses import dataclass, field

from bganalyzer.config import NightscoutConfig, SyncConfig
from bganalyzer.logging_config import get_logger
from bganalyzer.nightscout.client import NightscoutClient, NightscoutError
from bganalyzer.secrets import CredentialProvider

logger = get_logger(__name__)


@dataclass
class ProbeResult:
    """Result of Nightscout connection probe."""

    origin: str
    reachable: bool = False
    server_version: str = ""
    api_mode: str = "v1"
    clock_offset_ms: int = 0
    collections: dict[str, dict] = field(default_factory=dict)
    capabilities_json: str = "{}"
    errors: list[str] = field(default_factory=list)


def probe_nightscout(
    config: NightscoutConfig, sync_config: SyncConfig, credential_provider: CredentialProvider
) -> ProbeResult:
    """Perform comprehensive Nightscout connection probe."""
    result = ProbeResult(origin=config.origin)

    if not config.origin.startswith("https://") and not config.origin.startswith(
        "http://localhost"
    ):
        result.errors.append("Origin must be HTTPS (or localhost for development)")
        return result

    try:
        with NightscoutClient(config, sync_config, credential_provider) as client:
            start = time.time()
            status = client.get_status()
            elapsed = (time.time() - start) * 1000

            result.reachable = True
            result.server_version = status.get("version", "unknown")
            result.clock_offset_ms = int(elapsed)

            logger.info(
                "Nightscout status retrieved", version=result.server_version, latency_ms=elapsed
            )

            probe_results = client.probe_collections()
            result.collections = probe_results
            result.capabilities_json = json.dumps(probe_results)

            readable_count = sum(1 for c in probe_results.values() if c.get("readable"))
            logger.info(
                "Collection probe complete", readable=readable_count, total=len(probe_results)
            )

            for name, data in probe_results.items():
                if not data.get("readable"):
                    result.errors.append(
                        f"Collection '{name}': {data.get('error_code', 'unknown error')}"
                    )

    except NightscoutError as e:
        result.errors.append(f"Connection failed: {e.error_code}")
        logger.error("Nightscout probe failed", error=str(e))
    except Exception as e:
        result.errors.append(f"Unexpected error: {e}")
        logger.error("Nightscout probe unexpected error", error=str(e))

    return result


def verify_v3_auth(
    config: NightscoutConfig, sync_config: SyncConfig, credential_provider: CredentialProvider
) -> bool:
    """Verify v3 authentication works."""
    try:
        with NightscoutClient(config, sync_config, credential_provider) as client:
            client.get_version()
            return True
    except NightscoutError as e:
        if e.error_code == "AUTH_FAILED":
            return False
        raise
    except Exception:
        return False
