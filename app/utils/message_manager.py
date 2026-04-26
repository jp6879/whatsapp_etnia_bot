import io
import base64
import json
from difflib import get_close_matches
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from app.config import get_google_drive_settings
import re


def load_ads_config() -> list[dict]:
    """Load ads config with caching for performance"""
    gdrive_settings = get_google_drive_settings()
    config_path = gdrive_settings.ADS_FILE_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_offers_db():
    """Load messages db with caching for performance"""
    gdrive_settings = get_google_drive_settings()
    config_path = gdrive_settings.OFFERS_DB_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_drive_service():
    gdrive_settings = get_google_drive_settings()
    creds = service_account.Credentials.from_service_account_file(
        gdrive_settings.SERVICE_ACCOUNT_FILE,
        scopes=gdrive_settings.SCOPES,
    )
    return build("drive", "v3", credentials=creds)


async def list_files_in_folder(service, folder_id: str) -> list[dict]:
    query = f"'{folder_id}' in parents and trashed = false"
    response = (
        service.files()
        .list(
            q=query,
            fields="files(id,name,mimeType)",
            pageSize=1000,
        )
        .execute()
    )
    return response.get("files", [])


class MessageManager:
    CITIES = {
        "AEP": [
            "aep",
            "aeroparque",
            "buenos aires aeroparque",
            "ciudad de buenos aires",
            "ciudad de buenos aires capital",
            "ciudad de buenos aires ciudad",
            "jorge newbery",
        ],
        "AFA": [
            "afa",
            "san rafael",
            "san rafael capital",
            "san rafael ciudad",
            "santiago germano",
        ],
        "AOL": [
            "aol",
            "paso de los libres",
            "paso de los libres capital",
            "paso de los libres ciudad",
        ],
        "BHI": [
            "bahia blanca",
            "bahia blanca capital",
            "bahia blanca ciudad",
            "bhi",
            "comandante espora",
        ],
        "BRC": [
            "bariloche",
            "bariloche capital",
            "bariloche ciudad",
            "brc",
            "san carlos de bariloche",
            "tte. luis candelaria",
        ],
        "CNQ": [
            "cnq",
            "corrientes",
            "corrientes capital",
            "corrientes ciudad",
            "dr. piragine niveyro",
        ],
        "COC": [
            "coc",
            "comodoro pierrestegui",
            "concordia",
            "concordia capital",
            "concordia ciudad",
        ],
        "COR": [
            "a.taravella/pajas blancas",
            "cba",
            "cor",
            "cordoba",
            "cordoba argentina",
            "cordoba capital",
            "cordoba ciudad",
        ],
        "CPC": [
            "aviador .campos/chapelco",
            "cpc",
            "san martin de los andes",
            "san martin de los andes capital",
            "san martin de los andes ciudad",
        ],
        "CRD": [
            "chubut",
            "comodoro",
            "comodoro rivadavia",
            "comodoro rivadavia capital",
            "comodoro rivadavia ciudad",
            "crd",
            "intern.gral. e. mosconi",
        ],
        "CTC": [
            "catamarca",
            "catamarca capital",
            "catamarca ciudad",
            "cnel. felipe varela",
            "ctc",
        ],
        "CUT": ["cut", "cutral-co", "cutral-co capital", "cutral-co ciudad"],
        "EQS": [
            "brig. gral. antonio parodi",
            "eqs",
            "esquel",
            "esquel capital",
            "esquel ciudad",
        ],
        "ESQ": ["esquel", "esq"],
        "EZE": [
            "baires",
            "bs as",
            "bsas",
            "bue",
            "buenos aires",
            "buenos aires capital",
            "buenos aires ciudad",
            "buenosaires",
            "caba",
            "capital federal",
            "ciudad autonoma de buenos aires",
            "eze",
            "ezeiza",
            "ezeiza capital",
            "ezeiza ciudad",
            "ministro pistarini",
        ],
        "FDO": ["fdo", "san fernando", "san fernando capital", "san fernando ciudad"],
        "FMA": ["el pucu", "fma", "formosa", "formosa capital", "formosa ciudad"],
        "FTE": [
            "calafate",
            "comandante armando tola",
            "el calafate",
            "el calafate capital",
            "el calafate ciudad",
            "el calafate santa cruz",
            "fte",
        ],
        "GNR": [
            "arturo humberto illia",
            "general roca",
            "general roca capital",
            "general roca ciudad",
            "gnr",
        ],
        "GPO": ["general pico", "general pico capital", "general pico ciudad", "gpo"],
        "IGR": [
            "igr",
            "iguazu",
            "iguazú",
            "my. carlos e. krause",
            "puerto iguazu",
            "puerto iguazu capital",
            "puerto iguazu ciudad",
            "puerto iguazú",
        ],
        "IRJ": [
            "cap. vicente a. almonacid",
            "irj",
            "la rioja",
            "la rioja capital",
            "la rioja ciudad",
        ],
        "JNI": ["jni", "junin", "junin capital", "junin ciudad"],
        "JUJ": [
            "gob. horacio guzman",
            "juj",
            "jujuy",
            "jujuy argentina",
            "jujuy capital",
            "jujuy ciudad",
            "san salvador de jujuy",
            "san salvador de jujuy capital",
            "san salvador de jujuy ciudad",
        ],
        "LGS": [
            "cdro. ricardo salomon",
            "lgs",
            "malargue",
            "malargue capital",
            "malargue ciudad",
        ],
        "LPG": ["la plata", "la plata capital", "la plata ciudad", "lpg"],
        "LUQ": [
            "brig. may. cesar raul ojeda",
            "luq",
            "san luis",
            "san luis capital",
            "san luis ciudad",
        ],
        "MDP": ["mar del plata", "mdp", "mar del plata ciudad"],
        "MDQ": [
            "astor piazzolla",
            "mar del plata",
            "mar del plata capital",
            "mar del plata ciudad",
            "mdq",
        ],
        "MDZ": [
            "gob. gabrielli/el plumerillo",
            "mdz",
            "mendoza",
            "mendoza capital",
            "mendoza ciudad",
        ],
        "NEC": ["nec", "necochea", "necochea capital", "necochea ciudad"],
        "NQN": [
            "neuquen",
            "neuquen capital",
            "neuquen ciudad",
            "nqn",
            "presidente peron",
        ],
        "OYA": [
            "diego n. diaz colodrero",
            "goya",
            "goya capital",
            "goya ciudad",
            "oya",
        ],
        "PMY": [
            "el tehuelche",
            "pmy",
            "puerto madryn",
            "puerto madryn capital",
            "puerto madryn ciudad",
        ],
        "PRA": [
            "entre rios",
            "gral. justo j.de urquiza",
            "parana",
            "parana capital",
            "parana ciudad",
            "pra",
        ],
        "PSS": [
            "lib. gral. j. de san martin",
            "misiones capital",
            "posadas",
            "posadas capital",
            "posadas ciudad",
            "pss",
        ],
        "RCQ": [
            "daniel jukic",
            "rcq",
            "reconquista",
            "reconquista capital",
            "reconquista ciudad",
        ],
        "RCU": [
            "area material rio cuarto",
            "rcu",
            "rio cuarto",
            "rio cuarto capital",
            "rio cuarto ciudad",
        ],
        "REL": [
            "alte. marcos a. zar",
            "rel",
            "trelew",
            "trelew capital",
            "trelew ciudad",
        ],
        "RES": [
            "chaco",
            "chaco capital",
            "chaco ciudad",
            "jose de san martin",
            "res",
            "resistencia",
            "resistencia capital",
            "resistencia ciudad",
        ],
        "RGA": [
            "gob. ramon trejo noel",
            "rga",
            "rio grande",
            "rio grande capital",
            "rio grande ciudad",
        ],
        "RGL": [
            "pil. civ. norberto fernandez",
            "rgl",
            "rio gallegos",
            "rio gallegos capital",
            "rio gallegos ciudad",
            "santa cruz",
        ],
        "RHD": [
            "rhd",
            "rio hondo",
            "rio hondo capital",
            "rio hondo ciudad",
            "termas de rio hondo",
        ],
        "RLO": ["merlo", "merlo capital", "merlo ciudad", "rlo", "valle del conlara"],
        "ROS": [
            "islas malvinas",
            "ros",
            "rosario",
            "rosario argentina",
            "rosario capital",
            "rosario ciudad",
        ],
        "RSA": ["rsa", "santa rosa", "santa rosa capital", "santa rosa ciudad"],
        "RYO": [
            "el turbio",
            "el turbio capital",
            "el turbio ciudad",
            "el turbio/28 de noviembre",
            "ryo",
        ],
        "SDE": [
            "com. de la paz aragones",
            "santiago del estero",
            "santiago del estero capital",
            "santiago del estero ciudad",
            "sde",
        ],
        "SFE": ["santa fe", "santa fe capital", "santa fe ciudad"],
        "SFN": [
            "santa fe",
            "santa fe capital",
            "santa fe ciudad",
            "sauce viejo",
            "sfn",
        ],
        "SLA": ["gral. guemes", "salta", "salta capital", "salta ciudad", "sla"],
        "SRA": ["santa rosa", "la pampa", "la pampa capital", "santa rosa ciudad"],
        "STT": [
            "santa teresita",
            "santa teresita capital",
            "santa teresita ciudad",
            "stt",
        ],
        "TDL": ["tandil", "tandil capital", "tandil ciudad", "tdl"],
        "TTG": [
            "gral. e. mosconi",
            "tartagal",
            "tartagal capital",
            "tartagal ciudad",
            "ttg",
        ],
        "TUC": [
            "s. miguel de tucuman",
            "s. miguel de tucuman capital",
            "s. miguel de tucuman ciudad",
            "san miguel de tucuman",
            "tte. benjamin matienzo",
            "tuc",
            "tucuman",
            "tucumán",
        ],
        "UAQ": [
            "domingo faustino sarmiento",
            "san juan",
            "san juan capital",
            "san juan ciudad",
            "uaq",
        ],
        "USH": [
            "malvinas argentinas",
            "ush",
            "ushuaia",
            "ushuaia argentina",
            "ushuaia capital",
            "ushuaia ciudad",
            "ushuaia tierra del fuego",
        ],
        "VDM": [
            "gobernador castello",
            "rio negro",
            "vdm",
            "viedma",
            "viedma capital",
            "viedma ciudad",
        ],
        "VGL": ["vgl", "villa gesell", "villa gesell capital", "villa gesell ciudad"],
        "VME": [
            "villa reynolds",
            "villa reynolds capital",
            "villa reynolds ciudad",
            "vme",
        ],
    }

    def __init__(self):
        self.encoded_ads: list[dict] = load_ads_config()
        self.offers_db = load_offers_db()

    def get_ad_info(self, message: str) -> tuple[str, str, str]:
        """Fast lookup: message -> destination"""

        for add_info in self.encoded_ads:
            message_list = add_info.get("messages", [])
            if message in message_list:
                ad_destination = add_info.get("ad_destination")
                destination_key = add_info.get("destination_key")
                offer_type = add_info.get("offer_type")
                return ad_destination, destination_key, offer_type

        return "unknown", "unknown", "unknown"

    def get_iata_code(self, text: str):
        text_norm = self.normalize_text(text)

        # 1. Coincidencia directa
        for code, variants in self.CITIES.items():
            for variant in variants:
                if variant in text_norm:
                    return code

        # 2. Coincidencia aproximada (fuzzy)
        words = text_norm.split()
        for word in words:
            for code, variants in self.CITIES.items():
                best_match = get_close_matches(word, variants, n=1, cutoff=0.8)
                if best_match:
                    return code

        return None

    def _download_file_as_base64(self, service, file_to_download):
        """Download a file from Google Drive into memory and return a base64 data URI."""

        file_id = file_to_download.get("id")
        mime_type = file_to_download.get("mimeType", "application/octet-stream")

        print(
            f"Attempting to download file ID {file_id} - {file_to_download.get('name')}"
        )

        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print(f"Download {int(status.progress() * 100)}.")

        fh.seek(0)
        b64 = base64.b64encode(fh.read()).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    async def get_offer_link(
        self, actual_session
    ) -> tuple[str, str] | tuple[None, None]:
        gdrive_settings = get_google_drive_settings()
        service = build_drive_service()
        files = await list_files_in_folder(service, gdrive_settings.FOLDER_ID)
        num_travelers = actual_session.get("num_travelers")
        num_underage_travelers = actual_session.get("num_underage_travelers")

        # Filter files: ensure both destination and departure iata code appear in the file name (case-insensitive).
        filtered_files = [
            f
            for f in files
            if actual_session["destination"].lower() in f.get("name").lower()
            and actual_session["departure_iata_code"].lower() in f.get("name").lower()
        ]

        if len(filtered_files) == 0:
            return None, None

        file_to_download = None

        if not num_underage_travelers:
            for f in filtered_files:
                if f"{num_travelers} ADL" in f.get("name") and not "MENOR" in f.get(
                    "name"
                ):
                    file_to_download = f
                    break
        else:
            for f in filtered_files:
                if f"{num_travelers} ADL" in f.get(
                    "name"
                ) and f"{num_underage_travelers} MENOR" in f.get("name"):
                    file_to_download = f
                    break

        if file_to_download:
            return self._download_file_as_base64(
                service, file_to_download
            ), file_to_download.get("name")
        else:
            return None, None

    def get_offer_for_destination_key(self, destination_key: str) -> dict:
        """
        Returns the offer data for a given destination key.
        """
        dest_lower = destination_key.lower()
        return self.offers_db.get(dest_lower)

    def get_offer_summary_for_destination_key(self, destination_key: str) -> str | None:
        """
        Return a summary for the given offer, or None if the destination key is unknown.
        """
        offer = self.get_offer_for_destination_key(destination_key)
        if offer is None:
            return None
        return offer.get("summary_for_bot")

    def get_message_offer(self, actual_session: dict) -> str | None:
        """
        Look up a pre-built offer by destination + passenger count.

        New key format: "{destination}_{adults}_{minors}"  (no IATA departure)
        """
        destination = actual_session.get("destination", "")
        num_travelers = actual_session.get("num_travelers")
        num_underage_travelers = actual_session.get("num_underage_travelers")

        key = f"{destination.lower()}_{num_travelers}_{num_underage_travelers}"
        entry = self.offers_db.get(key)

        if not entry or not isinstance(entry, dict):
            return None

        return entry.get("message")

    def normalize_text(self, text: str) -> str:
        text = re.sub(r"[^a-záéíóúñ0-9 ]", " ", text.lower())
        return text
