import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))
TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID")

DONE_LIST_NAME = "YOPILGAN"

app = Flask(__name__)

processed_updates = set()


@app.route("/")
def home():
    return "Bot ishlayapti ✅"


def telegram_api(method, data=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    return requests.post(url, data=data, timeout=30).json()


def send_message(text):
    telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text
    })


def trello_get(path, extra=None):
    params = {
        "key": TRELLO_KEY,
        "token": TRELLO_TOKEN
    }

    if extra:
        params.update(extra)

    url = f"https://api.trello.com/1/{path}"
    response = requests.get(url, params=params, timeout=30)

    if response.status_code != 200:
        return []

    return response.json()


def get_cards():
    return trello_get(f"boards/{BOARD_ID}/cards", {
        "customFieldItems": "true",
        "labels": "all"
    })


def get_lists():
    return trello_get(f"boards/{BOARD_ID}/lists")


def get_board_data():
    cards = get_cards()
    lists = get_lists()

    list_map = {item["id"]: item["name"] for item in lists}
    return cards, list_map


def is_done(list_name):
    return list_name.strip().upper() == DONE_LIST_NAME


def is_overdue(card, list_name):
    if is_done(list_name):
        return False

    if not card.get("due"):
        return False

    try:
        due_date = datetime.strptime(card["due"][:10], "%Y-%m-%d")
        return due_date.date() < datetime.utcnow().date()
    except Exception:
        return False


def get_card_type(card):
    text = card.get("name", "").lower()

    for label in card.get("labels", []):
        text += " " + label.get("name", "").lower()

    if "mahalliy" in text:
        return "Mahalliy"

    if "import" in text:
        return "Import"

    if "aralash" in text:
        return "Aralash"

    return "Aniqlanmagan"


def generate_report():
    cards, list_map = get_board_data()

    total = len(cards)
    done_count = 0
    active_count = 0
    overdue_count = 0
    no_due_count = 0

    type_stats = {}
    employee_stats = {}

    for card in cards:
        list_name = list_map.get(card.get("idList"), "Noma’lum ustun")

        if is_done(list_name):
            done_count += 1
        else:
            active_count += 1

        if is_overdue(card, list_name):
            overdue_count += 1

        if not card.get("due") and not is_done(list_name):
            no_due_count += 1

        card_type = get_card_type(card)
        type_stats[card_type] = type_stats.get(card_type, 0) + 1

        if not is_done(list_name):
            if list_name not in employee_stats:
                employee_stats[list_name] = {
                    "total": 0,
                    "overdue": 0,
                    "no_due": 0
                }

            employee_stats[list_name]["total"] += 1

            if is_overdue(card, list_name):
                employee_stats[list_name]["overdue"] += 1

            if not card.get("due"):
                employee_stats[list_name]["no_due"] += 1

    text = "📊 Xarid bo‘limi hisobot\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📦 UMUMIY ZAYAVKALAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Jami: {total} ta\n"
    text += f"Jarayonda: {active_count} ta\n"
    text += f"Yopilgan: {done_count} ta\n"
    text += f"Kechikkan: {overdue_count} ta\n"
    text += f"Muddatsiz: {no_due_count} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📌 ZAYAVKA TURI BO‘YICHA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    for name, count in sorted(type_stats.items()):
        text += f"{name}: {count} ta\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n"
    text += "👨‍💼 XODIMLAR BO‘YICHA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    for employee, data in sorted(employee_stats.items()):
        text += f"\n🔹 {employee}\n"
        text += f"   Jarayonda: {data['total']} ta\n"
        text += f"   Kechikkan: {data['overdue']} ta\n"
        text += f"   Muddatsiz: {data['no_due']} ta\n"

    return text


def get_latest_update_id():
    try:
        result = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            timeout=20
        ).json()

        updates = result.get("result", [])

        if not updates:
            return None

        return updates[-1]["update_id"]

    except Exception:
        return None


def bot_loop():
    last_update_id = get_latest_update_id()

    while True:
        try:
            params = {
                "timeout": 20
            }

            if last_update_id is not None:
                params["offset"] = last_update_id + 1

            result = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params=params,
                timeout=30
            ).json()

            for update in result.get("result", []):
                update_id = update["update_id"]
                last_update_id = update_id

                if update_id in processed_updates:
                    continue

                processed_updates.add(update_id)

                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "").strip().lower()

                if chat_id != CHAT_ID:
                    continue

                if text in ["/hisobot", "hisobot"]:
                    send_message(generate_report())

        except Exception as e:
            print("Xato:", e)

        time.sleep(1)


if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
