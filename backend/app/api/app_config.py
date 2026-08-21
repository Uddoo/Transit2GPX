from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import get_settings

router = APIRouter(prefix="/config", tags=["configuration"])


class PublicMapConfig(BaseModel):
    tiles_enabled: bool
    tile_url: str
    tile_attribution: str
    max_zoom: int = Field(ge=1, le=24)
    external_tiles: bool


class PublicConfigResponse(BaseModel):
    map: PublicMapConfig


@router.get("/public", response_model=PublicConfigResponse)
def public_config() -> PublicConfigResponse:
    """Return non-secret runtime settings needed by the browser UI."""

    settings = get_settings()
    return PublicConfigResponse(
        map=PublicMapConfig(
            tiles_enabled=settings.map_tiles_enabled,
            tile_url=settings.map_tile_url,
            tile_attribution=settings.map_tile_attribution,
            max_zoom=settings.map_max_zoom,
            external_tiles=settings.map_tile_url.startswith(("http://", "https://")),
        )
    )
