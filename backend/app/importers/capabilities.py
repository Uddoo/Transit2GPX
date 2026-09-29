from importlib.util import find_spec


def raw_import_available() -> bool:
    return all(
        find_spec(name) is not None for name in ("geopandas", "pandas", "pyogrio")
    )


def require_raw_import() -> None:
    if not raw_import_available():
        from app.core.errors import APIError

        raise APIError(
            status_code=409,
            code="raw_import_unavailable",
            message=(
                "轻量版使用 .t2fcity 标准城市包。"
                "处理原始 Shapefile 请使用完整导入版或数据制包工具。"
            ),
        )
