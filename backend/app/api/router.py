from fastapi import APIRouter

from app.api.app_config import router as config_router
from app.api.city_map import router as city_map_router
from app.api.city_packs import router as city_packs_router
from app.api.csv_imports import router as csv_imports_router
from app.api.data_status import router as data_router
from app.api.exports import router as exports_router
from app.api.journeys import router as journeys_router
from app.api.network import router as network_router
from app.api.onboarding import router as onboarding_router
from app.api.paths import router as paths_router
from app.api.rail_data import router as rail_data_router
from app.api.rail_stations import router as rail_stations_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(config_router)
api_router.include_router(data_router)
api_router.include_router(city_packs_router)
api_router.include_router(city_map_router)
api_router.include_router(network_router)
api_router.include_router(paths_router)
api_router.include_router(rail_data_router)
api_router.include_router(rail_stations_router)
api_router.include_router(journeys_router)
api_router.include_router(exports_router)
api_router.include_router(csv_imports_router)

api_router.include_router(onboarding_router)
