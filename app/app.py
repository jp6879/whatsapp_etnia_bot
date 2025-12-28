from datetime import datetime
import pytz
from fastapi import FastAPI, Request, HTTPException
from app.session.session import RedisSessionDep
from app.utils.message_manager import MessageManager
from app.utils.whatsapp import SessionState, send_whatsapp_text
import io
import base64
from googleapiclient.http import MediaIoBaseDownload
from app.seasons_sm import SeasonalSM


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
seasonal_sm = SeasonalSM(message_manager)


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

    if not await redis_session.load_session():
        ad_destination = await message_manager.get_destination_by_message(body)
        actual_session = {
            "state": SessionState.GETTING_AD_DESTINATION,
            "destination": ad_destination,
            "num_travelers": 0,
            "num_underage_travelers": 0,
            "departure_location": None,
            "departure_iata_code": None,
            "date_of_contact": datetime.now(
                pytz.timezone("America/Argentina/Buenos_Aires")
            ).strftime("%Y-%m-%d %H:%M"),
            "count_requests": 1,
        }

        if actual_session.get("destination") != "unknown":
            # send initial greeting + first question
            actual_session["state"] = SessionState.ASKING_NUM_TRAVELERS
            await send_whatsapp_text(
                from_number,
                "¡Hola Viajero! 👋🏻 Somos Agos y Meli de Etnia Viajes ✨\n\n"
                f"Nos escribiste por un viaje a: {ad_destination}.\n"
                "Contame ¿para cuántas personas te interesa? Si hay menores en el grupo, decinos cuántos.",
            )
            await redis_session.save_session(actual_session)
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

    if state == SessionState.ASKING_NUM_TRAVELERS:

        num_travelers_dict = await message_manager.extract_number_of_persons(body)

        if not num_travelers_dict or num_travelers_dict["total"] < 1:

            actual_session["state"] = SessionState.HANDOFF_NO_TRAVELERS
            await redis_session.save_session(actual_session)
            return await send_whatsapp_text(
                from_number,
                "En breve te contactamos para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )

        actual_session["num_travelers"] = num_travelers_dict["adults"]
        actual_session["num_underage_travelers"] = num_travelers_dict["minors"]

        actual_session["state"] = SessionState.ASKING_DEPARTURE
        await redis_session.save_session(actual_session)

        await send_whatsapp_text(
            from_number, "Perfecto. ¿Desde dónde te gustaría salir?"
        )
        return {"status": "ok"}

    if (
        state == SessionState.ASKING_DEPARTURE
        or state == SessionState.ASKING_DEPARTURE_DATE
    ):
        if (
            actual_session["departure_location"] is None
            and actual_session["departure_iata_code"] is None
        ):
            actual_session["departure_location"] = body
            departure_iata = await message_manager.get_iata_code(body)
            actual_session["departure_iata_code"] = departure_iata

            if not departure_iata:
                actual_session["state"] = SessionState.HANDOFF_NO_DEPARTURE
                await redis_session.save_session(actual_session)
                return await send_whatsapp_text(
                    from_number,
                    "En breve te contactamos para encontrar el paquete ideal para vos. ¡Gracias! 😊",
                )

        if actual_session.get("destination") == "Puerto Iguazú":
            actual_session = await seasonal_sm.seasonal_state_machine_workflow(
                actual_session, from_number, body
            )
            await redis_session.save_session(actual_session)

            if actual_session.get("state") == SessionState.HANDOFF_WITH_OFFER:
                return await send_whatsapp_text(
                    from_number,
                    "¡Excelente! Ahora te enviamos el paquete ideal para vos. ¡Gracias! 😊",
                    media=seasonal_sm.offer_link,
                    file_name=seasonal_sm.file_name,
                )
                await send_whatsapp_text(
                    from_number,
                    "✨ Decime si esta opción es la que buscás o si preferís que la acomodemos (fecha, hotel, compañía), o si querés que te enviemos otras opciones.",
                )

            return {"status": "ok"}

        offer_link, file_name = await message_manager.get_offer_link(actual_session)

        if not offer_link:
            actual_session["state"] = SessionState.HANDOFF_NO_OFFER
            await redis_session.save_session(actual_session)
            return await send_whatsapp_text(
                from_number,
                "En breve te contactamos para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )

        await redis_session.save_session(actual_session)

        await send_whatsapp_text(
            from_number,
            "Te envío una propuesta ideal para vos 🛩️",
            media=offer_link,
            file_name=file_name,
        )

        await send_whatsapp_text(
            from_number,
            "✨ Decime si esta opción es la que buscás o si preferís que la acomodemos (fecha, hotel, compañía), o si querés que te enviemos otras opciones.",
        )

        actual_session["state"] = SessionState.HANDOFF_WITH_OFFER
        await redis_session.save_session(actual_session)

        return {"status": "ok"}

    if actual_session["count_requests"] > 15 or state in SessionState.handoff_states():
        return {"status": "400", "detail": "Session ended or max requests reached"}

    return {"status": "ok"}
