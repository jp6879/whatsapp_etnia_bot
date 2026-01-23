import asyncio
import sys
import os
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.getcwd())

# Mock modules
sys.modules["requests"] = MagicMock()
sys.modules["googleapiclient"] = MagicMock()
sys.modules["googleapiclient.http"] = MagicMock()
sys.modules["spacy"] = MagicMock()
sys.modules["pyparsing"] = MagicMock()
sys.modules["app.utils.list_drive"] = MagicMock()

# Setup app.config mock
mock_config = MagicMock()
mock_config.gdrive_settings = MagicMock()
sys.modules["app.config"] = mock_config

import app.utils.message_manager as mm_module
from app.utils.message_manager import MessageManager

# Monkeypatch the global load_ads_config function
mm_module.load_ads_config = lambda: {}


async def run_tests():
    mm = MessageManager()

    test_cases = [
        ("somos dos grandes y un chico", {"adults": 2, "minors": 1}),
        ("voy con mi marido y mis dos hijos", {"adults": 2, "minors": 2}),
        ("4 personas, 2 menores", {"adults": 2, "minors": 2}),
        ("somos 3", {"adults": 3, "minors": 0}),
        (
            "hola buenas tardes queria consultar por un paquete a bariloche para 2 personas",
            {"adults": 2, "minors": 0},
        ),
        ("matrimonio con 2 hijos", {"adults": 2, "minors": 2}),
        ("2 adultos y un bebe", {"adults": 2, "minors": 1}),
        ("3 pasajeros", {"adults": 3, "minors": 0}),
        ("somos 4, 3 mayores y 1 menor", {"adults": 3, "minors": 1}),
        ("2 adultos", {"adults": 2, "minors": 0}),
        ("1 adulto 2 niños", {"adults": 1, "minors": 2}),
        ("familia de 4", {"adults": 4, "minors": 0}),
        ("somos 5", {"adults": 5, "minors": 0}),
        ("2 grandes 2 chicos", {"adults": 2, "minors": 2}),
        ("un matrimonio y un hijo", {"adults": 2, "minors": 1}),
        ("somos 2", {"adults": 2, "minors": 0}),
        ("un matrimonio", {"adults": 2, "minors": 0}),
        ("2 y no hay menores", {"adults": 2, "minors": 0}),
        ("seriamos 4", {"adults": 4, "minors": 0}),
        ("2 grande y 2 menores", {"adults": 2, "minors": 2}),
        ("2 adultos y 1 adolescente", {"adults": 3, "minors": 0}),
    ]

    print(f"{'Text':<80} | {'Expected':<20} | {'Actual':<20} | {'Result'}")
    print("-" * 140)

    for text, expected in test_cases:
        try:
            result = await mm.extract_number_of_persons(text)
            valid = True
            for k, v in expected.items():
                if result.get(k) != v:
                    valid = False
                    break

            status = "PASS" if valid else "FAIL"
            print(f"{text:<80} | {str(expected):<20} | {str(result):<20} | {status}")
        except Exception as e:
            print(f"{text:<80} | {str(expected):<20} | ERROR: {e!r:<13} | FAIL")


if __name__ == "__main__":
    asyncio.run(run_tests())
