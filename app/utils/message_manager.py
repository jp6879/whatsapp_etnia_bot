import re
import token
from dataclasses import dataclass
import json
import io
import base64
import requests
from googleapiclient.http import MediaIoBaseDownload

from pyparsing import Optional
from app.utils.list_drive import build_drive_service, list_files_in_folder
import spacy
from difflib import get_close_matches
import os
from dotenv import load_dotenv, find_dotenv
from app.config import gdrive_settings


import json
from functools import lru_cache
from pathlib import Path


def load_ads_config():
    """Load ads config with caching for performance"""
    config_path = gdrive_settings.ADS_FILE_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


class MessageManager:
    NUM_WORDS = {
        "uno": 1,
        "un": 1,
        "una": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
        "once": 11,
        "doce": 12,
        "trece": 13,
        "catorce": 14,
        "quince": 15,
        "dieciséis": 16,
        "dieciseis": 16,
        "diecisiete": 17,
        "dieciocho": 18,
        "diecinueve": 19,
        "veinte": 20,
    }
    CITIES = {
        "BUE": [
            "buenos aires",
            "bsas",
            "bs as",
            "caba",
            "bue",
            "capital federal",
            "ciudad autonoma de buenos aires",
            "baires",
            "buenos aires ciudad",
            "buenos aires capital",
            "buenosaires",
        ],
        "COR": [
            "cordoba",
            "cba",
            "cor",
            "cordoba capital",
            "cordoba ciudad",
            "cordoba argentina",
        ],
        "MDZ": ["mendoza", "mdz", "mendoza ciudad", "mendoza capital"],
        "ROS": [
            "rosario",
            "ros",
            "rosario santa fe",
            "rosario ciudad",
            "rosario argentina",
        ],
        "IGR": [
            "iguazu",
            "puerto iguazu",
            "igr",
            "iguazú",
            "puerto iguazú",
            "cataratas",
            "cataratas del iguazu",
        ],
        "USH": ["ushuaia", "ush", "ushuaia tierra del fuego", "ushuaia argentina"],
        "SLA": ["salta", "sla", "salta capital", "salta ciudad"],
        "BRC": ["bariloche", "san carlos de bariloche", "brc", "bariloche ciudad"],
        "FTE": ["el calafate", "calafate", "fte", "el calafate santa cruz"],
        "TUC": ["tucuman", "san miguel de tucuman", "tuc", "tucumán"],
        "MDP": ["mar del plata", "mdp", "mar del plata ciudad"],
    }

    MONTHS = {
        "enero": ["01", "enero", "ene"],
        "febrero": ["02", "febrero", "feb"],
        "marzo": ["03", "marzo", "mar"],
        "abril": ["04", "abril", "abr"],
        "mayo": ["05", "mayo", "may"],
        "junio": ["06", "junio", "jun"],
        "julio": ["07", "julio", "jul"],
        "agosto": ["08", "agosto", "ago"],
        "septiembre": ["09", "septiembre", "sep", "setiembre"],
        "octubre": ["10", "octubre", "oct"],
        "noviembre": ["11", "noviembre", "nov"],
        "diciembre": ["12", "diciembre", "dic"],
    }

    def __init__(self):
        self.encoded_ads = load_ads_config()

    async def get_destination_by_message(self, message: str) -> str:
        """Fast lookup: message -> destination"""
        ad_info = self.encoded_ads.get(message, {})
        return ad_info.get("ad_destination", "unknown")

    async def get_iata_code(self, text: str):
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

    async def get_seassonal_offer_link(self, actual_session):
        service = build_drive_service()
        files = await list_files_in_folder(service, gdrive_settings.FOLDER_ID_SEASONAL)
        num_travelers = actual_session.get("num_travelers")
        num_underage_travelers = actual_session.get("num_underage_travelers")
        month = actual_session.get("departure_month")
        departure = actual_session.get("departure_iata_code")

        if not num_underage_travelers:
            filtered_files = [
                f
                for f in files
                if departure.lower() in f.get("name").lower()
                and month in f.get("name").lower()
                and f"{num_travelers} adultos" in f.get("name").lower()
            ]

        if len(filtered_files) == 0:
            return None, None

        file_to_download = filtered_files[0]

        return self._download_file_as_base64(
            service, file_to_download
        ), file_to_download.get("name")

    async def extract_number_of_persons(self, text: str) -> dict:
        """Extract number of adults, minors and total from a short Spanish travel text.

        Returns a dict: {"adults": int, "minors": int, "total": int}
        """
        # Convert to lowercase and remove punctuation or special characters
        text_norm = self.normalize_text(text)

        if len(text_norm.split()) == 1:
            # Single word, could be a number word or digit
            if text_norm.isdigit():
                n = int(text_norm)
                return {"adults": n, "minors": 0, "total": n}
            else:
                n = self.word_to_num(text_norm)
                if n is not None:
                    return {"adults": n, "minors": 0, "total": n}
                else:
                    return {"adults": 0, "minors": 0, "total": 0}

        # Explicit counts
        adults = 0
        minors = 0

        # patterns: digits attached to keywords
        # Don't count "X personas" as adults if it's likely the total
        adult_pattern = r"adultos?|mayores|adulto|grandes?|familia de|familia|vamos a ser|grupo de|en total"

        # Check if "personas" is likely referring to total (when minors are mentioned separately)
        if not re.search(
            r"(\d+)\s+personas.*(\d+)\s+(menores?|niñ[oa]s?|chicos?)", text_norm
        ):
            # It's safe to count "personas" as adults
            adult_pattern += r"|personas?"

        adult_pattern += r"|pasajeros?"

        adults += self._num_near_keyword(text_norm, adult_pattern)
        minors += self._num_near_keyword(
            text_norm,
            r"niñ[oa]s?|menores?|menor|chicos?|hijos?|bebe|bebes|de \d+ meses|de \d+ años",
        )

        total = self._find_total(text_norm)

        a_add, m_add = self._word_numbers_near_keywords(text_norm)
        adults += a_add
        minors += m_add

        # Handle implicit references like "voy con mi marido" or "matrimonio y un hijo"
        implicit_adults, implicit_minors = self._extract_implicit_persons(text_norm)
        adults += implicit_adults
        minors += implicit_minors

        # Logic for reconciling total with adults/minors
        if total is not None:
            if adults > 0 and minors > 0:
                # If we have explicit adults and minors, check if they add up to total
                explicit_sum = adults + minors
                if explicit_sum > total:
                    # Trust the explicit breakdown
                    total = explicit_sum
                elif explicit_sum < total:
                    # Could be some implicit persons, keep total as is
                    total = total
            elif adults > 0 and minors == 0:
                # Only adults specified
                if adults > total:
                    total = adults
            elif adults == 0 and minors > 0:
                # Only minors specified, calculate adults from total
                adults = max(total - minors, 0)
            elif adults == 0 and minors == 0:
                # No explicit breakdown, assume all adults
                adults = total
        else:
            # No total found, calculate from parts
            # Special case: if we only have a bare number with "no hay menores"
            if re.search(r"\b(\d+)\b.*no hay menores?", text_norm):
                m = re.search(r"\b(\d+)\b", text_norm)
                if m and adults == 0:
                    adults = int(m.group(1))

            total = adults + minors

        return {"adults": int(adults), "minors": int(minors), "total": int(total)}

    def normalize_text(self, text: str) -> str:
        text = re.sub(r"[^a-záéíóúñ0-9 ]", " ", text.lower())
        # Handle matrimonio/pareja BEFORE other replacements
        text = text.replace("un matrimonio", "2 adultos")
        text = text.replace("matrimonio", "2 adultos")
        text = text.replace("una pareja", "2 adultos")
        text = text.replace("dos matrimonios", "4 adultos")
        text = text.replace("dos parejas", "4 adultos")
        text = text.replace("1 matrimonio", "2 adultos")
        text = text.replace("1 pareja", "2 adultos")
        text = text.replace("2 matrimonios", "4 adultos")
        text = text.replace("2 parejas", "4 adultos")
        # Keep these patterns
        text = text.replace("un chico", "1 menor")
        # Adolescents are typically adults for travel purposes
        text = text.replace("adolescente", "adulto")
        text = text.replace("adolescentes", "adultos")
        return text

    def word_to_num(self, token: str) -> int:
        return self.NUM_WORDS.get(token.lower())

    def _num_near_keyword(self, text: str, keyword_pattern: str):
        """Sum explicit digit mentions that directly precede a keyword (e.g., '2 adultos') or follow it."""
        results = 0
        digit_pattern = re.compile(r"(\d+)\s*(?:" + keyword_pattern + r")")
        for m in digit_pattern.finditer(text):
            results += int(m.group(1))
        if results == 0:
            # Find after the keyword too (e.g., 'familia de 2')
            digit_pattern = re.compile(r"(?:" + keyword_pattern + r")\s*(\d+)")
            for m in digit_pattern.finditer(text):
                results += int(m.group(1))
            return results
        return results

    def _word_numbers_near_keywords(self, text: str, max_dist: int = 25):
        """Assign word-number occurrences to the nearest adult or minor keyword.

        Returns tuple (adults_sum, minors_sum)
        """
        words = self._find_word_numbers(text)
        if not words:
            return 0, 0

        adult_kw = list(
            re.finditer(
                r"adultos?|mayores|adulto|grandes?|en total|viajamos|pasajeros?", text
            )
        )
        minor_kw = list(
            re.finditer(r"niñ[oa]s?|menores?|menor|chicos?|hijos?|bebe|bebes", text)
        )

        adults_sum = 0
        minors_sum = 0

        for num, s, e in words:
            # compute nearest adult/minor distance
            best_adult_dist = None
            for m in adult_kw:
                dist = min(abs(s - m.start()), abs(e - m.end()))
                if best_adult_dist is None or dist < best_adult_dist:
                    best_adult_dist = dist

            best_minor_dist = None
            for m in minor_kw:
                dist = min(abs(s - m.start()), abs(e - m.end()))
                if best_minor_dist is None or dist < best_minor_dist:
                    best_minor_dist = dist

            # decide assignment based on nearest distance and a max distance threshold
            if (
                best_adult_dist is not None
                and (best_minor_dist is None or best_adult_dist < best_minor_dist)
                and best_adult_dist <= max_dist
            ):
                adults_sum += num
            elif (
                best_minor_dist is not None
                and (best_adult_dist is None or best_minor_dist < best_adult_dist)
                and best_minor_dist <= max_dist
            ):
                minors_sum += num
            # else: skip (could be total or unrelated)

        return adults_sum, minors_sum

    def _find_word_numbers(self, text: str):
        # returns list of tuples (num, span_start, span_end)
        words_pattern = "|".join(
            sorted((re.escape(w) for w in self.NUM_WORDS.keys()), key=len, reverse=True)
        )
        pattern = re.compile(r"\b(" + words_pattern + r")\b")
        results = []
        for m in pattern.finditer(text):
            num = self.word_to_num(m.group(1))
            if num is not None:
                results.append((num, m.start(), m.end()))
        return results

    def _find_total(self, text: str) -> int:
        # patterns like "somos 5 personas", "viajan 3", "viajamos 3", "seriamos 4"
        m = re.search(r"(somos|seriamos|serian|seran)\s+(\d+)\b", text)
        if m:
            return int(m.group(2))

        # digits for travel verb: "viajan 3", "viajamos 2"
        m = re.search(r"viaj\w*\s+(\d+)\b", text)
        if m:
            return int(m.group(1))

        # patterns like "familia de 4", "grupo de 3", "vamos a ser 5"
        m = re.search(
            r"(familia|grupo|somos|viajamos|viajan|vamos a ser|seriamos)\s+de\s+(\d+)\b",
            text,
        )
        if m:
            return int(m.group(2))

        # Look for "X personas" pattern (e.g., "4 personas")
        m = re.search(r"(\d+)\s+personas?", text)
        if m:
            num = int(m.group(1))
            # Check if there are explicit minors mentioned separately
            # If so, this might be the total, not just adults
            if re.search(r"(\d+)\s+menores?", text) or re.search(
                r"(\d+)\s+niñ[oa]s?", text
            ):
                return num  # Return as total
            return num

        # Look for "X pasajeros" pattern
        m = re.search(r"(\d+)\s+pasajeros?", text)
        if m:
            return int(m.group(1))

        # word-number variants
        words = self._find_word_numbers(text)
        for num, s, e in words:
            # look after the word for keywords
            window_after = text[e : e + 25]
            if (
                re.search(r"personas?", window_after)
                or re.search(r"viaj", window_after)
                or re.search(r"somos", window_after)
                or re.search(r"familia de", window_after)
                or re.search(r"grupo", window_after)
                or re.search(r"una familia de", window_after)
                or re.search(r"pasajeros?", window_after)
            ):
                return num
            # or look before the word for 'somos'/'viajamos'/'seriamos'
            window_before = text[max(0, s - 20) : s]
            if re.search(r"(somos|seriamos|viaj)", window_before):
                return num

        return None

    def _extract_implicit_persons(self, text: str) -> tuple:
        """Extract implicit person counts from phrases like 'voy con mi marido'.

        Returns tuple (implicit_adults, implicit_minors)
        """
        implicit_adults = 0
        implicit_minors = 0

        # "voy con mi marido" = 2 adults (speaker + spouse)
        if re.search(r"voy con mi (marido|esposo|esposa|mujer)", text):
            implicit_adults += 2

        # Check if we've already processed matrimonio -> adultos
        # to avoid double counting in "matrimonio con X hijos"
        has_matrimonio_replacement = re.search(r"2 adultos con", text)

        # "mis X hijos" = X minors (if X is already captured, skip)
        # Only count if not already matched by digit patterns
        if not has_matrimonio_replacement:
            m = re.search(r"(\d+) hijos?", text)
            if m:
                # Check if this wasn't already counted via _num_near_keyword
                num_hijos = int(m.group(1))
                # We'll let _num_near_keyword handle this, so skip here
                pass

        return implicit_adults, implicit_minors

    def get_month_from_message(self, message: str) -> str | None:
        text_norm = self.normalize_text(message)

        for month, variants in self.MONTHS.items():
            for variant in variants:
                if variant in text_norm:
                    return month

        return None
