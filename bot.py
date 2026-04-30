import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("8717622332:AAFVshiMWLkQL_LB24VuWLhW51qXhHn-qj4")
CHAT_ID = os.getenv("-1003908412363")
TRELLO_KEY = os.getenv("6ca88f5a985a209852bcf9eae6f6c6c5")
TRELLO_TOKEN = os.getenv("ATTAb8ec71a6c12dbc366f8ba6e4f21ef0ce0b48c890d80fd272c8ca1de7d065247143CCD020")
BOARD_ID = os.getenv("6802a865955f066f028888bd")

DONE_LIST_NAME = "YOPILGAN"
CHECK_INTERVAL = 10

old_cards = {}
notified_alerts = set()
last_update_id = None

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot ishlayapti ✅"


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})


def get_updates():
    global last_update_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {}
    if last_update_id:
        params["offset"] = last_update_id
    return requests.get(url, params=params).json().get("result", [])


def trello_params():
    return {"key": TRELLO_KEY, "token": TRELLO_TOKEN}


def get_cards():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/cards"
    params = trello_params()
    params.update({"customFieldItems": "true", "labels": "all"})
    return requests.get(url, params=params).json()


def get_lists():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/lists"
    return requests.get(url, params=trello_params()).json()


def get_members():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/members"
    return requests.get(url, params=trello_params()).json()


def get_custom_fields():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/customFields"
    return requests.get(url, params=trello_params()).json()


def build_list_map():
    return {x["id"]: x["name"] for x in get_lists()}


def build_member_map():
    return {x["id"]: x.get("fullName") or x.get("username") or x["id"] for x in get_members()}


def build_custom_field_options_map():
    options_map = {}
    for field in get_custom_fields():
        if "zayavka turi" in field.get("name", "").lower():
            for opt in field.get("options", []):
                options_map[opt["id"]] = opt.get("value", {}).get("text", "").lower()
    return options_map


def card_created_year(card_id):
    try:
        return datetime.fromtimestamp(int(card_id[:8], 16)).year
    except:
        return None


def is_current_year_card(card):
    return card_created_year(card["id"]) == datetime.now().year


def get_card_type(card, options_map):
    for label in card.get("labels", []):
        name = label.get("name", "").lower()
        if "aralash" in name:
            return "aralash"
        if "import" in name:
            return "import"
        if "mahalliy" in name:
            return "mahalliy"

    for item in card.get("customFieldItems", []):
        value = options_map.get(item.get("idValue"), "")
        text_value = item.get("value", {}).get("text", "").lower()
        combined = value + " " + text_value

        if "aralash" in combined:
            return "aralash"
        if "import" in combined:
            return "import"
        if "mahalliy" in combined:
            return "mahalliy"

    return None


def initialize_existing_cards():
    global old_cards, notified_alerts
    cards = get_cards()
    list_map = build_list_map()

    for card in cards:
        old_cards[card["id"]] = list_map.get(card["idList"], "")
        notified_alerts.add(f"{card['id']}_nodue")
        notified_alerts.add(f"{card['id']}_soon")
        notified_alerts.add(f"{card['id']}_overdue")

    print("✅ Eski kartalar bloklandi.")


def generate_report():
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = build_list_map()
    member_map = build_member_map()
    now = datetime.utcnow()

    total = len(cards)
    done = active = overdue = no_due = 0
    per_member = {}

    for card in cards:
        list_name = list_map.get(card["idList"], "")
        is_done = list_name.upper() == DONE_LIST_NAME

        if is_done:
            done += 1
        else:
            active += 1

        if not card.get("due") and not is_done:
            no_due += 1

        if card.get("due") and not is_done:
            try:
                if datetime.fromisoformat(card["due"].replace("Z", "")) < now:
                    overdue += 1
            except:
                pass

        for member_id in card.get("idMembers", []):
            name = member_map.get(member_id, member_id)
            per_member.setdefault(name, {"total": 0, "active": 0, "done": 0})
            per_member[name]["total"] += 1
            if is_done:
                per_member[name]["done"] += 1
            else:
                per_member[name]["active"] += 1

    text = f"📊 Xarid bo‘limi hisobot — {datetime.now().year} yil\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📦 UMUMIY ZAYAVKALAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Jami zayavka: {total} ta\n"
    text += f"Jarayonda:    {active} ta\n"
    text += f"Yopilgan:     {done} ta\n"
    text += f"Kechikkan:    {overdue} ta\n"
    text += f"Muddatsiz:    {no_due} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "👤 ISHTIROKCHILAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    for name, v in per_member.items():
        text += f"🔹 {name}\n"
        text += f"   • Ishtirok: {v['total']} ta\n"
        text += f"   • Jarayonda: {v['active']} ta\n"
        text += f"   • Yopilgan: {v['done']} ta\n\n"

    return text


def generate_type_report(type_name):
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = build_list_map()
    options_map = build_custom_field_options_map()
    now = datetime.utcnow()

    total = done = active = overdue = no_due = 0

    for card in cards:
        if get_card_type(card, options_map) != type_name:
            continue

        list_name = list_map.get(card["idList"], "")
        is_done = list_name.upper() == DONE_LIST_NAME

        total += 1
        if is_done:
            done += 1
        else:
            active += 1

        if not card.get("due") and not is_done:
            no_due += 1

        if card.get("due") and not is_done:
            try:
                if datetime.fromisoformat(card["due"].replace("Z", "")) < now:
                    overdue += 1
            except:
                pass

    title = {"mahalliy": "MAHALLIY", "import": "IMPORT", "aralash": "ARALASH"}[type_name]

    return f"""📦 {title} zayavkalar — {datetime.now().year} yil

━━━━━━━━━━━━━━━━━━
Jami zayavka: {total} ta
Jarayonda:    {active} ta
Yopilgan:     {done} ta
Kechikkan:    {overdue} ta
Muddatsiz:    {no_due} ta
━━━━━━━━━━━━━━━━━━"""


def check_changes():
    global old_cards, notified_alerts

    cards = get_cards()
    list_map = build_list_map()
    current_cards = {}
    now = datetime.utcnow()

    for card in cards:
        card_id = card["id"]
        card_name = card["name"]
        list_name = list_map.get(card["idList"], "")
        old_list = old_cards.get(card_id)
        current_cards[card_id] = list_name

        if not is_current_year_card(card):
            continue

        if card_id not in old_cards and list_name.upper() != DONE_LIST_NAME:
            send_message(f"🆕 Yangi zayavka\n\n📌 {card_name}\n📂 Ustun: {list_name}")

        elif old_list and old_list.upper() != DONE_LIST_NAME and list_name.upper() == DONE_LIST_NAME:
            send_message(
                f"✅ Zayavka yopildi\n\n"
                f"📌 {card_name}\n"
                f"📂 Qaysi ustundan yopildi: {old_list}\n"
                f"📂 Hozirgi ustun: {list_name}"
            )

        if not card.get("due") and list_name.upper() != DONE_LIST_NAME:
            key = f"{card_id}_nodue"
            if key not in notified_alerts:
                send_message(f"⚠️ Muddat qo‘yilmagan zayavka\n\n📌 {card_name}\n📂 Ustun: {list_name}")
                notified_alerts.add(key)

        if card.get("due") and list_name.upper() != DONE_LIST_NAME:
            try:
                due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                diff = due_dt - now

                if timedelta(hours=0) < diff <= timedelta(days=1):
                    key = f"{card_id}_soon"
                    if key not in notified_alerts:
                        send_message(f"⚠️ Zayavka muddati yaqin\n\n📌 {card_name}\n📂 Ustun: {list_name}")
                        notified_alerts.add(key)

                if diff <= timedelta(hours=0):
                    key = f"{card_id}_overdue"
                    if key not in notified_alerts:
                        send_message(f"⛔ Zayavka muddati o‘tgan\n\n📌 {card_name}\n📂 Ustun: {list_name}")
                        notified_alerts.add(key)
            except:
                pass

    old_cards = current_cards


def handle_commands():
    global last_update_id

    for update in get_updates():
        last_update_id = update["update_id"] + 1
        text = update.get("message", {}).get("text", "").strip().lower()

        if text in ["/hisobot", "hisobot"]:
            send_message(generate_report())
        elif text in ["/mahalliy", "mahalliy"]:
            send_message(generate_type_report("mahalliy"))
        elif text in ["/import", "import"]:
            send_message(generate_type_report("import"))
        elif text in ["/aralash", "aralash"]:
            send_message(generate_type_report("aralash"))


def bot_loop():
    initialize_existing_cards()

    while True:
        try:
            check_changes()
            handle_commands()
        except Exception as e:
            print("Xato:", e)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
