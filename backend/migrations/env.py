from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db import models as _models  # noqa: F401
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

settings = get_settings()
settings.ensure_runtime_directories()
database_url = config.attributes.get("database_url", settings.resolved_database_url)
config.set_main_option("sqlalchemy.url", str(database_url))
target_metadata = Base.metadata

_VIRTUAL_TABLE_PREFIXES = (
    "station_fts",
    "rail_station_fts",
    "station_spatial",
    "route_edge_spatial",
)


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    del object_, reflected, compare_to
    if type_ != "table" or name is None:
        return True
    return not any(
        name == prefix or name.startswith(f"{prefix}_")
        for prefix in _VIRTUAL_TABLE_PREFIXES
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
