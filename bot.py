import os
import re
import time
import json
import threading
import requests
from flask import Flask
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))
TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID")

DONE_LIST_NAME = "YOPILGAN"
CHECK_INTERVAL = 30

app = Flask(__name__)

last_update_id = None
known_cards = {}
warned_5_days = set()
plugin_cache = {}


@app.route("/")
def home():
    return "Bot ishlayapti ✅"


def current_year():
    return str(datetime.now().year)


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    while len(text) > 3900:
        cut = text.rfind("\n", 0, 3900)
        if cut == -1:
            cut = 3900
        requests.post(url, data={"chat_id": CHAT_ID, "text": text[:cut]}, timeout=30)
        text = text[cut:].strip()
        time.sleep(1)

    if text:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=30)


def trello_get(path, extra=None):
    params = {"key": TRELLO_KEY, "token": TRELLO_TOKEN}

    if extra:
        params.update(extra)

    url = f"https://api.trello.com/1/{path}"
    r = requests.get(url, params=params, timeout=30)

    if r.status_code != 200:
        print("Trello xato:", r.status_code, r.text[:500])
        return []

    try:
        return r.json()
    except Exception:
        return []


def get_cards():
    return trello_get(f"boards/{BOARD_ID}/cards", {
        "customFieldItems": "true",
        "labels": "all",
        "members": "true",
        "pluginData": "true"
    })


def get_lists():
    return trello_get(f"boards/{BOARD_ID}/lists")


def get_members():
    return trello_get(f"boards/{BOARD_ID}/members")


def get_custom_fields():
    return trello_get(f"boards/{BOARD_ID}/customFields")


def get_card_plugin_data(card_id):
    now = time.time()

    if card_id in plugin_cache:
        saved_time, saved_data = plugin_cache[card_id]
        if now - saved_time < 300:
            return saved_data

    data = trello_get(f"cards/{card_id}/pluginData")
    plugin_cache[card_id] = (now, data)

    return data


def build_list_map():
    return {x["id"]: x["name"] for x in get_lists()}


def build_member_map():
    return {
        m["id"]: m.get("fullName") or m.get("username") or m["id"]
        for m in get_members()
    }


def build_custom_option_map():
    option_map = {}

    for field in get_custom_fields():
        for opt in field.get("options", []):
            opt_id = opt.get("id")
            opt_text = opt.get("value", {}).get("text", "")

            if opt_id and opt_text:
                option_map[opt_id] = opt_text

    return option_map


def collect_all_text(obj):
    result = []

    if obj is None:
        return result

    if isinstance(obj, str):
        result.append(obj)

        try:
            parsed = json.loads(obj)
            result.extend(collect_all_text(parsed))
        except Exception:
            pass

        return result

    if isinstance(obj, dict):
        for key, value in obj.items():
            result.append(str(key))
            result.extend(collect_all_text(value))
        return result

    if isinstance(obj, list):
        for item in obj:
            result.extend(collect_all_text(item))
        return result

    result.append(str(obj))
    return result


def detect_type_from_text(text):
    t = (text or "").lower()

    if "aralash" in t or "аралаш" in t or "смеш" in t:
        return "Aralash"

    if "import" in t or "импорт" in t:
        return "Import"

    if (
        "mahalliy" in t
        or "mahalli" in t
        or "махаллий" in t
        or "маҳаллий" in t
        or "local" in t
    ):
        return "Mahalliy"

    return None


def get_card_type(card, option_map):
    texts = []

    texts.append(card.get("name", ""))
    texts.append(card.get("desc", ""))

    for label in card.get("labels", []):
        texts.append(label.get("name", ""))

    for item in card.get("customFieldItems", []):
        option_id = item.get("idValue")

        if option_id in option_map:
            texts.append(option_map[option_id])

        value = item.get("value", {})
        texts.extend(collect_all_text(value))

    texts.extend(collect_all_text(card.get("pluginData", [])))

    plugin_data = get_card_plugin_data(card["id"])
    texts.extend(collect_all_text(plugin_data))

    joined = " ".join(texts)
    detected = detect_type_from_text(joined)

    return detected if detected else "Aniqlanmagan"


def is_done(list_name):
    return list_name.strip().upper() == DONE_LIST_NAME


def is_current_year_card(card):
    year = current_year()
    name = card.get("name", "")
    desc = card.get("desc", "")

    years_in_name = re.findall(r"20\d{2}", name)

    if years_in_name:
        return year in years_in_name

    years_in_desc = re.findall(r"20\d{2}", desc)

    if years_in_desc:
        return year in years_in_desc

    if card.get("due"):
        return card["due"][:4] == year

    return False


def due_date(card):
    if not card.get("due"):
        return None

    try:
        return datetime.strptime(card["due"][:10], "%Y-%m-%d").date()
    except Exception:
        return None


def due_text(card):
    d = due_date(card)
    return d.strftime("%d.%m.%Y") if d else "Muddat qo‘yilmagan"


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

    return desc[:limit] + "..." if len(desc) > limit else desc


def card_short_url(card):
    return card.get("shortUrl") or card.get("url") or ""


def member_names(card, member_map):
    names = [member_map.get(mid, mid) for mid in card.get("idMembers", [])]
    return ", ".join(names) if names else "Uchastnik biriktirilmagan"


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
    option_map = build_custom_option_map()

    new_known = {}

    for card in cards:
        card_id = card["id"]
        card_name = card.get("name", "Nomsiz karta")
        list_name = list_map.get(card.get("idList"), "Noma’lum ustun")
        old_list = known_cards.get(card_id)

        new_known[card_id] = list_name

        if not is_current_year_card(card):
            continue

        zayavka_type = get_card_type(card, option_map)

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


def calculate_stats(filter_type=None):
    all_cards = get_cards()
    list_map = build_list_map()
    member_map = build_member_map()
    option_map = build_custom_option_map()

    cards = [c for c in all_cards if is_current_year_card(c)]

    if filter_type:
        cards = [c for c in cards if get_card_type(c, option_map) == filter_type]

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
        card_type = get_card_type(card, option_map)

        if done_status:
            done += 1
        else:
            active += 1

        if overdue_status:
            overdue += 1

        if no_due_status:
            no_due += 1

        type_stats[card_type] = type_stats.get(card_type, 0) + 1

        if not done_status:
            column_stats[list_name] = column_stats.get(list_name, 0) + 1

        for member_id in card.get("idMembers", []):
            name = member_map.get(member_id, member_id)

            if name not in employee_stats:
                employee_stats[name] = {
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

            employee_stats[name]["total"] += 1

            if done_status:
                employee_stats[name]["done"] += 1
            else:
                employee_stats[name]["active"] += 1

            if overdue_status:
                employee_stats[name]["overdue"] += 1

            if no_due_status:
                employee_stats[name]["no_due"] += 1

            if card_type == "Mahalliy":
                employee_stats[name]["mahalliy"] += 1
            elif card_type == "Import":
                employee_stats[name]["import"] += 1
            elif card_type == "Aralash":
                employee_stats[name]["aralash"] += 1
            else:
                employee_stats[name]["aniqlanmagan"] += 1

    return {
        "total": total,
        "active": active,
        "done": done,
        "overdue": overdue,
        "no_due": no_due,
        "type_stats": type_stats,
        "column_stats": column_stats,
        "employee_stats": employee_stats
    }


def generate_report(filter_type=None):
    s = calculate_stats(filter_type)

    text = f"📊 Xarid bo‘limi hisobot — {current_year()} yil\n"

    if filter_type:
        text += f"📌 Filtr: {filter_type}\n"

    text += "\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📦 UMUMIY ZAYAVKALAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Jami: {s['total']} ta\n"
    text += f"Jarayonda: {s['active']} ta\n"
    text += f"Yopilgan: {s['done']} ta\n"
    text += f"Kechikkan: {s['overdue']} ta\n"
    text += f"Muddatsiz: {s['no_due']} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📌 ZAYAVKA TURI BO‘YICHA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Mahalliy: {s['type_stats'].get('Mahalliy', 0)} ta\n"
    text += f"Import: {s['type_stats'].get('Import', 0)} ta\n"
    text += f"Aralash: {s['type_stats'].get('Aralash', 0)} ta\n"
    text += f"Aniqlanmagan: {s['type_stats'].get('Aniqlanmagan', 0)} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📂 USTUNLAR BO‘YICHA JARAYONDA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    for name, count in sorted(s["column_stats"].items()):
        if not is_done(name):
            text += f"{name}: {count} ta\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n"
    text += "👨‍💼 XODIMLAR BO‘YICHA ISHTIROK\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    if s["employee_stats"]:
        for employee, data in sorted(s["employee_stats"].items()):
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


def debug_turi():
    cards = [c for c in get_cards() if is_current_year_card(c)]
    option_map = build_custom_option_map()

    text = "🧪 ZAYAVKA TURI DEBUG\n\n"

    for card in cards[:5]:
        detected = get_card_type(card, option_map)
        plugin_data = get_card_plugin_data(card["id"])
        sample = " ".join(collect_all_text(plugin_data))[:1000]

        text += f"📌 {card.get('name', '')[:100]}\n"
        text += f"Topilgan turi: {detected}\n"
        text += f"PluginData sample:\n{sample}\n\n"

    return text


def get_latest_update_id():
    try:
        result = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            timeout=20
        ).json()

        updates = result.get("result", [])
        return updates[-1]["update_id"] if updates else None
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
        last_update_id = update["update_id"]

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip().lower()

        if chat_id != CHAT_ID:
            continue

        if text in ["/hisobot", "hisobot"]:
            send_message(generate_report())

        elif text in ["/mahalliy", "mahalliy"]:
            send_message(generate_report("Mahalliy"))

        elif text in ["/import", "import"]:
            send_message(generate_report("Import"))

        elif text in ["/aralash", "aralash"]:
            send_message(generate_report("Aralash"))

        elif text in ["/debug_turi", "debug_turi"]:
            send_message(debug_turi())


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
