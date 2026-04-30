import os
import requests
import time
from flask import Flask
import threading

# ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot ishlayapti!"

# TELEGRAMGA YUBORISH
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, data=data)

# TRELLODAN KARTALAR OLISH
def get_cards():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/cards"
    params = {
        "key": TRELLO_KEY,
        "token": TRELLO_TOKEN
    }
    response = requests.get(url, params=params)
    return response.json()

# HISOBOT
def get_report():
    cards = get_cards()

    jami = len(cards)
    yopilgan = len([c for c in cards if c["closed"]])
    jarayonda = jami - yopilgan

    text = f"""📊 Xarid bo‘limi hisobot

📦 UMUMIY ZAYAVKALAR
Jami: {jami} ta
Jarayonda: {jarayonda} ta
Yopilgan: {yopilgan} ta
"""
    return text

# BOT LOOP
def bot_loop():
    last_update_id = None

    while True:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        if last_update_id:
            url += f"?offset={last_update_id + 1}"

        res = requests.get(url).json()

        for update in res.get("result", []):
            last_update_id = update["update_id"]

            if "message" in update:
                text = update["message"].get("text", "")

                if text == "/hisobot":
                    send_message(get_report())

        time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=bot_loop).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
