from datetime import datetime, time
import pytz
from fastapi import FastAPI, Request, HTTPException
import requests
from app.config import wpp_settings
from app.session.session import RedisSessionDep
from app.utils.message_manager import MessageManager
import io
import base64
from googleapiclient.http import MediaIoBaseDownload


def download_file_as_base64(service, file_id, mime_type="application/octet-stream"):
    """
    Download a Google Drive file directly into memory and return a data URI.
    """
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    # Reset pointer to start
    fh.seek(0)
    # Encode in base64
    b64 = base64.b64encode(fh.read()).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


app = FastAPI()
message_manager = MessageManager()

WPP_ADAPTER_URL = wpp_settings.WPP_ADAPTER_URL


async def send_whatsapp_text(
    to_whatsapp: str, body: str, media: str = None, file_name: str = None
):
    payload = {
        "to": to_whatsapp,
        "message": body,
        "authKey": wpp_settings.AUTH_SESSION_KEY,
    }
    if media:
        payload["mediaUrl"] = media
        payload["fileName"] = file_name
    try:
        requests.post(WPP_ADAPTER_URL, json=payload)
    except Exception as e:
        print("Error sending message via WPPConnect:", e)
        raise


@app.post("/webhook")
async def whatsapp_webhook(request: Request, redis_session: RedisSessionDep):
    data = await request.json()
    from_number = data.get("From")
    body = data.get("Body", "").strip()
    print(f"Received message from {from_number}: {body}")

    if not from_number or not body:
        raise HTTPException(
            status_code=400, detail="Missing From number or Body in webhook payload"
        )

    if not redis_session.load_session():
        ad_destination = await message_manager.get_destination_by_message(body)
        actual_session = {
            "state": "getting_ad_destination",
            "destination": ad_destination,
            "num_travelers": 0,
            "num_underage_travelers": 0,
            "departure_location": None,
            "iata_code": None,
            "date_of_contact": datetime.now(
                pytz.timezone("America/Argentina/Buenos_Aires")
            ).strftime("%Y-%m-%d %H:%M"),
            "count_requests": 1,
        }

        if actual_session.get("destination") != "unknown":
            # send initial greeting + first question
            actual_session["state"] = "asking_num_travelers"
            await send_whatsapp_text(
                from_number,
                "¡Hola! 👋🏻 Somos Agos y Meli de Etnia Viajes ✨\n\n"
                f"Nos escribiste por un paquete a: {ad_destination}.\n"
                "Contame ¿cuántas personas viajan? Si hay menores por favor especificá cuántos.",
            )
            redis_session.save_session(actual_session)
            return {"status": "ok"}
        else:
            raise HTTPException(
                status_code=400, detail="Destination not recognized in message"
            )

    # if a session exists, use it
    if redis_session.session:
        actual_session = redis_session.session
        actual_session["count_requests"] += 1

    state = redis_session.state

    if state == "asking_num_travelers":

        num_travelers_dict = await message_manager.extract_number_of_persons(body)

        if not num_travelers_dict or num_travelers_dict["total"] < 1:

            actual_session["state"] = "handoff_to_agent"
            redis_session.save_session(actual_session)
            return await send_whatsapp_text(
                from_number,
                "Para ayudarte mejor, tu asesor de Etnia Viajes te ayudará con este paquete.",
            )

        actual_session["num_travelers"] = num_travelers_dict["adults"]
        actual_session["num_underage_travelers"] = num_travelers_dict["minors"]

        actual_session["state"] = "asking_departure"
        redis_session.save_session(actual_session)

        await send_whatsapp_text(
            from_number, "Perfecto. ¿Desde dónde te gustaría salir?"
        )
        return {"status": "ok"}

    if state == "asking_departure":

        actual_session["departure_location"] = body

        departure_iata = await message_manager.get_iata_code(body)

        actual_session["iata_code"] = departure_iata

        if not departure_iata:

            actual_session["state"] = "handoff_to_agent"
            redis_session.save_session(actual_session)
            return await send_whatsapp_text(
                from_number,
                "Tu asesor de Etnia Viajes te ayudará con este paquete.",
            )

        offer_link, file_name = await message_manager.get_offer_link(actual_session)

        if not offer_link:
            actual_session["state"] = "handoff_to_agent"
            redis_session.save_session(actual_session)
            return await send_whatsapp_text(
                from_number, "Tu asesor de Etnia Viajes te ayudará con este paquete."
            )

        redis_session.save_session(actual_session)

        await send_whatsapp_text(
            from_number,
            "Te envío el paquete de la promoción que te puede interesar 🛩️",
            media=offer_link,
            file_name=file_name,
        )

        await send_whatsapp_text(
            from_number,
            "En caso de no alinearse con lo que buscás o querés un paquete a medida avisame y tu asesor de Etnia Viajes se contactará en breve para ayudarte personalmente. ¡Muchas gracias! 😊",
        )

        actual_session["state"] = "handoff_to_agent"
        redis_session.save_session(actual_session)

        return {"status": "ok"}

    if actual_session["count_requests"] > 10 or state == "handoff_to_agent":
        return {"status": "400", "detail": "Session ended or max requests reached"}

    return {"status": "ok"}
