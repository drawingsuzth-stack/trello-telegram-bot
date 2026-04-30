import os
import time
import threading
import requests
from flask import Flask

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID")

app = Flask(__name__)

@app.route("/")
def home():
    return "Diagnostika bot ishlayapti ✅"

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)

def get_trello_cards_debug():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/cards"
    params = {
        "key": TRELLO_KEY,
        "token": TRELLO_TOKEN
    }

    try:
        response = requests.get(url, params=params, timeout=30)

        text = "🧪 DIAGNOSTIKA HISOBOTI\n\n"
        text += f"BOT_TOKEN: {'BOR ✅' if BOT_TOKEN else 'YO‘Q ❌'}\n"
        text += f"CHAT_ID: {'BOR ✅' if CHAT_ID else 'YO‘Q ❌'}\n"
        text += f"TRELLO_KEY: {'BOR ✅' if TRELLO_KEY else 'YO‘Q ❌'}\n"
        text += f"TRELLO_TOKEN: {'BOR ✅' if TRELLO_TOKEN else 'YO‘Q ❌'}\n"
        text += f"BOARD_ID: {BOARD_ID if BOARD_ID else 'YO‘Q ❌'}\n\n"

        text += f"Trello status code: {response.status_code}\n"

        if response.status_code != 200:
            text += f"Trello javobi:\n{response.text[:500]}"
            return text

        cards = response.json()
        text += f"Trellodan kelgan kartalar soni: {len(cards)} ta\n"

        if len(cards) > 0:
            text += f"Birinchi karta nomi:\n{cards[0].get('name', 'Nomi yo‘q')}\n"

        return text

    except Exception as e:
        return f"❌ Diagnostika xato:\n{e}"

def bot_loop():
    last_update_id = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {}

            if last_update_id is not None:
                params["offset"] = last_update_id + 1

            result = requests.get(url, params=params, timeout=20).json()

            for update in result.get("result", []):
                last_update_id = update["update_id"]

                message = update.get("message", {})
                text = message.get("text", "").strip().lower()

                if text in ["/hisobot", "hisobot"]:
                    send_message(get_trello_cards_debug())

        except Exception as e:
            print("Bot loop xato:", e)

        time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
