"""Nightscout v3 API models and utilities."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class V3Version(BaseModel):
    """Nightscout v3 version response."""

    model_config = ConfigDict(extra="allow")
    version: str
    apiVersion: str
    name: str


class V3Status(BaseModel):
    """Nightscout v3 status response."""

    model_config = ConfigDict(extra="allow")
    version: str
    name: str
    apiEnabled: bool
    features: dict = Field(default_factory=dict)


class V3TokenExchange(BaseModel):
    """v3 token exchange request."""

    model_config = ConfigDict(extra="forbid")
    token: str


class V3TokenResponse(BaseModel):
    """v3 token exchange response."""

    model_config = ConfigDict(extra="allow")
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600


class V3CollectionPage(BaseModel):
    """v3 paginated collection response."""

    model_config = ConfigDict(extra="allow")
    data: list[dict]
    pagination: Optional[dict] = None


class V3ModificationHistory(BaseModel):
    """v3 modification history entry."""

    model_config = ConfigDict(extra="allow")
    _id: str
    collection: str
    operation: str
    document: dict
    timestamp: str


def parse_v3_collection(data: dict) -> list[dict]:
    """Extract data array from v3 paginated response."""
    return data.get("data", [])


def extract_v3_cursor(response: dict) -> Optional[str]:
    """Extract next cursor from v3 pagination."""
    pagination = response.get("pagination", {})
    return pagination.get("next_cursor")
