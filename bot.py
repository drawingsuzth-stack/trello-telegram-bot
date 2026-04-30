import os
import requests
import time
from flask import Flask
import threading
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot ishlayapti!"

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, data=data)

def get_cards():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/cards"
    params = {
        "key": TRELLO_KEY,
        "token": TRELLO_TOKEN
    }
    return requests.get(url, params=params).json()

def get_lists():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/lists"
    params = {
        "key": TRELLO_KEY,
        "token": TRELLO_TOKEN
    }
    return requests.get(url, params=params).json()

def get_report():
    cards = get_cards()
    lists = get_lists()

    list_map = {l["id"]: l["name"] for l in lists}

    jami = len(cards)
    yopilgan = 0
    jarayonda = 0
    kechikkan = 0

    # 👇 XODIM BO‘YICHA HISOB
    employees = {}

    today = datetime.utcnow()

    for c in cards:
        list_name = list_map.get(c["idList"], "").lower()

        # 🔴 YOPILGAN
        if "yopilgan" in list_name:
            yopilgan += 1
        else:
            jarayonda += 1

        # 🔴 KECHIKKAN
        if c.get("due"):
            due_date = datetime.strptime(c["due"][:10], "%Y-%m-%d")
            if due_date < today and "yopilgan" not in list_name:
                kechikkan += 1

        # 🔴 XODIM HISOBI
        if "yopilgan" not in list_name:
            employees[list_name] = employees.get(list_name, 0) + 1

    # 🔥 TEXT
    text = f"""📊 Xarid bo‘limi hisobot

📦 UMUMIY ZAYAVKALAR
Jami: {jami} ta
Jarayonda: {jarayonda} ta
Yopilgan: {yopilgan} ta
Kechikkan: {kechikkan} ta

👨‍💼 XODIMLAR:
"""

    for emp, count in employees.items():
        text += f"\n- {emp.title()}: {count} ta"

    return text

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
