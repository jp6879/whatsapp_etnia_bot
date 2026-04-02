import ast
import copy
import logging

from typing import Any, Dict, List, Optional
from redis import Redis
from app.core.enums import TotalStates

logger = logging.getLogger("redis_service")

SESSION_PREFIX = "wa_session:"


class RedisService:
    def __init__(self, client: Redis):
        self.client = client

    def lower_format(self, text: Any) -> str:
        return (
            text.encode("utf-8", "ignore").decode("utf-8").lower().replace("None", "")
            if isinstance(text, str)
            else text
        )

    def get_all_data(self) -> List[Dict[str, Any]]:
        """Getting all the data from the redis"""
        keys = self.client.keys("wa_session:*")
        data_list = []
        data = {}
        for k in keys:
            actual_dict = ast.literal_eval((self.client.get(k)).replace("null", "None"))
            destination = self.lower_format(actual_dict.get("destination", ""))
            departure_iata_code = self.lower_format(
                actual_dict.get("departure_iata_code", "")
            )
            departure_month = self.lower_format(actual_dict.get("departure_month", ""))
            num_travelers_message = self.lower_format(
                actual_dict.get("num_travelers_message", "")
            )
            num_adults = actual_dict.get("num_travelers")
            num_minors = actual_dict.get("num_underage_travelers")
            num_travelers_detected = (
                f"{num_adults if num_adults is not None else '-'} ADULTOS"
                f" - {num_minors if num_minors is not None else '-'} NIÑOS"
                if num_adults is not None or num_minors is not None
                else ""
            )
            full_name = self.lower_format(actual_dict.get("full_name", ""))

            departure_location = self.lower_format(
                actual_dict.get("departure_location", "")
            )

            data["FECHA"] = actual_dict.get("date_of_contact")
            data["TELEFONO"] = k.removeprefix("wa_session:").split("@")[0]
            data["NOMBRE"] = (
                full_name.split(" ")[0] if len(full_name.split(" ")) >= 1 else ""
            )
            data["APELLIDO"] = (
                full_name.split(" ")[1] if len(full_name.split(" ")) >= 2 else ""
            )
            data["DESTINO"] = f"{destination}"
            data["SALIDA DETECTADA"] = (
                f"{departure_iata_code}" if departure_iata_code else ""
            )
            data["FECHA DEL VIAJE"] = f"{departure_month}"
            data["CANTIDAD DE PASAJEROS"] = num_travelers_detected
            data["RESUMEN DE VIAJE"] = " - ".join(
                filter(
                    None, [num_travelers_message, departure_location, departure_month]
                )
            )
            raw_state = actual_dict.get("state")
            try:
                data["ESTADO"] = TotalStates[raw_state].lower()
            except KeyError:
                data["ESTADO"] = raw_state or "desconocido"
            data["RED SOCIAL"] = "WHATSAPP"
            data_list.append(copy.deepcopy(data))

        return data_list

    def _format_session_row(self, key: str, actual_dict: dict) -> Dict[str, Any]:
        """Format a raw Redis session dict into the flat row structure used by Sheets."""
        data: Dict[str, Any] = {}
        destination = self.lower_format(actual_dict.get("destination", ""))
        departure_iata_code = self.lower_format(
            actual_dict.get("departure_iata_code", "")
        )
        departure_month = self.lower_format(actual_dict.get("departure_month", ""))
        num_travelers_message = self.lower_format(
            actual_dict.get("num_travelers_message", "")
        )
        num_adults = actual_dict.get("num_travelers")
        num_minors = actual_dict.get("num_underage_travelers")
        num_travelers_detected = (
            f"{num_adults if num_adults is not None else '-'} ADULTOS"
            f" - {num_minors if num_minors is not None else '-'} NIÑOS"
            if num_adults is not None or num_minors is not None
            else ""
        )
        full_name = self.lower_format(actual_dict.get("full_name", ""))
        departure_location = self.lower_format(
            actual_dict.get("departure_location", "")
        )

        data["FECHA"] = actual_dict.get("date_of_contact")
        data["TELEFONO"] = key.removeprefix(SESSION_PREFIX).split("@")[0]
        data["NOMBRE"] = (
            full_name.split(" ")[0] if len(full_name.split(" ")) >= 1 else ""
        )
        data["APELLIDO"] = (
            full_name.split(" ")[1] if len(full_name.split(" ")) >= 2 else ""
        )
        data["DESTINO"] = f"{destination}"
        data["SALIDA DETECTADA"] = (
            f"{departure_iata_code}" if departure_iata_code else ""
        )
        data["FECHA DEL VIAJE"] = f"{departure_month}"
        data["CANTIDAD DE PASAJEROS"] = num_travelers_detected
        data["RESUMEN DE VIAJE"] = " - ".join(
            filter(None, [num_travelers_message, departure_location, departure_month])
        )
        raw_state = actual_dict.get("state")
        try:
            data["ESTADO"] = TotalStates[raw_state].lower()
        except KeyError:
            data["ESTADO"] = raw_state or "desconocido"
        data["RED SOCIAL"] = "WHATSAPP"
        return data

    def get_session_row(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """
        Read and format a single session from Redis by phone number.

        Returns the formatted row dict (same structure as get_all_data entries),
        or None if the session key does not exist.
        """
        key = f"{SESSION_PREFIX}{phone_number}"
        raw = self.client.get(key)
        if not raw:
            logger.warning("[get_session_row] Key not found: %s", key)
            return None
        try:
            actual_dict = ast.literal_eval(raw.replace("null", "None"))
            return self._format_session_row(key, actual_dict)
        except Exception as exc:
            logger.error("[get_session_row] Failed to parse session %s: %s", key, exc)
            return None
