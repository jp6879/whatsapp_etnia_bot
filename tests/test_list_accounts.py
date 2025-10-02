from pprint import pprint as pp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account


# Scopes: elegí el más limitado posible
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]

# Ruta al archivo JSON que bajaste de Google Cloud
SERVICE_ACCOUNT_FILE = "app/etc/secrets/service_account_key.json"


def main():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    results = []
    page_token = None
    folder_id = ""
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

    if not results:
        print("No files found.")
        return

    print("Files:")
    for item in results:
        pp(item)


if __name__ == "__main__":
    main()
