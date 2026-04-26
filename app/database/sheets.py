from fastapi import Depends
from typing import Annotated
from app.services.sheets_services import SheetsService
from google.oauth2 import service_account
from googleapiclient.discovery import build
from app.config import get_google_sheets_settings
from app.core.exceptions import GoogleSheetsConnectionError


async def build_sheets_service():
    """
    Build a service object for the Google Sheets API.
    """
    google_sheets_settings = get_google_sheets_settings()
    creds = service_account.Credentials.from_service_account_file(
        google_sheets_settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE,
        scopes=google_sheets_settings.GOOGLE_SHEETS_SCOPES,
    )
    service = build("sheets", "v4", credentials=creds)

    if not service:
        raise GoogleSheetsConnectionError("Failed to build Google Sheets service")

    return service


SheetsOriginalServiceDep = Annotated[SheetsService, Depends(build_sheets_service)]


async def get_sheets_service(
    original_service: SheetsOriginalServiceDep,
) -> SheetsService:
    """Getting the sheets service where the data is stored"""
    return SheetsService(service=original_service)
