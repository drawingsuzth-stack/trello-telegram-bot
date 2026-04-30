import os
import requests
from flask import Flask
import threading
import time

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot ishlayapti!"

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, data=data)

def bot_loop():
    last_update_id = None

    while True:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        if last_update_id:
            url += f"?offset={last_update_id + 1}"

        response = requests.get(url).json()

        for update in response["result"]:
            last_update_id = update["update_id"]

            if "message" in update:
                text = update["message"].get("text", "")

                if text == "/hisobot":
                    send_message("Bot ishlayapti ✅")

        time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=bot_loop).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
