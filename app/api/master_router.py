from fastapi import APIRouter
from app.api.routers import redis_router, sheets_router

master_router = APIRouter()
master_router.include_router(redis_router.router)
master_router.include_router(sheets_router.router)


@master_router.post("/sync-sheets")
def trigger_sheets_sync():
    """Manually trigger a sync from Redis to Google Sheets."""
    from app.tasks import sync_sheets_with_redis_task

    # No phone_number → intentional full dump (admin/manual sync path)
    task = sync_sheets_with_redis_task.delay()
    return {"message": "Sync queued", "task_id": task.id}
