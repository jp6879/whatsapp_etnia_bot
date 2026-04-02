import logging
from pandas import DataFrame
from asgiref.sync import async_to_sync
from redis import Redis

from app.celery_app import celery
from app.config import redis_settings, google_sheets_settings
from app.services.redis_services import RedisService
from app.services.sheets_services import SheetsService
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger("tasks")


def get_redis_service_sync() -> RedisService:
    """Create Redis service for Celery (using sync client — Celery workers are sync)."""
    client = Redis(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        username=redis_settings.REDIS_USER,
        password=redis_settings.REDIS_PASSWORD,
        decode_responses=True,
    )
    return RedisService(client)


def get_sheets_service_sync() -> SheetsService:
    """Create Sheets service for Celery (sync context)."""
    creds = service_account.Credentials.from_service_account_file(
        google_sheets_settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE,
        scopes=google_sheets_settings.GOOGLE_SHEETS_SCOPES,
    )
    service = build("sheets", "v4", credentials=creds)
    return SheetsService(service=service)


@celery.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,  # seconds between retries
    name="app.tasks.sync_sheets_with_redis_task",
)
def sync_sheets_with_redis_task(self, phone_number: str | None = None):
    """
    Background task to sync Redis session data to Google Sheets.

    When `phone_number` is provided (the normal case), performs a targeted
    single-row upsert — O(1) Redis read instead of O(n) full scan.

    Falls back to a full dump when called without a phone number (e.g. admin/cron trigger).
    """
    redis_service = get_redis_service_sync()
    sheets_service = get_sheets_service_sync()

    try:
        if phone_number:
            # ── Fast path: single-session upsert ────────────────────────────
            logger.info("[sheets_sync] Upserting single session for %s", phone_number)
            row = redis_service.get_session_row(phone_number)
            if not row:
                logger.warning(
                    "[sheets_sync] No session found for %s — skipping", phone_number
                )
                return {"message": "No session found", "phone": phone_number}
            data = DataFrame([row])
        else:
            # ── Slow path: full dump (admin / cron use only) ─────────────────
            logger.info("[sheets_sync] Full dump triggered (no phone_number)")
            data = DataFrame(redis_service.get_all_data())

        if data.empty:
            return {"message": "No data to sync"}

        data = data.sort_values(by="FECHA", ascending=True).reset_index(drop=True)
        async_to_sync(sheets_service.update_sheet)(data)
        logger.info("[sheets_sync] Sheets updated successfully (rows=%d)", len(data))
        return {"message": "Sheets updated successfully", "rows": len(data)}

    except Exception as exc:
        logger.error(
            "[sheets_sync] Task failed (attempt %d/3): %s",
            self.request.retries + 1,
            exc,
        )
        raise self.retry(exc=exc)

    finally:
        # CRITICAL: Close Redis connection to prevent "max clients" error
        redis_service.client.close()
