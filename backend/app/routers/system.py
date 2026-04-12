from fastapi import APIRouter, BackgroundTasks, Depends

from app.dependencies import get_admin_user
from app.indexer import run_indexer
from app.models import User
from app.services.track_repair import repair_stale_tracks
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/index")
async def trigger_index(
    background_tasks: BackgroundTasks,
    _: User = Depends(get_admin_user),
) -> dict:
    """
    Manually trigger a full library index scan.
    """
    _logger.info("Manual index triggered")
    background_tasks.add_task(run_indexer)
    return {"message": "Indexing started in background"}

@router.post("/repair-stale-tracks")
async def post_repair_stale_tracks(_: User = Depends(get_admin_user)) -> dict:
    """
    Fix DB rows that still say \"cached\" after cache files were deleted, and remove
    junk ``local`` tracks that were indexed from ``TEMP_DIR`` / ``CACHE_DIR``.
    """
    stats = repair_stale_tracks()
    _logger.info("repair-stale-tracks: %s", stats)
    return {"message": "Repair complete", **stats}


@router.get("/storage")
async def get_storage(_: User = Depends(get_admin_user)) -> dict:
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
