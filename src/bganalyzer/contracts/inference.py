"""Inference contracts - models for local AI model management."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ModelState(str, Enum):
    """Model lifecycle states."""

    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ModelSource(str, Enum):
    """Model source types."""

    OFFICIAL = "official"
    LOCAL_IMPORT = "local_import"
    OFFLINE_BUNDLE = "offline_bundle"


class LlamaCppDevice(BaseModel):
    """llama.cpp device information."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: int
    name: str
    type: str
    vram_free_mb: Optional[int] = None
    vram_total_mb: Optional[int] = None
    compute_capability: Optional[str] = None


class ModelCatalogEntry(BaseModel):
    """Model catalog entry with verification metadata."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    repo_id: str
    revision: str
    file_name: str
    file_size: int
    sha256: str
    license: str
    license_url: str
    context_format: str
    tested_runtime_hash: str
    shards: list[str] = Field(default_factory=list)


class ModelDownloadProgress(BaseModel):
    """Model download progress."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    total_bytes: int
    downloaded_bytes: int
    speed_bytes_per_sec: float = 0
    eta_seconds: Optional[float] = None
    state: ModelState = ModelState.DOWNLOADING


class InferenceRequest(BaseModel):
    """Request to local inference server."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    prompt: str
    max_tokens: int = 1500
    temperature: float = 0.2
    top_p: float = 0.95
    stop: list[str] = Field(default_factory=list)
    stream: bool = False


class InferenceResponse(BaseModel):
    """Response from local inference server."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    content: str
    tokens_generated: int
    prompt_tokens: int
    generation_time_ms: int
    model: str


class ServerHealth(BaseModel):
    """Inference server health status."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    healthy: bool
    model_loaded: bool
    model_name: Optional[str] = None
    context_size: int = 0
    gpu_layers: int = 0
    uptime_seconds: int = 0
