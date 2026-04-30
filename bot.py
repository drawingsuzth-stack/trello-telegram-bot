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
CHECK_INTERVAL = 30

app = Flask(__name__)

last_update_id = None
known_cards = {}
warned_5_days = set()


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
        print("Trello xato:", r.status_code, r.text[:300])
        return []

    return r.json()


def get_cards():
    return trello_get(f"boards/{BOARD_ID}/cards", {
        "members": "true",
        "labels": "all"
    })


def get_lists():
    return trello_get(f"boards/{BOARD_ID}/lists")


def get_members():
    return trello_get(f"boards/{BOARD_ID}/members")


def build_list_map():
    return {x["id"]: x["name"] for x in get_lists()}


def build_member_map():
    result = {}
    for m in get_members():
        result[m["id"]] = m.get("fullName") or m.get("username") or m["id"]
    return result


def is_done(list_name):
    return list_name.strip().upper() == DONE_LIST_NAME


def is_current_year_card(card):
    year = current_year()
    text = f"{card.get('name', '')} {card.get('desc', '')} {card.get('due', '')}"
    return year in text


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
    if not d or is_done(list_name):
        return False
    return d < datetime.utcnow().date()


def days_left(card):
    d = due_date(card)
    if not d:
        return None
    return (d - datetime.utcnow().date()).days


def is_due_within_5_days(card, list_name):
    left = days_left(card)
    if left is None or is_done(list_name):
        return False
    return 0 <= left <= 5


def card_description(card, limit=900):
    desc = card.get("desc", "").strip()
    if not desc:
        return "Opisaniya yozilmagan."
    return desc[:limit] + "..." if len(desc) > limit else desc


def card_url(card):
    return card.get("shortUrl") or card.get("url") or ""


def member_names(card, member_map):
    names = [member_map.get(mid, mid) for mid in card.get("idMembers", [])]
    return ", ".join(names) if names else "Uchastnik biriktirilmagan"


def card_message(title, card, list_name, member_map, extra=""):
    return (
        f"{title}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Zayavka: {card.get('name', 'Nomsiz karta')}\n"
        f"Ustun: {list_name}\n"
        f"Uchastniklar: {member_names(card, member_map)}\n"
        f"Deadline: {due_text(card)}\n"
        f"{extra}"
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"Opisaniya:\n{card_description(card)}\n\n"
        f"Link: {card_url(card)}"
    )


def initialize_known_cards():
    global known_cards

    cards = get_cards()
    list_map = build_list_map()

    for card in cards:
        known_cards[card["id"]] = list_map.get(card["idList"], "")

    print(f"Boshlang‘ich kartalar yuklandi: {len(known_cards)} ta")


def check_trello_changes():
    global known_cards

    cards = get_cards()
    list_map = build_list_map()
    member_map = build_member_map()

    new_known = {}

    for card in cards:
        if not is_current_year_card(card):
            continue

        card_id = card["id"]
        list_name = list_map.get(card.get("idList"), "Noma’lum ustun")
        old_list = known_cards.get(card_id)

        new_known[card_id] = list_name

        if card_id not in known_cards:
            send_message(
                card_message(
                    "Yangi zayavka qo‘shildi",
                    card,
                    list_name,
                    member_map
                )
            )

        elif old_list and not is_done(old_list) and is_done(list_name):
            send_message(
                card_message(
                    "Zayavka yopildi",
                    card,
                    list_name,
                    member_map,
                    extra=f"Oldingi ustun: {old_list}\n"
                )
            )

        if is_due_within_5_days(card, list_name):
            key = f"{card_id}_5days"
            if key not in warned_5_days:
                left = days_left(card)
                send_message(
                    card_message(
                        "Muddat yaqinlashmoqda",
                        card,
                        list_name,
                        member_map,
                        extra=f"Qolgan vaqt: {left} kun\n"
                    )
                )
                warned_5_days.add(key)

    known_cards.update(new_known)


def generate_report():
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = build_list_map()
    member_map = build_member_map()

    total = len(cards)
    active = 0
    done = 0
    overdue = 0
    no_due = 0

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
            column_stats[list_name] = column_stats.get(list_name, 0) + 1

        if overdue_status:
            overdue += 1

        if no_due_status:
            no_due += 1

        for member_id in card.get("idMembers", []):
            employee = member_map.get(member_id, member_id)

            if employee not in employee_stats:
                employee_stats[employee] = {
                    "total": 0,
                    "active": 0,
                    "done": 0,
                    "overdue": 0,
                    "no_due": 0
                }

            employee_stats[employee]["total"] += 1

            if done_status:
                employee_stats[employee]["done"] += 1
            else:
                employee_stats[employee]["active"] += 1

            if overdue_status:
                employee_stats[employee]["overdue"] += 1

            if no_due_status:
                employee_stats[employee]["no_due"] += 1

    text = f"Xarid bo‘limi hisobot — {current_year()} yil\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "UMUMIY ZAYAVKALAR\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"Jami zayavka: {total} ta\n"
    text += f"Jarayonda: {active} ta\n"
    text += f"Yopilgan: {done} ta\n"
    text += f"Kechikkan: {overdue} ta\n"
    text += f"Muddatsiz: {no_due} ta\n\n"

    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "USTUNLAR BO‘YICHA JARAYONDA\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    if column_stats:
        for name, count in sorted(column_stats.items()):
            text += f"{name}: {count} ta\n"
    else:
        text += "Jarayondagi zayavkalar yo‘q.\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n"
    text += "XODIMLAR BO‘YICHA ISHTIROK\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    if employee_stats:
        for employee, data in sorted(employee_stats.items()):
            text += f"\n{employee}\n"
            text += f"  Ishtirok jami: {data['total']} ta\n"
            text += f"  Jarayonda: {data['active']} ta\n"
            text += f"  Yopilgan: {data['done']} ta\n"
            text += f"  Kechikkan: {data['overdue']} ta\n"
            text += f"  Muddatsiz: {data['no_due']} ta\n"
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
