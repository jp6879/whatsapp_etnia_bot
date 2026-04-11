import copy

from typing import Any, Dict, List
from redis import Redis
from app.core.enums import TotalStates
import json


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
        for k in keys:
            actual_dict = json.loads(self.client.get(k))
            destination = self.lower_format(actual_dict.get("destination", ""))
            departure_iata_code = self.lower_format(
                actual_dict.get("departure_iata_code", "")
            )
            departure_month = self.lower_format(actual_dict.get("departure_month", ""))
            num_travelers_message = self.lower_format(
                actual_dict.get("num_travelers_message", "")
            )
            num_travelers_detected = f"{actual_dict.get('num_travelers', '')} ADULTOS - {actual_dict.get('num_underage_travelers', '')} NIÑOS"
            full_name = self.lower_format(actual_dict.get("full_name", ""))

            departure_location = self.lower_format(
                actual_dict.get("departure_location", "")
            )
            data = {
                "FECHA": actual_dict.get("date_of_contact"),
                "TELEFONO": k.removeprefix("wa_session:").split("@")[0],
                "NOMBRE": (
                    full_name.split(" ")[0] if len(full_name.split(" ")) >= 1 else ""
                ),
                "APELLIDO": (
                    full_name.split(" ")[1] if len(full_name.split(" ")) >= 2 else ""
                ),
                "DESTINO": f"{destination}",
                "SALIDA DETECTADA": (
                    f"{departure_iata_code}" if departure_iata_code else ""
                ),
                "FECHA DEL VIAJE": f"{departure_month}",
                "CANTIDAD DE PASAJEROS": num_travelers_detected,
                "RESUMEN DE VIAJE": " - ".join(
                    filter(
                        None,
                        [num_travelers_message, departure_location, departure_month],
                    )
                ),
                "ESTADO": TotalStates[actual_dict.get("state")].lower(),
                "RED SOCIAL": "WHATSAPP",
            }
            data_list.append(data)

        return data_list
