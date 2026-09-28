from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import City, Line, RouteEdge, RouteStop, RouteVariant, Station


def clear_dataset_cities(db: Session, dataset_id: int) -> None:
    """Delete an unpublished dataset graph in foreign-key-safe order."""

    city_ids = select(City.id).where(City.dataset_version_id == dataset_id)
    variant_ids = select(RouteVariant.id).where(
        RouteVariant.dataset_version_id == dataset_id
    )
    db.execute(delete(RouteEdge).where(RouteEdge.route_variant_id.in_(variant_ids)))
    db.execute(delete(RouteStop).where(RouteStop.route_variant_id.in_(variant_ids)))
    db.execute(
        delete(RouteVariant).where(RouteVariant.dataset_version_id == dataset_id)
    )
    db.execute(delete(Line).where(Line.city_id.in_(city_ids)))
    db.execute(delete(Station).where(Station.city_id.in_(city_ids)))
    db.execute(delete(City).where(City.dataset_version_id == dataset_id))
