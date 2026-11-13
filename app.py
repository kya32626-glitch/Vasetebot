# ========================= PART 1/7: IMPORTS, CONFIG, DATABASE =========================
import os
import re
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, InputMediaPhoto
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    PreCheckoutQueryHandler, ContextTypes, filters
)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("vasete_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 8396752402
AD_CHANNEL_ID = "@Vasetearminazizi"
TRUST_CHANNEL_ID = "@etemadearminazizi"
CHANNELS = [
    (AD_CHANNEL_ID, "https://t.me/Vasetearminazizi"),
    (TRUST_CHANNEL_ID, "https://t.me/etemadearminazizi"),
]
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vasetebot.onrender.com").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "Nsjshsbsb").strip()
WEBHOOK_PATH = "/telegram-webhook"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MEDIATOR_STARS = int(os.getenv("MEDIATOR_STARS", "100"))

if not BOT_TOKEN:
    logger.warning("BOT_TOKEN is not set. Add it to Render Environment Variables.")


def _is_postgres() -> bool:
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


def _connect():
    if _is_postgres():
        if psycopg2 is None:
            raise RuntimeError("برای دیتابیس PostgreSQL باید psycopg2-binary نصب باشد.")
        return psycopg2.connect(
    DATABASE_URL,
    sslmode="require",
    options="-c search_path=public"
        )

def db_execute(sql: str, params: tuple = (), fetch: Optional[str] = None):
    """Run one SQL statement. fetch may be 'one' or 'all'."""
    conn = _connect()
    try:
        if _is_postgres():
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace("?", "%s"), params)
        else:
            cur = conn.cursor()
            cur.execute(sql, params)
        result = None
        if fetch == "one":
            row = cur.fetchone()
            result = dict(row) if row is not None else None
        elif fetch == "all":
            result = [dict(row) for row in cur.fetchall()]
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_insert(sql: str, params: tuple = ()) -> int:
    """Insert and return its id in both SQLite and PostgreSQL."""
    conn = _connect()
    try:
        if _is_postgres():
            cur = conn.cursor()
            cur.execute(sql.replace("?", "%s") + " RETURNING id", params)
            row = cur.fetchone()
            new_id = int(row[0])
        else:
            cur = conn.cursor()
            cur.execute(sql, params)
            new_id = int(cur.lastrowid)
        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    id_type = "SERIAL PRIMARY KEY" if _is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    statements = [
        f"""CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY, username TEXT, first_name TEXT,
            points INTEGER NOT NULL DEFAULT 0, invited_by BIGINT,
            is_banned INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS ads (
            id {id_type}, user_id BIGINT NOT NULL, text TEXT NOT NULL,
            photo_ids TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            edited_text TEXT, channel_message_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS requests (
            id {id_type}, user_id BIGINT NOT NULL, kind TEXT NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            admin_reply TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS payments (
            id {id_type}, user_id BIGINT NOT NULL, amount INTEGER NOT NULL,
            currency TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ]
    for statement in statements:
        db_execute(statement)

    # Migrate an older users table without deleting existing user records.
    if _is_postgres():
        rows = db_execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'users'",
            fetch="all",
        )
        columns = {row["column_name"] for row in rows}
        if "id" not in columns:
            old_id = next(
                (name for name in ("user_id", "telegram_id", "telegram_user_id", "uid")
                 if name in columns),
                None,
            )
            if old_id:
                db_execute(f'ALTER TABLE users RENAME COLUMN "{old_id}" TO id')
                columns.remove(old_id)
                columns.add("id")
            else:
                raise RuntimeError(
                    "جدول users در PostgreSQL ستون id ندارد و ستون شناسه قابل‌شناسایی هم پیدا نشد. "
                    "برای جلوگیری از حذف اطلاعات، دیتابیس را خودکار تغییر ندادم."
                )

        missing_columns = {
            "username": "TEXT",
            "first_name": "TEXT",
            "points": "INTEGER NOT NULL DEFAULT 0",
            "invited_by": "BIGINT",
            "is_banned": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column, sql_type in missing_columns.items():
            if column not in columns:
                db_execute(f'ALTER TABLE users ADD COLUMN "{column}" {sql_type}')
    else:
        rows = db_execute("PRAGMA table_info(users)", fetch="all")
        columns = {row["name"] for row in rows}
        if "id" not in columns:
            old_id = next(
                (name for name in ("user_id", "telegram_id", "telegram_user_id", "uid")
                 if name in columns),
                None,
            )
            if old_id:
                db_execute(f'ALTER TABLE users RENAME COLUMN "{old_id}" TO id')
                columns.remove(old_id)
                columns.add("id")
            else:
                raise RuntimeError(
                    "جدول users ستون id یا شناسه جایگزین ندارد؛ برای حفظ اطلاعات، "
                    "مهاجرت خودکار انجام نشد."
                )
        missing_columns = {
            "username": "TEXT",
            "first_name": "TEXT",
            "points": "INTEGER NOT NULL DEFAULT 0",
            "invited_by": "INTEGER",
            "is_banned": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column, sql_type in missing_columns.items():
            if column not in columns:
                db_execute(f'ALTER TABLE users ADD COLUMN "{column}" {sql_type}')


# ========================= PART 2/7: COMMON HELPERS AND KEYBOARDS =========================
def row_user(user_id: int):
    return db_execute("SELECT * FROM users WHERE id = ?", (user_id,), "one")


def ensure_user(user, inviter_id: Optional[int] = None) -> bool:
    existing = row_user(user.id)
    if existing:
        db_execute(
            "UPDATE users SET username = ?, first_name = ? WHERE id = ?",
            (user.username or "", user.first_name or "", user.id),
        )
        return False
    if inviter_id == user.id:
        inviter_id = None
    db_execute(
        "INSERT INTO users (id, username, first_name, invited_by) VALUES (?, ?, ?, ?)",
        (user.id, user.username or "", user.first_name or "", inviter_id),
    )
    if inviter_id:
        inviter = row_user(inviter_id)
        if inviter and not inviter.get("is_banned"):
            db_execute("UPDATE users SET points = points + 1 WHERE id = ?", (inviter_id,))
    return True


def is_banned(user_id: int) -> bool:
    user = row_user(user_id)
    return bool(user and user.get("is_banned"))


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def setting(key: str, default: str = "") -> str:
    row = db_execute("SELECT value FROM settings WHERE key = ?", (key,), "one")
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    db_execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


DEFAULT_TEXTS = {
    "welcome": "سلام {name} عزیز ❤️\nبه ربات واسطه‌گری خوش اومدی.",
    "mediator_terms": "برای ثبت درخواست واسطه‌گری، ابتدا هزینه را پرداخت کن. پس از پرداخت، ادمین با شما ارتباط می‌گیرد.",
}


def get_text(key: str) -> str:
    return setting(key, DEFAULT_TEXTS.get(key, ""))


def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🤝 درخواست واسطه", callback_data="mediator")],
        [InlineKeyboardButton("📋 ثبت آگهی", callback_data="post_ad")],
        [InlineKeyboardButton("💰 قیمت‌گذاری", callback_data="pricing"),
         InlineKeyboardButton("🛒 خرید اکانت", callback_data="buy_account")],
        [InlineKeyboardButton("❓ سوال از ادمین", callback_data="ask_question"),
         InlineKeyboardButton("🚨 گزارش", callback_data="report")],
        [InlineKeyboardButton("🎁 دعوت دوستان", callback_data="invite"),
         InlineKeyboardButton("⭐ امتیازهای من", callback_data="my_points")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def join_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("عضویت در کانال", url=url)] for _, url in CHANNELS]
    rows.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 آگهی‌های در انتظار", callback_data="admin_ads")],
        [InlineKeyboardButton("💰 درخواست‌های قیمت‌گذاری", callback_data="admin_pricing")],
        [InlineKeyboardButton("🛒 درخواست‌های خرید", callback_data="admin_buy")],
        [InlineKeyboardButton("❓ سوال‌ها و گزارش‌ها", callback_data="admin_other")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("✏️ ویرایش متن‌ها", callback_data="admin_texts")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="restart")],
    ])


async def check_membership(bot, user_id: int) -> bool:
    for channel_id, _ in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                return False
        except Exception as exc:
            logger.warning("Membership check failed for %s: %s", channel_id, exc)
            return False
    return True


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = get_text("welcome").format(name=user.first_name or "دوست")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard(user.id))
    else:
        await update.effective_message.reply_text(text, reply_markup=main_keyboard(user.id))


async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if is_admin(user.id):
        return True
    if await check_membership(context.bot, user.id):
        return True
    msg = "برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شو و بعد دکمه بررسی را بزن."
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=join_keyboard())
    else:
        await update.effective_message.reply_text(msg, reply_markup=join_keyboard())
    return False


# ========================= PART 3/7: START, REFERRAL, REQUEST FLOWS =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    inviter_id = None
    if context.args:
        match = re.fullmatch(r"ref_(\d+)", context.args[0])
        if match:
            inviter_id = int(match.group(1))
    is_new = ensure_user(user, inviter_id)
    if is_banned(user.id):
        await update.effective_message.reply_text("دسترسی شما به ربات محدود شده است.")
        return
    if not await require_membership(update, context):
        return
    await show_home(update, context)
    if is_new and inviter_id and row_user(inviter_id):
        try:
            await context.bot.send_message(inviter_id, "🎉 یک نفر با لینک دعوتت وارد ربات شد؛ ۱ امتیاز گرفتی.")
        except Exception:
            pass


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_message.reply_text("پنل مدیریت:", reply_markup=admin_keyboard())


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) or not context.args:
        return
    try:
        target_id = int(context.args[0])
        db_execute("UPDATE users SET is_banned = 1 WHERE id = ?", (target_id,))
        await update.effective_message.reply_text(f"کاربر {target_id} در ربات مسدود شد.")
    except ValueError:
        await update.effective_message.reply_text("شناسه کاربر باید عدد باشد. نمونه: /ban 123456")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) or not context.args:
        return
    try:
        target_id = int(context.args[0])
        db_execute("UPDATE users SET is_banned = 0 WHERE id = ?", (target_id,))
        await update.effective_message.reply_text(f"محدودیت کاربر {target_id} برداشته شد.")
    except ValueError:
        await update.effective_message.reply_text("شناسه کاربر باید عدد باشد. نمونه: /unban 123456")


async def create_request(user_id: int, kind: str, payload: str) -> int:
    return db_insert(
        "INSERT INTO requests (user_id, kind, payload) VALUES (?, ?, ?)",
        (user_id, kind, payload),
    )


async def notify_admin_request(context, request_id: int, kind_title: str, user, payload: str):
    text = (
        f"📩 درخواست جدید: {kind_title}\n"
        f"شناسه درخواست: #{request_id}\n"
        f"کاربر: {user.full_name} | آیدی: {user.id}\n\n{payload}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ پاسخ به کاربر", callback_data=f"reply_req_{request_id}")],
        [InlineKeyboardButton("❌ رد درخواست", callback_data=f"reject_req_{request_id}")],
    ])
    try:
        await context.bot.send_message(ADMIN_ID, text, reply_markup=kb)
    except Exception as exc:
        logger.exception("Cannot notify admin: %s", exc)


async def handle_menu_callback(query, context):
    user = query.from_user
    data = query.data
    if is_banned(user.id):
        await query.edit_message_text("دسترسی شما به ربات محدود شده است.")
        return
    if data == "restart":
        context.user_data.clear()
        await show_home_from_query(query)
    elif data == "invite":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.id}"
        await query.edit_message_text(
            f"🎁 لینک دعوت اختصاصی شما:\n{link}\n\nبا ورود هر کاربر جدید از لینک شما، یک امتیاز می‌گیری.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="restart")]])
        )
    elif data == "my_points":
        u = row_user(user.id) or {}
        await query.edit_message_text(
            f"⭐ امتیازهای شما: {u.get('points', 0)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="restart")]])
        )
    elif data == "mediator":
        await query.edit_message_text(
            get_text("mediator_terms"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"⭐ پرداخت {MEDIATOR_STARS} استار", callback_data="mediator_pay")],
                [InlineKeyboardButton("🎁 استفاده از امتیاز رایگان", callback_data="free_mediator")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="restart")],
            ])
        )
    elif data == "mediator_pay":
        payload = f"mediator:{user.id}:{MEDIATOR_STARS}"
        await context.bot.send_invoice(
            chat_id=user.id, title="هزینه واسطه‌گری", description="پرداخت هزینه درخواست واسطه‌گری",
            payload=payload, provider_token="", currency="XTR",
            prices=[LabeledPrice("واسطه‌گری", MEDIATOR_STARS)],
        )
        await query.edit_message_text("فاکتور پرداخت برای شما ارسال شد.")
    elif data == "free_mediator":
        u = row_user(user.id) or {}
        if int(u.get("points", 0)) < 1:
            await query.edit_message_text(
                "امتیاز کافی نداری.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="restart")]])
            )
            return
        db_execute("UPDATE users SET points = points - 1 WHERE id = ?", (user.id,))
        req_id = await create_request(user.id, "mediator", "درخواست واسطه‌گری با امتیاز رایگان")
        await notify_admin_request(context, req_id, "واسطه‌گری رایگان", user, "درخواست با یک امتیاز ثبت شد.")
        await query.edit_message_text("✅ درخواست واسطه‌گری ثبت شد. ادمین به‌زودی با شما ارتباط می‌گیرد.")
    elif data == "post_ad":
        await send_ad_form(query.message, context, user)
    elif data in ("pricing", "buy_account", "ask_question", "report"):
        labels = {
            "pricing": ("قیمت‌گذاری", "اطلاعات اکانت و قیمت پیشنهادی خود را ارسال کن."),
            "buy_account": ("خرید اکانت", "لینک یا توضیحات اکانت موردنظر برای خرید را ارسال کن."),
            "ask_question": ("سوال از ادمین", "سوالت را در یک پیام ارسال کن."),
            "report": ("گزارش", "گزارش خود را همراه با توضیحات ارسال کن."),
        }
        title, prompt = labels[data]
        context.user_data["mode"] = data
        await query.edit_message_text(
            f"{prompt}\n\nبرای لغو، /cancel را بفرست.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="restart")]])
        )
    elif data == "check_join":
        if await check_membership(context.bot, user.id):
            await query.edit_message_text("✅ عضویت تأیید شد.")
            await show_home_from_query(query)
        else:
            await query.message.reply_text("هنوز عضویت شما در همه کانال‌ها تأیید نشده است.", reply_markup=join_keyboard())
    elif data == "admin_panel" and is_admin(user.id):
        await query.edit_message_text("پنل مدیریت:", reply_markup=admin_keyboard())
    else:
        await admin_callback(query, context)


async def show_home_from_query(query):
    text = get_text("welcome").format(name=query.from_user.first_name or "دوست")
    await query.edit_message_text(text, reply_markup=main_keyboard(query.from_user.id))


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("عملیات لغو شد.", reply_markup=main_keyboard(update.effective_user.id))


# ========================= PART 4/7: AD FORM, PHOTO VALIDATION, ADMIN AD REVIEW =========================
AD_FORM = """📋 فرم ثبت اگهی:

نوع بازی🎮:
ـــــــــــــــــــــــــــــــــــ

سیو ها📥:
ـــــــــــــــــــــــــــــــــ

ایا قابل چنج هست:
تعداد سیپی🪙:
تعداد گان متیک 🟥:
تعداد گان لجند 🟨:
تعداد بتل پس:
توضیحات فروشنده:
Uid:
قیمت:
آیدی فروشنده:

جهت خرید اکانت اگهی کردن اکانت و قیمت گزاری و درخاست واسطه به بات مراجعه کنید:
@Vasetearminazizibot

جهت ارتباط با ادمین و واسطه گری اکانت:
@Vasete_armin_azizi

چنلمون:
https://t.me/Vasetearminazizi

اعتماد:
https://t.me/etemadearminazizi"""


async def send_ad_form(message, context, user):
    context.user_data["mode"] = "ad_form"
    context.user_data.pop("pending_ad_text", None)
    context.user_data["pending_ad_photos"] = []
    context.user_data.pop("ad_photo_overflow", None)
    await message.reply_text(AD_FORM)
    await message.reply_text(
        "اطلاعات اکانتتونو در فرم بالا پر کنید و سپس ارسال کنید\n\n"
        "❗️ اگر اکانت شما گزینه های زیر رو نداشته باشه آگهی نمیشه:\n"
        "1_ آیدی فروشنده الزامیس\n"
        "2_ عکس حد اقل 2 و حد اکثر 9 تا\n\n"
        "فرم را همراه عکس ها ارسال کنید و پیام اضافه نفرستید.\n"
        f"ممنون از شما {user.first_name or 'دوست'} ❤️"
    )


def seller_id_is_present(text: str) -> bool:
    match = re.search(r"آیدی\s*فروشنده\s*[:：]\s*([^\r\n]*)", text, re.IGNORECASE)
    if not match:
        return False
    value = match.group(1).strip()
    return bool(value and not re.fullmatch(r"[-_ـ.\s]+", value))


def clean_ad_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\n?فرم را همراه عکس ها ارسال کنید.*$", "", text, flags=re.S)
    return text.strip()


async def process_ad_text(message, context):
    text = clean_ad_text(message.text or message.caption or "")
    if not seller_id_is_present(text):
        await message.reply_text("❌ آیدی فروشنده در فرم الزامی است. فرم را کامل کن و دوباره بفرست.")
        return
    context.user_data["pending_ad_text"] = text
    context.user_data["mode"] = "ad_photos"
    context.user_data.setdefault("pending_ad_photos", [])
    count = len(context.user_data["pending_ad_photos"])
    await message.reply_text(
        f"✅ فرم دریافت شد. حالا ۲ تا ۹ عکس اکانت را ارسال کن.\nتعداد عکس‌های دریافت‌شده: {count}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ثبت نهایی آگهی", callback_data="submit_ad")]])
    )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if is_banned(user.id):
        return
    mode = context.user_data.get("mode")
    if mode == "broadcast" and is_admin(user.id):
        users = db_execute("SELECT id FROM users WHERE is_banned = 0", fetch="all")
        sent = 0
        for item in users:
            try:
                await context.bot.copy_message(
                    chat_id=item["id"], from_chat_id=message.chat_id,
                    message_id=message.message_id
                )
                sent += 1
            except Exception:
                continue
        context.user_data.pop("mode", None)
        await message.reply_text(f"✅ پیام همگانی برای {sent} کاربر ارسال شد.")
        return
    if mode not in ("ad_form", "ad_photos"):
        return
    if message.caption and not context.user_data.get("pending_ad_text"):
        caption = clean_ad_text(message.caption)
        if seller_id_is_present(caption):
            context.user_data["pending_ad_text"] = caption
            context.user_data["mode"] = "ad_photos"
    photos = context.user_data.setdefault("pending_ad_photos", [])
    file_id = message.photo[-1].file_id
    if file_id not in photos:
        photos.append(file_id)
    count = len(photos)
    if count > 9:
        context.user_data["ad_photo_overflow"] = True
        await message.reply_text("❌ تعداد عکس‌ها بیشتر از ۹ تا شد. /cancel بزن و آگهی را دوباره با ۲ تا ۹ عکس ثبت کن.")
        return
    await message.reply_text(
        f"📸 عکس دریافت شد: {count}\nبعد از ارسال ۲ تا ۹ عکس، دکمه ثبت نهایی را بزن.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ثبت نهایی آگهی", callback_data="submit_ad")]])
    )


async def finalize_ad(query, context):
    user = query.from_user
    text = context.user_data.get("pending_ad_text", "")
    photos = context.user_data.get("pending_ad_photos", [])
    if context.user_data.get("ad_photo_overflow"):
        await query.answer("تعداد عکس‌ها بیشتر از ۹ تا شده؛ عملیات را لغو و دوباره شروع کن.", show_alert=True)
        return
    if not seller_id_is_present(text):
        await query.answer("اول فرم کامل را همراه آیدی فروشنده ارسال کن.", show_alert=True)
        return
    if not 2 <= len(photos) <= 9:
        await query.answer("برای ثبت آگهی باید حداقل ۲ و حداکثر ۹ عکس ارسال کنی.", show_alert=True)
        return
    ad_id = db_insert(
        "INSERT INTO ads (user_id, text, photo_ids, status) VALUES (?, ?, ?, 'pending')",
        (user.id, text, json.dumps(photos)),
    )
    context.user_data.pop("pending_ad_text", None)
    context.user_data.pop("pending_ad_photos", None)
    context.user_data.pop("ad_photo_overflow", None)
    context.user_data.pop("mode", None)
    await query.edit_message_text(f"✅ آگهی شما با شماره #{ad_id} برای بررسی ادمین ارسال شد.")
    await query.answer("آگهی ثبت شد.")
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"📥 آگهی جدید #{ad_id}\nکاربر: {user.full_name} | {user.id}\n\n{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأیید و انتشار", callback_data=f"approve_ad_{ad_id}")],
                [InlineKeyboardButton("✏️ ویرایش متن", callback_data=f"edit_ad_{ad_id}"),
                 InlineKeyboardButton("❌ رد آگهی", callback_data=f"reject_ad_{ad_id}")],
            ])
        )
        media = [InputMediaPhoto(media=p) for p in photos]
        await context.bot.send_media_group(ADMIN_ID, media=media)
    except Exception as exc:
        logger.exception("Sending ad to admin failed: %s", exc)


async def publish_ad(ad: dict, context):
    text = ad.get("edited_text") or ad["text"]
    photos = json.loads(ad["photo_ids"] or "[]")
    await context.bot.send_message(AD_CHANNEL_ID, text)
    if photos:
        media = [InputMediaPhoto(media=p) for p in photos]
        await context.bot.send_media_group(AD_CHANNEL_ID, media=media)


# ========================= PART 5/7: MESSAGE ROUTER, PAYMENTS, ADMIN REQUESTS =========================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or is_banned(user.id):
        return
    text = (message.text or "").strip()
    mode = context.user_data.get("mode")

    if mode in ("ad_form", "ad_photos") and ("نوع بازی" in text or "آیدی فروشنده" in text):
        await process_ad_text(message, context)
        return
    if mode == "ad_photos" and text.lower() in ("ثبت", "ثبت نهایی", "ارسال"):
        await message.reply_text(
            "برای ثبت نهایی روی دکمه زیر بزن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ثبت نهایی آگهی", callback_data="submit_ad")]])
        )
        return
    request_modes = {
        "pricing": "قیمت‌گذاری", "buy_account": "خرید اکانت",
        "ask_question": "سوال", "report": "گزارش",
    }
    if mode in request_modes:
        if len(text) < 2:
            await message.reply_text("لطفاً توضیحات بیشتری بفرست.")
            return
        req_id = await create_request(user.id, mode, text)
        await notify_admin_request(context, req_id, request_modes[mode], user, text)
        context.user_data.pop("mode", None)
        await message.reply_text(
            f"✅ درخواست شما با شماره #{req_id} ثبت شد.",
            reply_markup=main_keyboard(user.id)
        )
        return

    if is_admin(user.id):
        if mode == "broadcast":
            users = db_execute("SELECT id FROM users WHERE is_banned = 0", fetch="all")
            sent = 0
            for item in users:
                try:
                    await context.bot.copy_message(
                        chat_id=item["id"], from_chat_id=message.chat_id,
                        message_id=message.message_id
                    )
                    sent += 1
                except Exception:
                    continue
            context.user_data.pop("mode", None)
            await message.reply_text(f"✅ پیام همگانی برای {sent} کاربر ارسال شد.")
            return
        if mode == "admin_edit_text":
            key = context.user_data.pop("edit_key", "")
            if key:
                set_setting(key, text)
            context.user_data.pop("mode", None)
            await message.reply_text("✅ متن ذخیره شد.", reply_markup=admin_keyboard())
            return
        if mode == "admin_edit_ad":
            ad_id = context.user_data.pop("edit_ad_id", None)
            ad = db_execute("SELECT * FROM ads WHERE id = ?", (ad_id,), "one") if ad_id else None
            if ad:
                db_execute("UPDATE ads SET edited_text = ? WHERE id = ?", (text, ad_id))
                await message.reply_text(f"✅ متن آگهی #{ad_id} ویرایش و ذخیره شد.")
            else:
                await message.reply_text("آگهی پیدا نشد.")
            context.user_data.pop("mode", None)
            return
        if mode == "admin_reply_request":
            req_id = context.user_data.pop("reply_request_id", None)
            req = db_execute("SELECT * FROM requests WHERE id = ?", (req_id,), "one") if req_id else None
            if req:
                db_execute("UPDATE requests SET status = 'answered', admin_reply = ? WHERE id = ?", (text, req_id))
                await context.bot.send_message(req["user_id"], f"📩 پاسخ ادمین به درخواست #{req_id}:\n\n{text}")
                await message.reply_text("✅ پاسخ برای کاربر ارسال شد.")
            else:
                await message.reply_text("درخواست پیدا نشد.")
            context.user_data.pop("mode", None)
            return
        if mode == "glass_button_text":
            context.user_data["glass_button_label"] = text[:64]
            context.user_data["mode"] = "glass_button_url"
            await message.reply_text("حالا لینک دکمه را بفرست (با https:// شروع شود).")
            return
        if mode == "glass_button_url":
            label = context.user_data.pop("glass_button_label", "مشاهده")
            post_id = context.user_data.pop("glass_post_id", None)
            if not re.match(r"^https?://", text):
                await message.reply_text("لینک معتبر نیست؛ با https:// شروعش کن.")
                return
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=AD_CHANNEL_ID, message_id=post_id,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(label, url=text)]])
                )
                await message.reply_text("✅ دکمه به پست کانال اضافه شد.")
            except Exception as exc:
                logger.exception("Could not add channel button: %s", exc)
                await message.reply_text("افزودن دکمه ناموفق بود؛ دسترسی ادمین ربات به کانال را بررسی کن.")
            context.user_data.pop("mode", None)
            return

    await message.reply_text("از دکمه‌های منوی اصلی استفاده کن.", reply_markup=main_keyboard(user.id))


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    valid = False
    try:
        parts = query.invoice_payload.split(":")
        valid = (
            len(parts) == 3 and parts[0] == "mediator"
            and int(parts[1]) == query.from_user.id
            and int(parts[2]) == MEDIATOR_STARS
            and query.currency == "XTR"
            and query.total_amount == MEDIATOR_STARS
        )
    except (ValueError, TypeError):
        valid = False
    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="فاکتور نامعتبر است. دوباره از منوی ربات اقدام کن.")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    payment = message.successful_payment
    parts = payment.invoice_payload.split(":")
    if len(parts) != 3 or parts[0] != "mediator":
        await message.reply_text("پرداخت دریافت شد، اما اطلاعات فاکتور قابل تأیید نیست. با ادمین ارتباط بگیر.")
        return
    try:
        owner_id, expected_amount = int(parts[1]), int(parts[2])
    except ValueError:
        return
    if owner_id != user.id or expected_amount != payment.total_amount or payment.currency != "XTR":
        await message.reply_text("اطلاعات پرداخت با فاکتور مطابقت ندارد. با ادمین ارتباط بگیر.")
        return
    db_insert(
        "INSERT INTO payments (user_id, amount, currency, payload) VALUES (?, ?, ?, ?)",
        (user.id, payment.total_amount, payment.currency, payment.invoice_payload),
    )
    req_id = await create_request(user.id, "mediator", "هزینه واسطه‌گری با موفقیت پرداخت شد.")
    await message.reply_text(f"✅ پرداخت با موفقیت ثبت شد. درخواست واسطه‌گری شما #{req_id} است.")
    await notify_admin_request(context, req_id, "واسطه‌گری پرداخت‌شده", user, "پرداخت استار با موفقیت انجام شد.")


async def document_video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Documents and videos do not count as required ad photos.
    message = update.effective_message
    user = update.effective_user
    if is_admin(user.id) and context.user_data.get("mode") == "broadcast":
        users = db_execute("SELECT id FROM users WHERE is_banned = 0", fetch="all")
        sent = 0
        for item in users:
            try:
                await context.bot.copy_message(chat_id=item["id"], from_chat_id=message.chat_id, message_id=message.message_id)
                sent += 1
            except Exception:
                continue
        context.user_data.pop("mode", None)
        await message.reply_text(f"✅ پیام همگانی برای {sent} کاربر ارسال شد.")
        return
    if context.user_data.get("mode") in ("ad_form", "ad_photos"):
        await message.reply_text("❌ فقط عکس معمولی تلگرام قابل قبول است؛ فایل و ویدئو جزو ۲ تا ۹ عکس حساب نمی‌شود.")


# ========================= PART 6/7: ADMIN CALLBACKS, STATS, BAN, CHANNEL BUTTON =========================
async def admin_callback(query, context):
    if not is_admin(query.from_user.id):
        await query.answer("این بخش فقط برای ادمین است.", show_alert=True)
        return
    data = query.data

    if data == "admin_ads":
        ads = db_execute("SELECT * FROM ads WHERE status = 'pending' ORDER BY id DESC LIMIT 20", fetch="all")
        await query.edit_message_text("📥 آگهی‌های در انتظار:")
        if not ads:
            await context.bot.send_message(ADMIN_ID, "آگهی در انتظار بررسی وجود ندارد.")
        for ad in ads:
            await context.bot.send_message(
                ADMIN_ID,
                f"آگهی #{ad['id']} | کاربر {ad['user_id']}\n\n{ad['edited_text'] or ad['text']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تأیید", callback_data=f"approve_ad_{ad['id']}")],
                    [InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_ad_{ad['id']}"),
                     InlineKeyboardButton("❌ رد", callback_data=f"reject_ad_{ad['id']}")],
                    [InlineKeyboardButton("🚫 مسدودسازی کاربر", callback_data=f"ban_{ad['user_id']}")],
                ])
            )
    elif data.startswith("approve_ad_"):
        ad_id = int(data.rsplit("_", 1)[1])
        ad = db_execute("SELECT * FROM ads WHERE id = ?", (ad_id,), "one")
        if not ad or ad["status"] != "pending":
            await query.answer("این آگهی وجود ندارد یا قبلاً بررسی شده است.", show_alert=True)
            return
        try:
            await publish_ad(ad, context)
            db_execute("UPDATE ads SET status = 'approved' WHERE id = ?", (ad_id,))
            await context.bot.send_message(ad["user_id"], f"✅ آگهی #{ad_id} تأیید و در کانال منتشر شد.")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.answer("آگهی منتشر شد.")
        except Exception as exc:
            logger.exception("Publish ad failed: %s", exc)
            await query.answer("انتشار ناموفق بود. دسترسی ربات به کانال را بررسی کن.", show_alert=True)
    elif data.startswith("reject_ad_"):
        ad_id = int(data.rsplit("_", 1)[1])
        ad = db_execute("SELECT * FROM ads WHERE id = ?", (ad_id,), "one")
        if ad:
            db_execute("UPDATE ads SET status = 'rejected' WHERE id = ?", (ad_id,))
            await context.bot.send_message(ad["user_id"], f"❌ آگهی #{ad_id} توسط ادمین رد شد.")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("آگهی رد شد.")
    elif data.startswith("edit_ad_"):
        ad_id = int(data.rsplit("_", 1)[1])
        context.user_data["mode"] = "admin_edit_ad"
        context.user_data["edit_ad_id"] = ad_id
        await query.message.reply_text(f"متن جدید آگهی #{ad_id} را ارسال کن:")
        await query.answer()
    elif data in ("admin_pricing", "admin_buy", "admin_other"):
        kind_map = {
            "admin_pricing": ["pricing"], "admin_buy": ["buy_account"],
            "admin_other": ["ask_question", "report"],
        }
        kinds = kind_map[data]
        placeholders = ",".join(["?"] * len(kinds))
        reqs = db_execute(
            f"SELECT * FROM requests WHERE status = 'pending' AND kind IN ({placeholders}) ORDER BY id DESC LIMIT 25",
            tuple(kinds), "all"
        )
        await query.edit_message_text(f"درخواست‌های در انتظار: {len(reqs)}")
        for req in reqs:
            await context.bot.send_message(
                ADMIN_ID,
                f"درخواست #{req['id']} | {req['kind']} | کاربر {req['user_id']}\n\n{req['payload']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✍️ پاسخ", callback_data=f"reply_req_{req['id']}")],
                    [InlineKeyboardButton("❌ رد", callback_data=f"reject_req_{req['id']}")],
                    [InlineKeyboardButton("🚫 مسدودسازی کاربر", callback_data=f"ban_{req['user_id']}")],
                ])
            )
    elif data.startswith("reply_req_"):
        req_id = int(data.rsplit("_", 1)[1])
        context.user_data["mode"] = "admin_reply_request"
        context.user_data["reply_request_id"] = req_id
        await query.message.reply_text(f"پاسخ درخواست #{req_id} را ارسال کن:")
        await query.answer()
    elif data.startswith("reject_req_"):
        req_id = int(data.rsplit("_", 1)[1])
        req = db_execute("SELECT * FROM requests WHERE id = ?", (req_id,), "one")
        if req:
            db_execute("UPDATE requests SET status = 'rejected' WHERE id = ?", (req_id,))
            await context.bot.send_message(req["user_id"], f"❌ درخواست #{req_id} توسط ادمین رد شد.")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("درخواست رد شد.")
    elif data.startswith("ban_"):
        target_id = int(data.rsplit("_", 1)[1])
        db_execute("UPDATE users SET is_banned = 1 WHERE id = ?", (target_id,))
        await query.answer("کاربر در ربات مسدود شد.", show_alert=True)
        await query.message.reply_text(f"کاربر {target_id} در ربات مسدود شد.")
    elif data.startswith("unban_"):
        target_id = int(data.rsplit("_", 1)[1])
        db_execute("UPDATE users SET is_banned = 0 WHERE id = ?", (target_id,))
        await query.answer("محدودیت کاربر برداشته شد.", show_alert=True)
    elif data == "admin_stats":
        users = db_execute("SELECT COUNT(*) AS n FROM users", fetch="one")["n"]
        banned = db_execute("SELECT COUNT(*) AS n FROM users WHERE is_banned = 1", fetch="one")["n"]
        pending_ads = db_execute("SELECT COUNT(*) AS n FROM ads WHERE status = 'pending'", fetch="one")["n"]
        pending_req = db_execute("SELECT COUNT(*) AS n FROM requests WHERE status = 'pending'", fetch="one")["n"]
        paid = db_execute("SELECT COALESCE(SUM(amount), 0) AS n FROM payments", fetch="one")["n"]
        await query.edit_message_text(
            f"📊 آمار ربات\n\n👥 کاربران: {users}\n🚫 مسدود: {banned}\n"
            f"📥 آگهی‌های در انتظار: {pending_ads}\n📩 درخواست‌های در انتظار: {pending_req}\n⭐ مجموع استار دریافت‌شده: {paid}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel")]])
        )
    elif data == "admin_broadcast":
        context.user_data["mode"] = "broadcast"
        await query.message.reply_text("پیام یا عکس همراه کپشن را بفرست تا برای همه کاربران غیرمسدود ارسال شود. برای لغو /cancel")
        await query.answer()
    elif data == "admin_texts":
        await query.edit_message_text(
            "کدام متن را می‌خواهی ویرایش کنی؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("متن خوش‌آمدگویی", callback_data="edit_txt_welcome")],
                [InlineKeyboardButton("متن توضیحات واسطه", callback_data="edit_txt_mediator_terms")],
                [InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_panel")],
            ])
        )
    elif data.startswith("edit_txt_"):
        key = data[len("edit_txt_"):]
        if key not in DEFAULT_TEXTS:
            await query.answer("کلید متن نامعتبر است.", show_alert=True)
            return
        context.user_data["mode"] = "admin_edit_text"
        context.user_data["edit_key"] = key
        await query.message.reply_text(f"متن جدید برای {key} را ارسال کن:")
        await query.answer()
    else:
        await query.answer("دستور ناشناخته است.", show_alert=True)


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post
    if not post or post.chat.username != AD_CHANNEL_ID.lstrip("@"):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن دکمه لینک", callback_data=f"ch_glass_yes_{post.message_id}")],
        [InlineKeyboardButton("بدون دکمه", callback_data=f"ch_glass_no_{post.message_id}")],
    ])
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"برای پست جدید کانال (پیام {post.message_id}) دکمه لینک اضافه شود؟",
            reply_markup=kb,
        )
    except Exception as exc:
        logger.warning("Could not message admin about channel post: %s", exc)


async def channel_button_callback(query, context):
    if not is_admin(query.from_user.id):
        await query.answer("فقط ادمین.", show_alert=True)
        return
    data = query.data
    if data.startswith("ch_glass_yes_"):
        post_id = int(data.rsplit("_", 1)[1])
        context.user_data["glass_post_id"] = post_id
        context.user_data["mode"] = "glass_button_text"
        await query.message.reply_text("متن دکمه را بفرست:")
        await query.answer()
    elif data.startswith("ch_glass_no_"):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("باشه.")


# ========================= PART 7/7: CALLBACK DISPATCH, FASTAPI WEBHOOK, STARTUP =========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    try:
        if data not in ("check_join",) and not is_admin(query.from_user.id):
            if not await require_membership(update, context):
                await query.answer()
                return
        # Special actions answer their own callback after processing.
        if data.startswith(("approve_ad_", "reject_ad_", "edit_ad_", "reply_req_", "reject_req_",
                            "ban_", "unban_", "edit_txt_", "ch_glass_yes_", "ch_glass_no_")):
            await channel_or_admin_dispatch(query, context)
            return
        if data == "submit_ad":
            await finalize_ad(query, context)
            return
        await query.answer()
        await handle_menu_callback(query, context)
    except Exception as exc:
        logger.exception("Callback failed (%s): %s", data, exc)
        try:
            await query.answer("خطایی رخ داد. دوباره تلاش کن.", show_alert=True)
        except Exception:
            pass


async def channel_or_admin_dispatch(query, context):
    data = query.data or ""
    if data.startswith(("ch_glass_yes_", "ch_glass_no_")):
        await channel_button_callback(query, context)
    else:
        await admin_callback(query, context)


telegram_app: Optional[Application] = None
app = FastAPI(title="Vasete Telegram Bot")


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "telegram-bot"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    global telegram_app
    if telegram_app is None:
        raise HTTPException(status_code=503, detail="Bot is not ready")
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return JSONResponse({"ok": True})
    except Exception as exc:
        logger.exception("Webhook update failed: %s", exc)
        return JSONResponse({"ok": False}, status_code=500)


@app.on_event("startup")
async def startup_event():
    global telegram_app
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing; web service started without Telegram bot.")
        return
    telegram_app = Application.builder().token(BOT_TOKEN).updater(None).build()
    telegram_app.add_handler(CommandHandler("start", start_cmd))
    telegram_app.add_handler(CommandHandler("admin", admin_cmd))
    telegram_app.add_handler(CommandHandler("ban", ban_cmd))
    telegram_app.add_handler(CommandHandler("unban", unban_cmd))
    telegram_app.add_handler(CommandHandler("cancel", cancel_cmd))
    telegram_app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    telegram_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    telegram_app.add_handler(CallbackQueryHandler(callback_router))
    telegram_app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    telegram_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, document_video_handler))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = BASE_URL + WEBHOOK_PATH
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    logger.info("Bot started. Webhook: %s", webhook_url)


@app.on_event("shutdown")
async def shutdown_event():
    global telegram_app
    if telegram_app is not None:
        try:
            await telegram_app.bot.delete_webhook()
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception as exc:
            logger.warning("Shutdown error: %s", exc)
        telegram_app = None


# Local run (optional): uvicorn app:app --host 0.0.0.0 --port 8000
