import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID", "62062d5559dff006768982bd")

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
    requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)


def get_updates():
    global last_update_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {}
    if last_update_id:
        params["offset"] = last_update_id
    return requests.get(url, params=params, timeout=20).json().get("result", [])


def trello_get(endpoint, extra=None):
    params = {"key": TRELLO_KEY, "token": TRELLO_TOKEN}
    if extra:
        params.update(extra)

    r = requests.get(endpoint, params=params, timeout=30)

    if r.status_code != 200:
        print("Trello API xato:", r.status_code, r.text[:300])
        return []

    try:
        return r.json()
    except Exception as e:
        print("JSON xato:", e, r.text[:300])
        return []


def get_cards():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/cards"
    return trello_get(url, {"customFieldItems": "true", "labels": "all"})


def get_lists():
    return trello_get(f"https://api.trello.com/1/boards/{BOARD_ID}/lists")


def get_members():
    return trello_get(f"https://api.trello.com/1/boards/{BOARD_ID}/members")


def get_custom_fields():
    return trello_get(f"https://api.trello.com/1/boards/{BOARD_ID}/customFields")


def build_list_map():
    return {x["id"]: x["name"] for x in get_lists()}


def build_member_map():
    return {
        x["id"]: x.get("fullName") or x.get("username") or x["id"]
        for x in get_members()
    }


def build_custom_field_options_map():
    options_map = {}

    for field in get_custom_fields():
        field_name = field.get("name", "").lower()

        if "zayavka turi" in field_name:
            for opt in field.get("options", []):
                opt_id = opt.get("id")
                opt_text = opt.get("value", {}).get("text", "").lower()
                options_map[opt_id] = opt_text

    return options_map


def is_current_year_card(card):
    year = str(datetime.now().year)

    if card.get("due"):
        try:
            due_year = str(datetime.fromisoformat(card["due"].replace("Z", "")).year)
            if due_year == year:
                return True
        except Exception:
            pass

    return year in card.get("name", "")


def get_card_type(card, options_map):
    text_all = card.get("name", "").lower()

    for label in card.get("labels", []):
        text_all += " " + label.get("name", "").lower()

    for item in card.get("customFieldItems", []):
        text_all += " " + options_map.get(item.get("idValue"), "")
        text_all += " " + item.get("value", {}).get("text", "").lower()

    if "aralash" in text_all:
        return "aralash"
    if "import" in text_all or "импорт" in text_all:
        return "import"
    if "mahalliy" in text_all or "махаллий" in text_all or "mahalli" in text_all:
        return "mahalliy"

    return None


def is_done_card(card, list_map):
    list_name = list_map.get(card["idList"], "")
    return list_name.strip().upper() == DONE_LIST_NAME


def initialize_existing_cards():
    global old_cards, notified_alerts

    cards = get_cards()
    list_map = build_list_map()

    for card in cards:
        card_id = card["id"]
        old_cards[card_id] = list_map.get(card["idList"], "")

        notified_alerts.add(f"{card_id}_nodue")
        notified_alerts.add(f"{card_id}_soon")
        notified_alerts.add(f"{card_id}_overdue")

    print("✅ Eski kartalar bloklandi.")


def generate_report():
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = build_list_map()
    member_map = build_member_map()
    now = datetime.utcnow()

    total = len(cards)
    done = 0
    active = 0
    overdue = 0
    no_due = 0
    per_member = {}

    for card in cards:
        is_done = is_done_card(card, list_map)

        if is_done:
            done += 1
        else:
            active += 1

        if not card.get("due") and not is_done:
            no_due += 1

        if card.get("due") and not is_done:
            try:
                due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                if due_dt < now:
                    overdue += 1
            except Exception:
                pass

        for member_id in card.get("idMembers", []):
            name = member_map.get(member_id, member_id)

            if name not in per_member:
                per_member[name] = {"total": 0, "active": 0, "done": 0}

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

    if per_member:
        for name, v in per_member.items():
            text += f"🔹 {name}\n"
            text += f"   • Ishtirok: {v['total']} ta\n"
            text += f"   • Jarayonda: {v['active']} ta\n"
            text += f"   • Yopilgan: {v['done']} ta\n\n"
    else:
        text += "Ishtirokchi biriktirilgan kartalar topilmadi.\n"

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

        is_done = is_done_card(card, list_map)

        total += 1

        if is_done:
            done += 1
        else:
            active += 1

        if not card.get("due") and not is_done:
            no_due += 1

        if card.get("due") and not is_done:
            try:
                due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                if due_dt < now:
                    overdue += 1
            except Exception:
                pass

    title = {
        "mahalliy": "MAHALLIY",
        "import": "IMPORT",
        "aralash": "ARALASH"
    }[type_name]

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

        if card_id not in old_cards and list_name.strip().upper() != DONE_LIST_NAME:
            send_message(f"🆕 Yangi zayavka\n\n📌 {card_name}\n📂 Ustun: {list_name}")

        elif old_list and old_list.strip().upper() != DONE_LIST_NAME and list_name.strip().upper() == DONE_LIST_NAME:
            send_message(
                f"✅ Zayavka yopildi\n\n"
                f"📌 {card_name}\n"
                f"📂 Qaysi ustundan yopildi: {old_list}\n"
                f"📂 Hozirgi ustun: {list_name}"
            )

        if not card.get("due") and list_name.strip().upper() != DONE_LIST_NAME:
            key = f"{card_id}_nodue"
            if key not in notified_alerts:
                send_message(f"⚠️ Muddat qo‘yilmagan zayavka\n\n📌 {card_name}\n📂 Ustun: {list_name}")
                notified_alerts.add(key)

        if card.get("due") and list_name.strip().upper() != DONE_LIST_NAME:
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

            except Exception:
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
    print("✅ Bot ishga tushdi.")
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
