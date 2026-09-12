"""Device status normalization utilities."""

from typing import Any


def parse_aaps_configuration(config: dict) -> dict[str, Any]:
    """Parse AAPS configuration from device status."""
    result = {}

    # Extract key configuration fields
    fields = [
        "use_dynamic_sensitivity",
        "insulin_plugin",
        "insulin_peak_minutes",
        "insulin_dia_hours",
        "max_daily_safety_multiplier",
        "autosens_max_multiplier",
        "autosens_min_multiplier",
        "smb_enabled",
        "smb_max_bolus",
        "smb_max_minutes",
    ]

    for field in fields:
        if field in config:
            result[field] = config[field]

    return result


def parse_loop_data(loop: dict) -> dict[str, Any]:
    """Parse loop data from device status."""
    result = {}

    if "iob" in loop:
        result["iob"] = loop["iob"]
    if "cob" in loop:
        result["cob"] = loop["cob"]
    if "activity" in loop:
        result["activity"] = loop["activity"]
    if "sensitivityRatio" in loop:
        result["sensitivity_ratio"] = loop["sensitivityRatio"]
    if "basaliob" in loop:
        result["basal_iob"] = loop["basaliob"]
    if "bolusiob" in loop:
        result["bolus_iob"] = loop["bolusiob"]
    if "netbasalinsulin" in loop:
        result["net_basal_insulin"] = loop["netbasalinsulin"]
    if "bolusinsulin" in loop:
        result["bolus_insulin"] = loop["bolusinsulin"]
    if "enacted" in loop:
        result["enacted"] = loop["enacted"]
    if "suggested" in loop:
        result["suggested"] = loop["suggested"]

    return result


def normalize_device_status(raw: dict) -> tuple[dict, dict, dict]:
    """Normalize device status into configuration, loop, and quality components."""
    configuration = parse_aaps_configuration(raw.get("openaps", {}).get("config", {}))
    loop = parse_loop_data(raw.get("openaps", {}).get("loop", {}))

    quality = {
        "has_configuration": bool(configuration),
        "has_loop_data": bool(loop),
        "has_iob": "iob" in loop,
        "has_cob": "cob" in loop,
        "has_sensitivity_ratio": "sensitivity_ratio" in loop,
    }

    return configuration, loop, quality


def extract_insulin_model(config: dict) -> dict[str, Any]:
    """Extract insulin model parameters from configuration."""
    return {
        "plugin": config.get("insulin_plugin", "rapid-acting"),
        "peak_minutes": config.get("insulin_peak_minutes", 75),
        "dia_hours": config.get("insulin_dia_hours", 5),
    }


def extract_autosens_config(config: dict) -> dict[str, Any]:
    """Extract autosens configuration."""
    return {
        "enabled": config.get("autosens_enabled", False),
        "max_multiplier": config.get("autosens_max_multiplier", 1.2),
        "min_multiplier": config.get("autosens_min_multiplier", 0.7),
    }
