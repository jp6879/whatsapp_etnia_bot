# drive_share_tools.py
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from app.config import gdrive_settings


def build_drive_service():
    """
    Build a Google Drive service using a Service Account.
    """
    creds = service_account.Credentials.from_service_account_file(
        gdrive_settings.SERVICE_ACCOUNT_FILE,
        scopes=gdrive_settings.SCOPES,
    )

    service = build("drive", "v3", credentials=creds)
    return service


async def list_files_in_folder(service, folder_id):
    """
    List files in folder (direct children only).
    Returns: list of dicts with file info (id, name, webViewLink, webContentLink)
    """
    results = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id, name, mimeType, webViewLink, webContentLink)"

    try:
        while True:
            resp = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields=fields,
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            files = resp.get("files", [])
            results.extend(files)
            page_token = resp.get("nextPageToken", None)
            if not page_token:
                break
    except HttpError as e:
        print("An error occurred listing files:", e)

    return results
