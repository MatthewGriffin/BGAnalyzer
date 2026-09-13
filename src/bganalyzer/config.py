"""Application configuration management."""

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from bganalyzer.logging_config import get_logger

logger = get_logger(__name__)


class NightscoutConfig(BaseSettings):
    """Legacy cache identity and transport settings, retained for compatibility."""

    model_config = SettingsConfigDict(extra="ignore")

    origin: str = ""
    auth_mode: str = "public"
    max_body_size: int = 25 * 1024 * 1024


class AtlasConfig(BaseSettings):
    """Atlas (MongoDB) connection configuration."""

    enabled: bool = False
    database: str = "Cluster0"
    entries: str = "entries"
    treatments: str = "treatments"
    devicestatus: str = "devicestatus"
    profile: str = "profile"
    uri: str = Field(default="", exclude=True, repr=False)


class SyncConfig(BaseSettings):
    """Synchronization configuration."""

    poll_interval_seconds: int = 60
    poll_jitter_seconds: int = 10
    backfill_window_days: int = 90
    max_concurrent_requests: int = 2
    retry_backoff: list[int] = Field(default_factory=lambda: [5, 15, 60, 300])
    page_size: int = 1000
    window_days: int = 7
    request_delay_seconds: float = 0.5



class UIConfig(BaseSettings):
    """UI configuration."""

    theme: str = "system"
    glucose_unit: str = "mmol/L"
    timezone: str = "Europe/London"
    report_days: int = 14
    low_threshold: float = 3.9
    high_threshold: float = 10.0
    very_high_threshold: float = 13.9


class StorageConfig(BaseSettings):
    """Storage configuration."""

    retention_days: int = 365
    warn_disk_gb: float = 2.0
    stop_disk_mb: int = 512


class AppConfig(BaseSettings):
    """Main application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="BGANALYZER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    nightscout: NightscoutConfig = Field(default_factory=NightscoutConfig)
    atlas: AtlasConfig = Field(default_factory=AtlasConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    @property
    def source_origin(self) -> str:
        # Keep legacy cache identity so existing records remain visible. No HTTP access.
        return self.nightscout.origin or "atlas://" + self.atlas.database

    @property
    def config_dir(self) -> Path:
        """Get configuration directory."""
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bganalyzer"

    @property
    def data_dir(self) -> Path:
        """Get data directory."""
        return (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "bganalyzer"
        )

    @property
    def cache_dir(self) -> Path:
        """Get cache directory."""
        return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bganalyzer"

    @property
    def db_path(self) -> Path:
        """Get database file path."""
        return self.data_dir / "bganalyzer.db"

    def ensure_dirs(self) -> None:
        """Ensure all required directories exist with correct permissions."""
        for path in [self.config_dir, self.data_dir, self.cache_dir]:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)

    @classmethod
    def load(cls) -> "AppConfig":
        """Load configuration from file and environment."""
        config = cls()
        config.ensure_dirs()
        config_file = config.config_dir / "config.json"
        if config_file.exists():
            try:
                with config_file.open("r") as f:
                    data = json.load(f)
                config = cls.model_validate(data)
                logger.info("Configuration loaded from file", path=str(config_file))
            except Exception as e:
                logger.warning(
                    "Failed to load config file, using defaults", error_type=type(e).__name__
                )
        return config

    def save(self) -> None:
        """Save configuration to file."""
        self.ensure_dirs()
        config_file = self.config_dir / "config.json"
        try:
            temporary = config_file.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self.model_dump(), f, indent=2)
            temporary.chmod(0o600)
            temporary.replace(config_file)
            logger.info("Configuration saved", path=str(config_file))
        except Exception as e:
            logger.error("Failed to save configuration", error_type=type(e).__name__)
            raise
