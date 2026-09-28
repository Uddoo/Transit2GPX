from sqlalchemy import Select, exists, select, tuple_
from sqlalchemy.orm import aliased

from app.db.models import City, DatasetVersion


def current_city_ids() -> Select[tuple[int]]:
    """Newest ready version per city, without deleting historical journey edges.

    A single-city update must not retire the other cities of a legacy full dataset.
    """
    newer_city = aliased(City)
    newer_dataset = aliased(DatasetVersion)
    newer = (
        select(newer_city.id)
        .join(newer_dataset, newer_city.dataset_version_id == newer_dataset.id)
        .where(
            newer_city.source_city_code == City.source_city_code,
            newer_city.status == "ready",
            newer_dataset.status == "ready",
            tuple_(newer_dataset.imported_at, newer_dataset.id)
            > tuple_(DatasetVersion.imported_at, DatasetVersion.id),
        )
        .correlate(City, DatasetVersion)
    )
    return (
        select(City.id)
        .join(DatasetVersion)
        .where(City.status == "ready", DatasetVersion.status == "ready", ~exists(newer))
        .correlate(None)
    )
