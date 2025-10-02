from pprint import pprint as pp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
import io
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SERVICE_ACCOUNT_FILE = "app/etc/secrets/service_account_key.json"


def download_file(real_file_id):
    """Downloads a file
    Args:
        real_file_id: ID of the file to download
    Returns : IO object with location.

    Load pre-authorized user credentials from the environment.
    TODO(developer) - See https://developers.google.com/identity
    for guides on implementing OAuth2 for the application."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )

    try:
        # create drive api client
        service = build("drive", "v3", credentials=creds)

        file_id = real_file_id

        # pylint: disable=maybe-no-member
        request = service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print(f"Download {int(status.progress() * 100)}.")

    except HttpError as error:
        print(f"An error occurred: {error}")
        file = None

    return file.getvalue()


if __name__ == "__main__":
    file = download_file(real_file_id="")
    with open("descargado.pdf", "wb") as f:
        f.write(file)
    print("Archivo descargado como 'descargado.pdf'")
