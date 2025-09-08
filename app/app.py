from fastapi import FastAPI, status
from pydantic import BaseModel
from .config import meta_settings

app = FastAPI()


@app.webhooks.get("/recieve")
def verify_token(mode: str, challenge: str, token: str):
    if mode == "subscribe" and token == meta_settings.WHATSAPP_VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return status.HTTP_200_OK, challenge

    print("WEBHOOK_VERIFICATION_FAILED")
    return status.HTTP_403_FORBIDDEN


@app.webhooks.post("/send")
def send_message(payload: BaseModel):
    print(payload)
    return status.HTTP_200_OK
