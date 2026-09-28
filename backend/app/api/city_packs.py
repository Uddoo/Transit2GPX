from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError
from app.db.session import get_db
from app.importers.capabilities import raw_import_available
from app.importers.city_pack import (
    MAX_ARCHIVE,
    CityPackError,
    PackPreview,
    install_city_pack,
    read_city_pack,
)

router = APIRouter(prefix="/data/city-packs", tags=["city packages"])


class ImportCapabilities(BaseModel):
    raw_import: bool
    city_pack_format: str = "transit2fog-city-v1"


class PackInstallRequest(BaseModel):
    package_id: str = Field(pattern="^[0-9a-f]{64}$")


class PackInstallResult(BaseModel):
    dataset_id: int
    status: str = "ready"


@router.get("/capabilities", response_model=ImportCapabilities)
def capabilities() -> ImportCapabilities:
    return ImportCapabilities(raw_import=raw_import_available())


@router.post("/inspect", response_model=PackPreview)
def inspect_pack(file: UploadFile) -> PackPreview:
    cache = get_settings().data_dir / "city-packs"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".upload-", dir=cache) as directory:
            incoming = Path(directory) / "upload.t2fcity"
            count = 0
            with incoming.open("wb") as stream:
                while block := file.file.read(1024 * 1024):
                    count += len(block)
                    if count > MAX_ARCHIVE:
                        raise CityPackError(
                            "城市包超过 32 MiB，请使用按城市拆分的数据包。"
                        )
                    stream.write(block)
            preview, _ = read_city_pack(incoming)
            incoming.replace(cache / f"{preview.package_id}.t2fcity")
            return preview
    except CityPackError as error:
        raise APIError(
            status_code=422, code="invalid_city_pack", message=str(error)
        ) from error


@router.post("/install", response_model=PackInstallResult)
def install_pack(
    payload: PackInstallRequest, db: Session = Depends(get_db)
) -> PackInstallResult:
    path = get_settings().data_dir / "city-packs" / f"{payload.package_id}.t2fcity"
    try:
        return PackInstallResult(
            dataset_id=install_city_pack(db, path, payload.package_id)
        )
    except (CityPackError, IntegrityError) as error:
        raise APIError(
            status_code=422,
            code="invalid_city_pack",
            message=str(error)
            if isinstance(error, CityPackError)
            else "城市包包含重复或不一致的线路记录；原有数据已保留。",
        ) from error
