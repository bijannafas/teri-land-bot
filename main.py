import os
import time
import sqlite3
import logging
import secrets
import requests

API_BASE = "https://botapi.rubika.ir/v3"
TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "teri_land.sqlite3")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2.5"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("teri-land")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            customer_chat_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def api(method, payload=None):
    if not TOKEN:
        raise RuntimeError("RUBIKA_BOT_TOKEN is not configured")
    url = f"{API_BASE}/{TOKEN}/{method}"
    response = requests.post(url, json=payload or {}, timeout=35)
    response.raise_for_status()
    result = response.json()
    if result.get("status") not in (None, "OK"):
        raise RuntimeError(f"Rubika API error: {result}")
    return result.get("data", result)


def send(chat_id, text, keypad=None):
    payload = {"chat_id": str(chat_id), "text": text}
    if keypad:
        payload["chat_keypad_type"] = "New"
        payload["chat_keypad"] = keypad
    return api("sendMessage", payload)


def main_keypad():
    # Rubika ChatKeypad buttons are standard buttons; black/gold is expressed
    # through the bot's copy and symbols, not unsupported button color settings.
    labels = [
        ["🟨 کاتالوگ قطعات", "☎️ ارتباط با فروش"],
        ["🛠 پشتیبانی مشتریان", "📣 کانال تری‌لند"],
        ["🏠 منوی اصلی"],
    ]
    return {
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "rows": [
            {"buttons": [
                {"id": text, "type": "Simple", "button_text": text}
                for text in row
            ]}
            for row in labels
        ],
    }


def send_home(chat_id):
    text = (
        "🖤 خوش آمدید به تری‌لند\n"
        "✨ مرجع معرفی و تأمین قطعات یدکی تریلر\n\n"
        "از منوی زیر بخش موردنظرتان را انتخاب کنید."
    )
    send(chat_id, text, main_keypad())


def send_catalog(chat_id):
    text = (
        "🟨 کاتالوگ قطعات تری‌لند\n\n"
        "• محور و متعلقات\n"
        "• سیستم ترمز و لنت\n"
        "• پایه و جک تریلر\n"
        "• سیستم روشنایی و برق\n"
        "• لاستیک، رینگ و متعلقات\n"
        "• قطعات تعلیق و زیربندی\n"
        "• قطعات بدنه و اتصالات\n\n"
        "برای استعلام موجودی، برند و قیمت، نام قطعه یا عکس آن را همین‌جا ارسال کنید."
    )
    send(chat_id, text, main_keypad())


def send_sales(chat_id):
    send(
        chat_id,
        "☎️ ارتباط با واحد فروش تری‌لند\n\n"
        "کارشناس فروش ۱: 09037882370\n"
        "کارشناس فروش ۲: 09189147468\n\n"
        "برای دریافت راهنمایی، پیام خود را از بخش پشتیبانی ارسال کنید.",
        main_keypad(),
    )


def send_channel(chat_id):
    send(
        chat_id,
        "📣 کانال رسمی تری‌لند\n"
        "برای مشاهده اطلاعیه‌ها و مطالب جدید، لینک زیر را لمس کنید:\n"
        "https://rubika.ir/Teri_land",
        main_keypad(),
    )


def new_ticket(customer_chat_id, text, message_id=None):
    ticket_id = secrets.token_hex(3).upper()
    with db() as conn:
        conn.execute(
            "INSERT INTO tickets(ticket_id, customer_chat_id) VALUES (?, ?)",
            (ticket_id, str(customer_chat_id)),
        )
    if ADMIN_CHAT_ID:
        admin_text = (
            f"🖤 پیام جدید پشتیبانی تری‌لند\n"
            f"شماره پیگیری: {ticket_id}\n"
            f"شناسه مشتری: {customer_chat_id}\n\n"
            f"{text}\n\n"
            f"برای پاسخ:\n/reply {ticket_id} متن پاسخ"
        )
        send(ADMIN_CHAT_ID, admin_text)
    send(
        customer_chat_id,
        f"✅ پیام شما ثبت شد.\nشماره پیگیری: {ticket_id}\n"
        "کارشناس تری‌لند در اولین فرصت پاسخ می‌دهد.",
        main_keypad(),
    )


def admin_reply(chat_id, text):
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        send(chat_id, "فرمت پاسخ:\n/reply شماره‌پیگیری متن پاسخ")
        return
    ticket_id, answer = parts[1].upper(), parts[2]
    with db() as conn:
        row = conn.execute(
            "SELECT customer_chat_id FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    if not row:
        send(chat_id, "شماره پیگیری پیدا نشد.")
        return
    send(row[0], f"🖤 پاسخ پشتیبانی تری‌لند\n\n{answer}", main_keypad())
    send(chat_id, f"✅ پاسخ شما برای مشتری {ticket_id} ارسال شد.")


def extract_message(update):
    # Official receiveUpdate shape: {"update":{"type":"NewMessage", ...}}
    if not isinstance(update, dict):
        return None
    body = update.get("update", update)
    if not isinstance(body, dict):
        return None
    msg = body.get("new_message") or body.get("message") or {}
    if not isinstance(msg, dict):
        return None
    chat_id = body.get("chat_id") or msg.get("chat_id")
    sender_id = msg.get("sender_id") or body.get("sender_id")
    text = msg.get("text") or ""
    aux = msg.get("aux_data") or {}
    button_id = aux.get("button_id") if isinstance(aux, dict) else None
    message_id = msg.get("message_id")
    return chat_id, sender_id, text, button_id, message_id, body.get("type")


def handle_update(update):
    extracted = extract_message(update)
    if not extracted:
        return
    chat_id, sender_id, text, button_id, message_id, update_type = extracted
    if not chat_id:
        return
    chat_id = str(chat_id)
    text = str(text or "").strip()
    action = str(button_id or text).strip()

    if text == "/myid":
        send(chat_id, f"شناسه چت شما:\n{chat_id}\n\nاین شناسه را فقط در متغیر ADMIN_CHAT_ID در Railway قرار دهید.")
        return

    if ADMIN_CHAT_ID and chat_id == ADMIN_CHAT_ID and text.startswith("/reply"):
        admin_reply(chat_id, text)
        return

    if action in ("/start", "شروع", "🏠 منوی اصلی"):
        send_home(chat_id)
    elif action in ("🟨 کاتالوگ قطعات", "کاتالوگ", "قطعات"):
        send_catalog(chat_id)
    elif action in ("☎️ ارتباط با فروش", "ارتباط با فروش", "فروش"):
        send_sales(chat_id)
    elif action in ("📣 کانال تری‌لند", "کانال", "کانال تری‌لند"):
        send_channel(chat_id)
    elif action in ("🛠 پشتیبانی مشتریان", "پشتیبانی", "پشتیبانی مشتریان"):
        send(
            chat_id,
            "🛠 پشتیبانی تری‌لند\n\n"
            "لطفاً سؤال، شرح مشکل یا تصویر قطعه موردنظر را ارسال کنید.\n"
            "پیام شما برای واحد پشتیبانی ثبت می‌شود.",
            main_keypad(),
        )
    elif text:
        # Every non-menu text from a customer becomes a support ticket.
        if not ADMIN_CHAT_ID:
            send(chat_id, "پشتیبانی هنوز توسط مدیر فعال نشده است. لطفاً با واحد فروش تماس بگیرید:\n09037882370\n09189147468", main_keypad())
        else:
            new_ticket(chat_id, text, message_id)
    else:
        send_home(chat_id)


def main():
    if not TOKEN:
        raise SystemExit(
            "خطا: متغیر محیطی RUBIKA_BOT_TOKEN تنظیم نشده است. "
            "آن را در Railway در بخش Variables اضافه کنید."
        )
    log.info("Teri Land bot is starting")
    offset_id = None
    while True:
        try:
            payload = {"limit": 100}
            if offset_id:
                payload["offset_id"] = offset_id
            data = api("getUpdates", payload)
            updates = data.get("updates", []) if isinstance(data, dict) else []
            for item in updates:
                try:
                    handle_update(item)
                except Exception:
                    log.exception("Failed to process an update")
            offset_id = data.get("next_offset_id", offset_id) if isinstance(data, dict) else offset_id
            if not updates:
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log.info("Bot stopped")
            break
        except Exception:
            log.exception("Polling failed; retrying")
            time.sleep(5)


if __name__ == "__main__":
    main()
