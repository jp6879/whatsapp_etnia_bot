from pandas import DataFrame
from asgiref.sync import async_to_sync
from redis import Redis

from app.celery_app import celery
from app.config import redis_settings, google_sheets_settings
from app.services.redis_services import RedisService
from app.services.sheets_services import SheetsService
from google.oauth2 import service_account
from googleapiclient.discovery import build


def get_redis_service_sync() -> RedisService:
    """Create Redis service for Celery (using async client with async_to_sync)."""
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


@celery.task
def sync_sheets_with_redis_task():
    """
    Background task to sync Redis session data to Google Sheets.
    Called when a conversation reaches a handoff state.
    """
    redis_service = get_redis_service_sync()
    sheets_service = get_sheets_service_sync()

    try:
        data = redis_service.get_all_data()
        df = (
            DataFrame(data)
            .sort_values(by="FECHA", ascending=True)
            .reset_index(drop=True)
        )
        async_to_sync(sheets_service.update_sheet)(df)
        return {"message": "Sheets updated successfully"}
    finally:
        redis_service.client.close()
