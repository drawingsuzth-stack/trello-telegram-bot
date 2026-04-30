import requests
import time
from datetime import datetime, timedelta

# ===== SOZLAMALAR =====
BOT_TOKEN = "8717622332:AAFVshiMWLkQL_LB24VuWLhW51qXhHn-qj4"
CHAT_ID = "-1003908412363"

TRELLO_KEY = "6ca88f5a985a209852bcf9eae6f6c6c5"
TRELLO_TOKEN = "ATTAb8ec71a6c12dbc366f8ba6e4f21ef0ce0b48c890d80fd272c8ca1de7d065247143CCD020"
BOARD_ID = "62062d5559dff006768982bd"

DONE_LIST_NAME = "YOPILGAN"
CHECK_INTERVAL = 10

old_cards = {}
notified_alerts = set()
last_update_id = None


# ===== TELEGRAM =====
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})


def get_updates():
    global last_update_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    params = {}
    if last_update_id:
        params["offset"] = last_update_id

    data = requests.get(url, params=params).json()
    return data.get("result", [])


# ===== TRELLO =====
def trello_params():
    return {"key": TRELLO_KEY, "token": TRELLO_TOKEN}


def get_cards():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/cards"
    params = trello_params()
    params.update({
        "customFieldItems": "true",
        "labels": "all"
    })
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
    return {item["id"]: item["name"] for item in get_lists()}


def build_member_map():
    return {
        item["id"]: item.get("fullName") or item.get("username") or item["id"]
        for item in get_members()
    }


def build_custom_field_options_map():
    fields = get_custom_fields()
    options_map = {}

    for field in fields:
        field_name = field.get("name", "").lower()

        if "zayavka turi" in field_name:
            for option in field.get("options", []):
                option_id = option.get("id")
                option_text = option.get("value", {}).get("text", "")
                options_map[option_id] = option_text.lower()

    return options_map


# ===== JORIY YIL =====
def card_created_year(card_id):
    try:
        timestamp = int(card_id[:8], 16)
        return datetime.fromtimestamp(timestamp).year
    except:
        return None


def is_current_year_card(card):
    return card_created_year(card["id"]) == datetime.now().year


# ===== ZAYAVKA TURINI ANIQLASH =====
def get_card_type(card, options_map):
    # 1) Label orqali tekshiradi
    for label in card.get("labels", []):
        name = label.get("name", "").lower()

        if "aralash" in name:
            return "aralash"
        if "import" in name:
            return "import"
        if "mahalliy" in name:
            return "mahalliy"

    # 2) Custom Field dropdown orqali tekshiradi
    for item in card.get("customFieldItems", []):
        id_value = item.get("idValue")

        if id_value in options_map:
            value = options_map[id_value]

            if "aralash" in value:
                return "aralash"
            if "import" in value:
                return "import"
            if "mahalliy" in value:
                return "mahalliy"

        text_value = item.get("value", {}).get("text", "").lower()

        if "aralash" in text_value:
            return "aralash"
        if "import" in text_value:
            return "import"
        if "mahalliy" in text_value:
            return "mahalliy"

    return None


# ===== ESKI KARTALARNI BLOKLASH =====
def initialize_existing_cards():
    global old_cards, notified_alerts

    cards = get_cards()
    list_map = build_list_map()

    for card in cards:
        card_id = card["id"]
        list_name = list_map.get(card["idList"], "")

        old_cards[card_id] = list_name

        notified_alerts.add(f"{card_id}_soon")
        notified_alerts.add(f"{card_id}_overdue")
        notified_alerts.add(f"{card_id}_nodue")

    print("✅ Eski kartalar va eski alertlar bloklandi.")


# ===== UMUMIY HISOBOT =====
def generate_report():
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = build_list_map()
    member_map = build_member_map()

    year = datetime.now().year
    total_cards = len(cards)
    done_cards = 0
    active_cards = 0
    overdue_cards = 0
    no_due_cards = 0
    per_member = {}

    now = datetime.utcnow()

    for card in cards:
        list_name = list_map.get(card["idList"], "")
        is_done = list_name == DONE_LIST_NAME

        if is_done:
            done_cards += 1
        else:
            active_cards += 1

        if not card.get("due") and not is_done:
            no_due_cards += 1

        if card.get("due") and not is_done:
            try:
                due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                if due_dt < now:
                    overdue_cards += 1
            except:
                pass

        # Xodimlar bo‘yicha: har bir xodim nechta zayavkada ishtirok etgan
        for member_id in card.get("idMembers", []):
            name = member_map.get(member_id, member_id)

            if name not in per_member:
                per_member[name] = {
                    "total": 0,
                    "active": 0,
                    "done": 0,
                    "overdue": 0,
                    "no_due": 0
                }

            per_member[name]["total"] += 1

            if is_done:
                per_member[name]["done"] += 1
            else:
                per_member[name]["active"] += 1

            if not card.get("due") and not is_done:
                per_member[name]["no_due"] += 1

            if card.get("due") and not is_done:
                try:
                    due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                    if due_dt < now:
                        per_member[name]["overdue"] += 1
                except:
                    pass

    text = f"📊 Xarid bo‘limi hisobot — {year} yil\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "📦 UMUMIY ZAYAVKALAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Jami zayavka: {total_cards} ta\n"
    text += f"Jarayonda:    {active_cards} ta\n"
    text += f"Yopilgan:     {done_cards} ta\n"
    text += f"Kechikkan:    {overdue_cards} ta\n"
    text += f"Muddatsiz:    {no_due_cards} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "👤 ISHTIROKCHILAR BO‘YICHA\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    if per_member:
        for name, value in per_member.items():
            text += f"🔹 {name}\n"
            text += f"   • Ishtirok etgan zayavka: {value['total']} ta\n"
            text += f"   • Jarayonda: {value['active']} ta\n"
            text += f"   • Yopilgan: {value['done']} ta\n"
            text += f"   • Kechikkan: {value['overdue']} ta\n"
            text += f"   • Muddatsiz: {value['no_due']} ta\n\n"
    else:
        text += "Ishtirokchi biriktirilgan kartalar topilmadi.\n"

    return text


# ===== MAHALLIY / IMPORT / ARALASH HISOBOT =====
def generate_type_report(type_name):
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = build_list_map()
    options_map = build_custom_field_options_map()

    total_cards = 0
    done_cards = 0
    active_cards = 0
    overdue_cards = 0
    no_due_cards = 0
    now = datetime.utcnow()

    for card in cards:
        card_type = get_card_type(card, options_map)

        if card_type != type_name:
            continue

        list_name = list_map.get(card["idList"], "")
        is_done = list_name == DONE_LIST_NAME

        total_cards += 1

        if is_done:
            done_cards += 1
        else:
            active_cards += 1

        if not card.get("due") and not is_done:
            no_due_cards += 1

        if card.get("due") and not is_done:
            try:
                due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                if due_dt < now:
                    overdue_cards += 1
            except:
                pass

    title_map = {
        "mahalliy": "MAHALLIY",
        "import": "IMPORT",
        "aralash": "ARALASH"
    }

    title = title_map.get(type_name, type_name.upper())
    year = datetime.now().year

    return f"""📦 {title} zayavkalar — {year} yil

━━━━━━━━━━━━━━━━━━
Jami zayavka: {total_cards} ta
Jarayonda:    {active_cards} ta
Yopilgan:     {done_cards} ta
Kechikkan:    {overdue_cards} ta
Muddatsiz:    {no_due_cards} ta
━━━━━━━━━━━━━━━━━━"""


# ===== TRELLO O‘ZGARISHLARINI TEKSHIRISH =====
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
        old_list_name = old_cards.get(card_id)

        current_cards[card_id] = list_name

        if not is_current_year_card(card):
            continue

        if card_id not in old_cards:
            if list_name != DONE_LIST_NAME:
                send_message(
                    f"🆕 Yangi zayavka qo‘shildi\n\n"
                    f"📌 {card_name}\n"
                    f"📂 Ustun: {list_name}"
                )

        elif old_list_name != DONE_LIST_NAME and list_name == DONE_LIST_NAME:
            send_message(
                f"✅ Zayavka yopildi\n\n"
                f"📌 {card_name}\n"
                f"📂 Qaysi ustundan yopildi: {old_list_name}\n"
                f"📂 Hozirgi ustun: {list_name}"
            )

        if not card.get("due") and list_name != DONE_LIST_NAME:
            key = f"{card_id}_nodue"
            if key not in notified_alerts:
                send_message(
                    f"⚠️ Muddat qo‘yilmagan zayavka\n\n"
                    f"📌 {card_name}\n"
                    f"📂 Ustun: {list_name}"
                )
                notified_alerts.add(key)

        if card.get("due") and list_name != DONE_LIST_NAME:
            try:
                due_dt = datetime.fromisoformat(card["due"].replace("Z", ""))
                diff = due_dt - now

                if timedelta(hours=0) < diff <= timedelta(days=1):
                    key = f"{card_id}_soon"
                    if key not in notified_alerts:
                        send_message(
                            f"⚠️ Zayavka muddati yaqin\n\n"
                            f"📌 {card_name}\n"
                            f"📂 Ustun: {list_name}"
                        )
                        notified_alerts.add(key)

                if diff <= timedelta(hours=0):
                    key = f"{card_id}_overdue"
                    if key not in notified_alerts:
                        send_message(
                            f"⛔ Zayavka muddati o‘tgan\n\n"
                            f"📌 {card_name}\n"
                            f"📂 Ustun: {list_name}"
                        )
                        notified_alerts.add(key)

            except:
                pass

    old_cards = current_cards


# ===== TELEGRAM KOMANDALAR =====
def handle_commands():
    global last_update_id

    for update in get_updates():
        last_update_id = update["update_id"] + 1

        message = update.get("message", {})
        text = message.get("text", "").strip().lower()

        if text.startswith("/hisobot") or text == "hisobot":
            send_message(generate_report())

        elif text.startswith("/mahalliy") or text == "mahalliy":
            send_message(generate_type_report("mahalliy"))

        elif text.startswith("/import") or text == "import":
            send_message(generate_type_report("import"))

        elif text.startswith("/aralash") or text == "aralash":
            send_message(generate_type_report("aralash"))


print("✅ Bot ishlayapti...")

initialize_existing_cards()

while True:
    try:
        check_changes()
        handle_commands()
    except Exception as e:
        print("Xato:", e)

    time.sleep(CHECK_INTERVAL)
