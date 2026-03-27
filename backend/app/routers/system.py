from fastapi import APIRouter, BackgroundTasks, Request, Depends
from app.config import settings
from app.indexer import run_indexer
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/config")
async def get_system_config(request: Request) -> dict:
    """
    Expose public configuration for the system.
    """
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "api_base_url": str(request.base_url).rstrip('/')
    }

@router.post("/index")
async def trigger_index(background_tasks: BackgroundTasks) -> dict:
    """
    Manually trigger a full library index scan.
    """
    _logger.info("Manual index triggered")
    background_tasks.add_task(run_indexer)
    return {"message": "Indexing started in background"}

@router.get("/storage")
async def get_storage() -> dict:
    """
    Get backend server storage statistics.
    """
    import psutil
    path = "/app"
    usage = psutil.disk_usage(path)
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": usage.percent
    }
