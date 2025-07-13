from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Get environment variables
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")


@app.route("/webhook", methods=["GET"])
def verify_token():
    try:
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if token == WHATSAPP_VERIFY_TOKEN and challenge:
            return challenge
        else:
            return "Invalid token", 403
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        # Process incoming webhook data here
        print("Received webhook data:", data)
        return "OK", 200
    except Exception as e:
        return f"Error: {str(e)}", 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
