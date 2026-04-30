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
warned_cards = set()


@app.route("/")
def home():
    return "Bot ishlayapti ✅"


# ---------------- TELEGRAM ----------------
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})


# ---------------- TRELLO ----------------
def trello_get(path, extra=None):
    params = {"key": TRELLO_KEY, "token": TRELLO_TOKEN}
    if extra:
        params.update(extra)

    url = f"https://api.trello.com/1/{path}"
    r = requests.get(url, params=params)

    if r.status_code != 200:
        print("Trello xato:", r.text)
        return []

    return r.json()


def get_cards():
    return trello_get(f"boards/{BOARD_ID}/cards", {
        "members": "true"
    })


def get_lists():
    return trello_get(f"boards/{BOARD_ID}/lists")


def get_members():
    return trello_get(f"boards/{BOARD_ID}/members")


# ---------------- HELPERS ----------------
def current_year():
    return str(datetime.now().year)


def is_current_year_card(card):
    text = str(card)
    return current_year() in text


def due_date(card):
    if not card.get("due"):
        return None
    return datetime.strptime(card["due"][:10], "%Y-%m-%d").date()


def is_done(list_name):
    return list_name.upper() == DONE_LIST_NAME


def is_overdue(card, list_name):
    d = due_date(card)
    if not d or is_done(list_name):
        return False
    return d < datetime.utcnow().date()


def is_due_soon(card, list_name):
    d = due_date(card)
    if not d or is_done(list_name):
        return False

    days = (d - datetime.utcnow().date()).days
    return 0 <= days <= 5


def card_desc(card):
    desc = card.get("desc", "")
    return desc[:500] if desc else "Opisaniya yo‘q"


def member_names(card, member_map):
    names = [member_map.get(i, i) for i in card.get("idMembers", [])]
    return ", ".join(names) if names else "Yo‘q"


# ---------------- INIT ----------------
def initialize_cards():
    global known_cards

    cards = get_cards()
    list_map = {l["id"]: l["name"] for l in get_lists()}

    for c in cards:
        known_cards[c["id"]] = list_map.get(c["idList"], "")

    print("Boshlang‘ich kartalar yuklandi")


# ---------------- MONITOR ----------------
def check_changes():
    global known_cards

    cards = get_cards()
    list_map = {l["id"]: l["name"] for l in get_lists()}
    member_map = {m["id"]: m["fullName"] for m in get_members()}

    new_known = {}

    for c in cards:
        if not is_current_year_card(c):
            continue

        cid = c["id"]
        name = c["name"]
        list_name = list_map.get(c["idList"], "")
        old_list = known_cards.get(cid)

        new_known[cid] = list_name

        # YANGI
        if cid not in known_cards:
            send_message(
                f"🆕 Yangi zayavka\n\n"
                f"{name}\n"
                f"📂 {list_name}\n"
                f"👥 {member_names(c, member_map)}\n"
                f"📅 {c.get('due','-')}\n\n"
                f"{card_desc(c)}"
            )

        # YOPILDI
        elif old_list and not is_done(old_list) and is_done(list_name):
            send_message(
                f"✅ Yopildi\n\n"
                f"{name}\n"
                f"📂 {old_list} → {list_name}\n"
                f"👥 {member_names(c, member_map)}"
            )

        # 5 KUN OG‘OHLANTIRISH
        if is_due_soon(c, list_name):
            key = cid + "_warn"

            if key not in warned_cards:
                send_message(
                    f"⚠️ Muddat yaqin\n\n"
                    f"{name}\n"
                    f"📅 {c.get('due','-')}"
                )
                warned_cards.add(key)

    known_cards.update(new_known)


# ---------------- REPORT ----------------
def generate_report():
    cards = [c for c in get_cards() if is_current_year_card(c)]
    list_map = {l["id"]: l["name"] for l in get_lists()}
    member_map = {m["id"]: m["fullName"] for m in get_members()}

    total = len(cards)
    active = 0
    done = 0
    overdue = 0
    no_due = 0

    column_stats = {}
    employee_stats = {}

    for c in cards:
        list_name = list_map.get(c["idList"], "")
        done_status = is_done(list_name)

        if done_status:
            done += 1
        else:
            active += 1

        if is_overdue(c, list_name):
            overdue += 1

        if not c.get("due") and not done_status:
            no_due += 1

        # USTUN
        if not done_status:
            column_stats[list_name] = column_stats.get(list_name, 0) + 1

        # XODIM
        for m in c.get("idMembers", []):
            name = member_map.get(m, m)

            if name not in employee_stats:
                employee_stats[name] = {"total": 0, "active": 0, "done": 0}

            employee_stats[name]["total"] += 1
            employee_stats[name]["done" if done_status else "active"] += 1

    text = f"📊 Xarid bo‘limi hisobot — {current_year()} yil\n\n"

    text += "📦 UMUMIY\n"
    text += f"Jami: {total}\nJarayonda: {active}\nYopilgan: {done}\n"
    text += f"Kechikkan: {overdue}\nMuddatsiz: {no_due}\n\n"

    text += "📂 USTUNLAR\n"
    for k, v in column_stats.items():
        text += f"{k}: {v}\n"

    text += "\n👨‍💼 XODIMLAR\n"
    for k, v in employee_stats.items():
        text += f"\n{k}\nJami: {v['total']} | Jarayonda: {v['active']} | Yopilgan: {v['done']}\n"

    return text


# ---------------- TELEGRAM ----------------
def get_last_update():
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates").json()
        return r["result"][-1]["update_id"] if r["result"] else None
    except:
        return None


def handle_commands():
    global last_update_id

    params = {}
    if last_update_id:
        params["offset"] = last_update_id + 1

    r = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params=params
    ).json()

    for upd in r.get("result", []):
        last_update_id = upd["update_id"]

        msg = upd.get("message", {})
        text = msg.get("text", "").lower()
        chat = str(msg.get("chat", {}).get("id"))

        if chat != CHAT_ID:
            continue

        if text in ["/hisobot", "hisobot"]:
            send_message(generate_report())


# ---------------- LOOP ----------------
def bot_loop():
    global last_update_id

    last_update_id = get_last_update()
    initialize_cards()

    while True:
        try:
            handle_commands()
            check_changes()
        except Exception as e:
            print("XATO:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
