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
CURRENT_YEAR = str(datetime.now().year)
CHECK_INTERVAL = 30

app = Flask(__name__)

last_update_id = None
known_cards = {}
warned_5_days = set()


@app.route("/")
def home():
    return "Bot ishlayapti ✅"


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    if len(text) <= 3900:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=30)
        return

    parts = []
    while len(text) > 3900:
        split_at = text.rfind("\n", 0, 3900)
        if split_at == -1:
            split_at = 3900
        parts.append(text[:split_at])
        text = text[split_at:].strip()

    if text:
        parts.append(text)

    for part in parts:
        requests.post(url, data={"chat_id": CHAT_ID, "text": part}, timeout=30)
        time.sleep(1)


def trello_get(path, extra=None):
    params = {"key": TRELLO_KEY, "token": TRELLO_TOKEN}
    if extra:
        params.update(extra)

    url = f"https://api.trello.com/1/{path}"
    r = requests.get(url, params=params, timeout=30)

    if r.status_code != 200:
        print("Trello xato:", r.status_code, r.text[:300])
        return []

    return r.json()


def get_cards():
    return trello_get(f"boards/{BOARD_ID}/cards", {
        "customFieldItems": "true",
        "labels": "all"
    })


def get_lists():
    return trello_get(f"boards/{BOARD_ID}/lists")


def get_members():
    return trello_get(f"boards/{BOARD_ID}/members")


def get_custom_fields():
    return trello_get(f"boards/{BOARD_ID}/customFields")


def build_list_map():
    return {x["id"]: x["name"] for x in get_lists()}


def build_member_map():
    result = {}
    for member in get_members():
        result[member["id"]] = member.get("fullName") or member.get("username") or member["id"]
    return result


def build_zayavka_type_map():
    result = {}

    for field in get_custom_fields():
        field_name = field.get("name", "").strip().lower()

        if "zayavka turi" in field_name or "заявка turi" in field_name:
            for option in field.get("options", []):
                option_id = option.get("id")
                option_text = option.get("value", {}).get("text", "")
                result[option_id] = option_text

    return result


def is_done(list_name):
    return list_name.strip().upper() == DONE_LIST_NAME


def is_current_year_card(card):
    name = card.get("name", "")
    desc = card.get("desc", "")

    if CURRENT_YEAR in name:
        return True

    if CURRENT_YEAR in desc:
        return True

    if card.get("due"):
        return card["due"][:4] == CURRENT_YEAR

    return False


def get_card_type(card, type_map):
    text = card.get("name", "").lower()
    text += " " + card.get("desc", "").lower()

    for label in card.get("labels", []):
        text += " " + label.get("name", "").lower()

    for item in card.get("customFieldItems", []):
        option_id = item.get("idValue")
        if option_id in type_map:
            return type_map[option_id]

        value_text = item.get("value", {}).get("text", "")
        if value_text:
            text += " " + value_text.lower()

    if "mahalliy" in text:
        return "Mahalliy"
    if "import" in text:
        return "Import"
    if "aralash" in text:
        return "Aralash"

    return "Aniqlanmagan"


def due_date(card):
    if not card.get("due"):
        return None

    try:
        return datetime.strptime(card["due"][:10], "%Y-%m-%d").date()
    except Exception:
        return None


def due_text(card):
    d = due_date(card)
    if not d:
        return "Muddat qo‘yilmagan"
    return d.strftime("%d.%m.%Y")


def is_overdue(card, list_name):
    d = due_date(card)
    if not d:
        return False
    if is_done(list_name):
        return False
    return d < datetime.utcnow().date()


def is_due_within_5_days(card, list_name):
    d = due_date(card)
    if not d:
        return False
    if is_done(list_name):
        return False

    days_left = (d - datetime.utcnow().date()).days
    return 0 <= days_left <= 5


def card_description(card, limit=900):
    desc = card.get("desc", "").strip()
    if not desc:
        return "Opisaniya yozilmagan"

    if len(desc) > limit:
        return desc[:limit] + "..."

    return desc


def card_short_url(card):
    return card.get("shortUrl") or card.get("url") or ""


def member_names(card, member_map):
    names = []

    for member_id in card.get("idMembers", []):
        names.append(member_map.get(member_id, member_id))

    if not names:
        return "Uchastnik biriktirilmagan"

    return ", ".join(names)


def initialize_known_cards():
    global known_cards

    cards = get_cards()
    list_map = build_list_map()

    for card in cards:
        known_cards[card["id"]] = list_map.get(card["idList"], "")

    print(f"✅ Boshlang‘ich kartalar yuklandi: {len(known_cards)} ta")


def check_trello_changes():
    global known_cards

    cards = get_cards()
    list_map = build_list_map()
    member_map = build_member_map()
    type_map = build_zayavka_type_map()

    new_known = {}

    for card in cards:
        if not is_current_year_card(card):
            continue

        card_id = card["id"]
        card_name = card.get("name", "Nomsiz karta")
        list_name = list_map.get(card.get("idList"), "Noma’lum ustun")
        old_list = known_cards.get(card_id)
        zayavka_type = get_card_type(card, type_map)

        new_known[card_id] = list_name

        if card_id not in known_cards:
            send_message(
                f"🆕 Yangi zayavka qo‘shildi\n\n"
                f"📌 Zayavka: {card_name}\n"
                f"📂 Ustun: {list_name}\n"
                f"📌 Turi: {zayavka_type}\n"
                f"👥 Uchastniklar: {member_names(card, member_map)}\n"
                f"📅 Deadline: {due_text(card)}\n\n"
                f"📝 Opisaniya:\n{card_description(card)}\n\n"
                f"🔗 {card_short_url(card)}"
            )

        elif old_list and not is_done(old_list) and is_done(list_name):
            send_message(
                f"✅ Zayavka yopildi\n\n"
                f"📌 Zayavka: {card_name}\n"
                f"📂 Oldingi ustun: {old_list}\n"
                f"📂 Hozirgi ustun: {list_name}\n"
                f"📌 Turi: {zayavka_type}\n"
                f"👥 Uchastniklar: {member_names(card, member_map)}\n"
                f"📅 Deadline: {due_text(card)}\n\n"
                f"📝 Opisaniya:\n{card_description(card)}\n\n"
                f"🔗 {card_short_url(card)}"
            )

        if is_due_within_5_days(card, list_name):
            warning_key = f"{card_id}_5days"

            if warning_key not in warned_5_days:
                d = due_date(card)
                days_left = (d - datetime.utcnow().date()).days

                send_message(
                    f"⚠️ Muddat yaqinlashmoqda\n\n"
                    f"📌 Zayavka: {card_name}\n"
                    f"📂 Ustun: {list_name}\n"
                    f"📌 Turi: {zayavka_type}\n"
                    f"👥 Uchastniklar: {member_names(card, member_map)}\n"
                    f"📅 Deadline: {d.strftime('%d.%m.%Y')}\n"
                    f"⏳ Qolgan vaqt: {days_left} kun\n\n"
                    f"📝 Opisaniya:\n{card_description(card)}\n\n"
                    f"🔗 {card_short_url(card)}"
                )

                warned_5_days.add(warning_key)

    known_cards.update(new_known)


def generate_report():
    all_cards = get_cards()
    list_map = build_list_map()
    member_map = build_member_map()
    type_map = build_zayavka_type_map()

    cards = [c for c in all_cards if is_current_year_card(c)]

    total = len(cards)
    active = 0
    done = 0
    overdue = 0
    no_due = 0

    type_stats = {
        "Mahalliy": 0,
        "Import": 0,
        "Aralash": 0,
        "Aniqlanmagan": 0
    }

    column_stats = {}
    employee_stats = {}

    for card in cards:
        list_name = list_map.get(card.get("idList"), "Noma’lum ustun")
        done_status = is_done(list_name)
        overdue_status = is_overdue(card, list_name)
        no_due_status = not card.get("due") and not done_status

        if done_status:
            done += 1
        else:
            active += 1

        if overdue_status:
            overdue += 1

        if no_due_status:
            no_due += 1

        card_type = get_card_type(card, type_map)
        if card_type not in type_stats:
            type_stats[card_type] = 0
        type_stats[card_type] += 1

        if not done_status:
            column_stats[list_name] = column_stats.get(list_name, 0) + 1

        for member_id in card.get("idMembers", []):
            member_name = member_map.get(member_id, member_id)

            if member_name not in employee_stats:
                employee_stats[member_name] = {
                    "total": 0,
                    "active": 0,
                    "done": 0,
                    "overdue": 0,
                    "no_due": 0,
                    "mahalliy": 0,
                    "import": 0,
                    "aralash": 0,
                    "aniqlanmagan": 0
                }

            employee_stats[member_name]["total"] += 1

            if done_status:
                employee_stats[member_name]["done"] += 1
            else:
                employee_stats[member_name]["active"] += 1

            if overdue_status:
                employee_stats[member_name]["overdue"] += 1

            if no_due_status:
                employee_stats[member_name]["no_due"] += 1

            t = card_type.lower()
            if "mahalliy" in t:
                employee_stats[member_name]["mahalliy"] += 1
            elif "import" in t:
                employee_stats[member_name]["import"] += 1
            elif "aralash" in t:
                employee_stats[member_name]["aralash"] += 1
            else:
                employee_stats[member_name]["aniqlanmagan"] += 1

    text = f"📊 Xarid bo‘limi hisobot — {CURRENT_YEAR} yil\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📦 UMUMIY ZAYAVKALAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Jami: {total} ta\n"
    text += f"Jarayonda: {active} ta\n"
    text += f"Yopilgan: {done} ta\n"
    text += f"Kechikkan: {overdue} ta\n"
    text += f"Muddatsiz: {no_due} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📌 ZAYAVKA TURI BO‘YICHA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Mahalliy: {type_stats.get('Mahalliy', 0)} ta\n"
    text += f"Import: {type_stats.get('Import', 0)} ta\n"
    text += f"Aralash: {type_stats.get('Aralash', 0)} ta\n"
    text += f"Aniqlanmagan: {type_stats.get('Aniqlanmagan', 0)} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📂 USTUNLAR BO‘YICHA JARAYONDA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    for name, count in sorted(column_stats.items()):
        if not is_done(name):
            text += f"{name}: {count} ta\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n"
    text += "👨‍💼 XODIMLAR BO‘YICHA ISHTIROK\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    if employee_stats:
        for employee, data in sorted(employee_stats.items()):
            text += f"\n🔹 {employee}\n"
            text += f"   Ishtirok jami: {data['total']} ta\n"
            text += f"   Jarayonda: {data['active']} ta\n"
            text += f"   Yopilgan: {data['done']} ta\n"
            text += f"   Kechikkan: {data['overdue']} ta\n"
            text += f"   Muddatsiz: {data['no_due']} ta\n"
            text += f"   Mahalliy: {data['mahalliy']} ta\n"
            text += f"   Import: {data['import']} ta\n"
            text += f"   Aralash: {data['aralash']} ta\n"
            text += f"   Aniqlanmagan: {data['aniqlanmagan']} ta\n"
    else:
        text += "\nUchastnik biriktirilgan zayavkalar topilmadi.\n"

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


def handle_telegram_commands():
    global last_update_id

    params = {"timeout": 20}

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

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip().lower()

        if chat_id != CHAT_ID:
            continue

        if text in ["/hisobot", "hisobot"]:
            send_message(generate_report())


def bot_loop():
    global last_update_id

    last_update_id = get_latest_update_id()
    initialize_known_cards()

    while True:
        try:
            handle_telegram_commands()
            check_trello_changes()
        except Exception as e:
            print("Xato:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
