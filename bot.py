import os, logging, sqlite3, asyncio
from threading import RLock
from fastapi import FastAPI, Request, Response, HTTPException
import uvicorn
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as K, BotCommand, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, PreCheckoutQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 8396752402
STARS_ADMIN_ID = 8396752402
AD_CHANNEL_ID = "@Vasetearminazizi"
CHANNELS = [
    ("@Vasetearminazizi", "https://t.me/Vasetearminazizi"),
    ("@etemadearminazizi", "https://t.me/etemadearminazizi")
]

WEBHOOK_SECRET = "Nsjshsbsb"
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vasetebot.onrender.com").rstrip("/")
WEBHOOK_PATH = "/telegram-webhook"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN در متغیرهای Render تنظیم نشده است.")

db_lock = RLock()
if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import DictCursor
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = True
    c = conn.cursor(cursor_factory=DictCursor)
    def q(sql): return sql.replace("?", "%s")
else:
    conn = sqlite3.connect("bot.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    def q(sql): return sql

def db(sql, params=()):
    with db_lock:
        c.execute(q(sql), params)
        return c

def commit():
    if not DATABASE_URL:
        conn.commit()

def val(row, key, index=0):
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]

def create_table(name, fields):
    db(f"CREATE TABLE IF NOT EXISTS {name} ({fields})")

id_field = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"

create_table("users", "user_id BIGINT PRIMARY KEY, is_banned INT DEFAULT 0, ref_count INT DEFAULT 0, points INT DEFAULT 0")
create_table("settings", "key TEXT PRIMARY KEY, value TEXT")
create_table("referrals", "invited_id BIGINT PRIMARY KEY, inviter_id BIGINT")
create_table("ads", f"id {id_field}, user_id BIGINT, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
create_table("pricing_requests", f"id {id_field}, user_id BIGINT, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
create_table("buy_requests", f"id {id_field}, user_id BIGINT, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', link TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
create_table("questions", f"id {id_field}, user_id BIGINT, question_text TEXT, answer_text TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
commit()

try:
    db("ALTER TABLE users ADD COLUMN points INT DEFAULT 0")
    commit()
except Exception:
    if DATABASE_URL:
        conn.rollback()

DEFAULT_TEXTS = {
"welcome": "این تنها ربات پاسخگویی واسطه گری آرمین عزیزی است\nآیدی ادمین واسطه: @Vasete_armin_azizi\n\nسلام %name% عزیز!",
"mediator": "قیمت های واسطه گری به این صورت است:\n\nمعامله زیر 50 هزار: رایگان\n━━━━━━━━━━━━━━━━━\nمعامله 50 تا 100 هزار: رایگان\n━━━━━━━━━━━━━━━━━\nمعامله 100 تا 300 هزار: نفری ۱۰ هزار\n━━━━━━━━━━━━━━━━━\nمعامله 400 تا 900 هزار: نفری ۵۰ هزار\n━━━━━━━━━━━━━━━━━\nمعامله 1500 تا 3 میل: نفری 100 هزار\n━━━━━━━━━━━━━━━━━\nمعامله ۴ تا ۱۰ میل: نفری 350 هزار\n━━━━━━━━━━━━━━━━━\nمعامله بالای 10 میل: نفری ۵۰۰ هزار\n\nاگر با قیمت ها اوکی بودید تایید را بزنید.",
"mediator_confirm": "لطفاً اطلاعات زیر را به آیدی زیر ارسال نمایید:\n\n@Vasete_armin_azizi\n\n1_ آیدی شما و طرف مقابل\n2_ فرم آگهی اکانت یا عکس ها\n3_ ارزش اکانت شما\n\n⚠️ تایید دو مرحله اکانت کالاف دیوتی الزامی است.\nمعامله فقط توسط همین آیدی انجام می‌شود.",
"post_ad": "📋 فرم ثبت آگهی:\n\nنوع بازی🎮:\nـــــــــــــــــــــــــــــــــــ\n\nسیو ها📥:\nـــــــــــــــــــــــــــــــــ\n\nآیا قابل چنج هست:\nتعداد سیپی🪙:\nتعداد گان متیک 🟥:\nتعداد گان لجند 🟨:\nتعداد بتل پس:\nتوضیحات فروشنده:\nUID:\nقیمت:\nآیدی فروشنده:\n\nجهت خرید، ثبت آگهی، قیمت‌گذاری و درخواست واسطه به بات مراجعه کنید:\n@Vasetearminazizibot\n\nجهت ارتباط با ادمین و واسطه‌گری:\n@Vasete_armin_azizi\n\nچنل:\nhttps://t.me/Vasetearminazizi\n\nاعتماد:\nhttps://t.me/etemadearminazizi",
"pricing": "برای قیمت‌گذاری اکانت اطلاعات زیر را ارسال نمایید:\n\n• عکس‌های اکانت\n• آیتم‌ها\n• وضعیت سیوها\n• سیپی منفی دارد / ندارد\n\nاز ارسال پیام‌های دیگر خودداری نمایید.",
"buy": "لینک آگهی اکانتی که قصد خرید آن را دارید ارسال کنید.\nآگهی باید در کانال خرید و فروش ما ثبت شده باشد.\nپس از استعلام به شما اطلاع داده می‌شود."
}

AD_GUIDE = (
"اطلاعات اکانتتونو در فرم بالا پر کنید و سپس ارسال کنید.\n\n"
"❗️ اگر اکانت شما گزینه‌های زیر رو نداشته باشه آگهی نمیشه:\n"
"1_ آیدی فروشنده الزامی است\n"
"2_ حداقل ۲ و حداکثر ۹ عکس\n\n"
"فرم را همراه عکس‌ها ارسال کنید و پیام اضافه نفرستید.\n"
"ممنون از شما {name} ❤️"
)

def get_text(key, name=""):
    row = db("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    text = val(row, "value") if row else DEFAULT_TEXTS.get(key, "")
    return text.replace("%name%", name or "")

def set_text(key, text):
    db("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, text))
    commit()

def is_admin(uid):
    return uid == ADMIN_ID

def is_banned(uid):
    row = db("SELECT is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
    return bool(val(row, "is_banned")) if row else False

def ensure_user(uid):
    db("INSERT INTO users(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING", (uid,))
    commit()

def new_record(table, uid, message_ids, extra=None):
    extra = extra or {}
    if table == "buy_requests":
        sql = "INSERT INTO buy_requests(user_id,message_ids,link) VALUES(?,?,?)"
        params = (uid, message_ids, extra.get("link", ""))
    else:
        sql = f"INSERT INTO {table}(user_id,message_ids) VALUES(?,?)"
        params = (uid, message_ids)
    if DATABASE_URL:
        row = db(sql + " RETURNING id", params).fetchone()
        return val(row, "id")
    cur = db(sql, params)
    commit()
    return cur.lastrowid

def count(sql):
    return val(db("SELECT COUNT(*) AS n FROM " + sql).fetchone(), "n")

async def check_membership(uid, bot):
    missing = []
    for channel, link in CHANNELS:
        try:
            member = await bot.get_chat_member(channel, uid)
            if member.status in ("left", "kicked"):
                missing.append((channel, link))
        except Exception:
            missing.append((channel, link))
    return missing

def user_keyboard():
    return K([
        [B("درخواست واسطه گری", callback_data="mediator")],
        [B("واسطه گری رایگان", callback_data="free_mediator")],
        [B("ثبت آگهی", callback_data="post_ad")],
        [B("قیمت‌گذاری روی اکانت", callback_data="pricing")],
        [B("خرید اکانت", callback_data="buy_account")],
        [B("پرسیدن سوال", callback_data="ask_question")],
        [B("گزارش خرابی", callback_data="report")]
    ])

def admin_keyboard():
    return K([
        [B("آمار کلی ربات", callback_data="admin_stats")],
        [B("آگهی‌های ثبت شده", callback_data="admin_ads")],
        [B("درخواست قیمت‌گذاری", callback_data="admin_pricing")],
        [B("خرید اکانت", callback_data="admin_buy")],
        [B("سوال‌های پرسیده شده", callback_data="admin_questions")],
        [B("کاربران بن شده", callback_data="admin_bans")],
        [B("انتقال امتیاز", callback_data="admin_transfer")],
        [B("تنظیمات متون ربات", callback_data="admin_settings")],
        [B("ارسال پیام همگانی", callback_data="admin_broadcast")]
    ])

async def show_admin_panel(update, context):
    text = "🔧 پنل مدیریت\nیک گزینه را انتخاب کنید:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=admin_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=admin_keyboard())

async def show_user_menu(update, context):
    user = update.effective_user
    text = get_text("welcome", user.first_name)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=user_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=user_keyboard()
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    context.user_data.clear()

    if is_banned(uid):
        return await update.message.reply_text("🚫 شما از ربات بن شده‌اید.")

    is_new = not db(
        "SELECT user_id FROM users WHERE user_id=?",
        (uid,)
    ).fetchone()

    ensure_user(uid)

    if is_new and context.args and context.args[0].startswith("ref_"):
        # ادامه کد قبلی مربوط به دعوت دوستان را اینجا نگه دار
        pass
        try:
            inviter = int(context.args[0][4:])
            if inviter != uid and db("SELECT user_id FROM users WHERE user_id=?", (inviter,)).fetchone():
                cur = db("INSERT INTO referrals(invited_id,inviter_id) VALUES(?,?) ON CONFLICT(invited_id) DO NOTHING", (uid, inviter))
                if cur.rowcount:
                    db("UPDATE users SET ref_count=ref_count+1 WHERE user_id=?", (inviter,))
                    commit()
                    row = db("SELECT ref_count FROM users WHERE user_id=?", (inviter,)).fetchone()
                    n = val(row, "ref_count", 0)
                    try:
                        await context.bot.send_message(inviter, f"🎉 یک زیرمجموعه جدید!\nتعداد کل: {n}")
                        if n == 20:
                            await context.bot.send_message(ADMIN_ID, f"کاربر {inviter} به ۲۰ زیرمجموعه رسید.")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Referral: %s", e)

    if is_admin(uid):
        return await show_admin_panel(update, context)

    missing = await check_membership(uid, context.bot)
    if missing:
        buttons = [[B(f"عضویت در {ch}", url=link)] for ch, link in missing]
        buttons.append([B("عضو شدم", callback_data="check_join")])
        return await update.message.reply_text("برای استفاده ابتدا عضو کانال‌ها شوید:", reply_markup=K(buttons))

    await show_user_menu(update, context)

async def channel_post_handler(update, context):
    post = update.channel_post
    if not post or (post.chat.username or "").lower() != AD_CHANNEL_ID[1:].lower():
        return
    markup = K([[B("شیشه‌ای شود", callback_data=f"ch_glass_yes_{post.message_id}"),
                 B("لغو", callback_data=f"ch_glass_no_{post.message_id}")]])
    await context.bot.send_message(ADMIN_ID, "پیام جدید کانال ثبت شد. آن را دکمه‌دار کنم؟", reply_markup=markup)

async def mediator_handler(update, context):
    await update.callback_query.edit_message_text(
        get_text("mediator"),
        reply_markup=K([
            [B("تایید و ارسال به ادمین", callback_data="mediator_confirm")],
            [B("💳 پرداخت با استارز", callback_data="stars_menu")],
            [B("برگشت", callback_data="restart")]
        ]))

async def mediator_confirm(update, context):
    await update.callback_query.edit_message_text(
        get_text("mediator_confirm"),
        reply_markup=K([[B("برگشت", callback_data="restart")]]))

async def post_ad_handler(update, context):
    context.user_data.clear()
    context.user_data.update(state="ad_waiting", ad_messages=[], ad_text="")
    name = update.effective_user.first_name or "کاربر"
    await update.callback_query.edit_message_text(
        get_text("post_ad", name),
        reply_markup=K([[B("برگشت", callback_data="restart")]]))
    await context.bot.send_message(update.effective_user.id, AD_GUIDE.format(name=name))

async def pricing_handler(update, context):
    context.user_data.clear()
    context.user_data.update(state="pricing_waiting", pricing_messages=[], pricing_text="")
    await update.callback_query.edit_message_text(
        get_text("pricing", update.effective_user.first_name),
        reply_markup=K([[B("برگشت", callback_data="restart")]]))

async def buy_handler(update, context):
    context.user_data.clear()
    context.user_data.update(state="buy_waiting", buy_messages=[], buy_link="")
    await update.callback_query.edit_message_text(
        get_text("buy", update.effective_user.first_name),
        reply_markup=K([[B("برگشت", callback_data="restart")]]))

async def free_mediator_handler(update, context):
    uid = update.effective_user.id
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    row = db("SELECT ref_count,points FROM users WHERE user_id=?", (uid,)).fetchone()
    refs = val(row, "ref_count", 0) or 0
    points = val(row, "points", 1) or 0
    text = (
        f"برای واسطه‌گری رایگان زیرمجموعه بگیرید.\n\n"
        f"🔗 لینک اختصاصی:\n{link}\n\n"
        f"👥 زیرمجموعه‌ها: {refs}\n💎 امتیاز مدیریت: {points}\n\n"
        "معامله ۱۰۰ تا ۴۰۰ هزار: ۲۰ زیرمجموعه\n"
        "۴۰۰ تا ۹۰۰ هزار: ۳۰ زیرمجموعه\n"
        "۱ تا ۳ میلیون: ۵۰ زیرمجموعه\n"
        "۴ تا ۱۰ میلیون: ۱۰۰ زیرمجموعه\n"
        "بالای ۱۰ میلیون: ۲۵۰ زیرمجموعه"
    )
    await update.callback_query.edit_message_text(text, reply_markup=K([[B("برگشت", callback_data="restart")]]))

async def report_handler(update, context):
    context.user_data.clear()
    context.user_data["state"] = "report_waiting"
    await update.callback_query.edit_message_text("مشکل یا باگ را توضیح دهید:", reply_markup=K([[B("برگشت", callback_data="restart")]]))

async def ask_question_handler(update, context):
    context.user_data.clear()
    context.user_data["state"] = "question_waiting"
    await update.callback_query.edit_message_text("سوال خود را به صورت یک پیام متنی ارسال کنید:", reply_markup=K([[B("لغو", callback_data="restart")]]))

async def stars_menu(update, context):
    buttons = [
        [B("۱۰۰ تا ۴۰۰ هزار (۲۰ استارز)", callback_data="pay_stars_20")],
        [B("۴۰۰ تا ۹۰۰ هزار (۳۰ استارز)", callback_data="pay_stars_30")],
        [B("۱ تا ۳ میلیون (۵۰ استارز)", callback_data="pay_stars_50")],
        [B("۴ تا ۱۰ میلیون (۱۰۰ استارز)", callback_data="pay_stars_100")],
        [B("بالای ۱۰ میلیون (۲۵۰ استارز)", callback_data="pay_stars_250")],
        [B("برگشت", callback_data="mediator")]
    ]
    await update.callback_query.edit_message_text("💳 پرداخت استارزی واسطه‌گری:", reply_markup=K(buttons))

async def send_stars_invoice(update, context, amount):
    query = update.callback_query
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title="واسطه‌گری",
        description=f"پرداخت واسطه‌گری به مبلغ {amount} استارز",
        payload=f"stars_{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("واسطه‌گری", amount)]
    )

async def precheckout_callback(update, context):
    query = update.pre_checkout_query
    try:
        amount = int(query.invoice_payload.split("_")[1])
        valid = query.invoice_payload in ("stars_20", "stars_30", "stars_50", "stars_100", "stars_250") and query.total_amount == amount and query.currency == "XTR"
    except Exception:
        valid = False
    await query.answer(ok=valid, error_message=None if valid else "اطلاعات پرداخت معتبر نیست.")

async def admin_settings_menu(update, context):
    buttons = [[B(label, callback_data=f"edit_txt_{key}")] for key, label in [
        ("welcome", "متن خوش‌آمدگویی"), ("mediator", "متن واسطه‌گری"),
        ("mediator_confirm", "متن تایید واسطه"), ("post_ad", "متن ثبت آگهی"),
        ("pricing", "متن قیمت‌گذاری"), ("buy", "متن خرید اکانت")
    ]]
    buttons.append([B("برگشت", callback_data="admin_back")])
    await update.callback_query.edit_message_text("کدام متن را ویرایش می‌کنید؟", reply_markup=K(buttons))

async def start_edit_text(update, context, key):
    context.user_data.update(state="admin_editing_text", edit_text_key=key)
    await update.callback_query.edit_message_text(
        f"متن فعلی:\n\n{get_text(key, 'کاربر')}\n\nمتن جدید را ارسال کنید:",
        reply_markup=K([[B("لغو", callback_data="admin_settings")]]))

async def admin_transfer_start(update, context):
    context.user_data["state"] = "admin_transfer_id"
    await update.callback_query.edit_message_text("آیدی عددی کاربر را بفرستید:", reply_markup=K([[B("لغو", callback_data="admin_back")]]))

async def admin_broadcast_start(update, context):
    context.user_data.update(state="admin_broadcast_msg", broadcast_data={})
    await update.callback_query.edit_message_text("پیام همگانی را بفرستید (متن، عکس یا ویدیو):", reply_markup=K([[B("لغو", callback_data="admin_back")]]))

async def submit_ad(update, context):
    query = update.callback_query
    data = context.user_data
    text = data.get("ad_text", "").strip()
    photos = data.get("ad_photos", [])
    ids = data.get("ad_messages", [])

    if "آیدی فروشنده:" not in text and "آیدی فروشنده" not in text:
        return await query.edit_message_text("❌ فرم باید شامل آیدی فروشنده باشد.")
    if not 2 <= len(photos) <= 9:
        return await query.edit_message_text(f"❌ باید بین ۲ تا ۹ عکس ارسال کنید. عکس‌های فعلی: {len(photos)}")

    ad_id = new_record("ads", query.from_user.id, ",".join(map(str, ids + (["text"] if text else []))))
    admin_ids = []
    if text:
        m = await context.bot.send_message(ADMIN_ID, text)
        admin_ids.append(m.message_id)
    for mid in ids:
        try:
            m = await context.bot.forward_message(ADMIN_ID, query.from_user.id, mid)
            admin_ids.append(m.message_id)
        except Exception as e:
            logger.warning("Forward ad item failed: %s", e)

    db("UPDATE ads SET admin_msg_ids=? WHERE id=?", (",".join(map(str, admin_ids)), ad_id))
    commit()
    await context.bot.send_message(
        ADMIN_ID, f"📝 آگهی جدید #{ad_id}\nکاربر: {query.from_user.id}",
        reply_markup=K([
            [B("تایید و انتشار", callback_data=f"approve_ad_{ad_id}"), B("رد", callback_data=f"reject_ad_{ad_id}")],
            [B("ویرایش متن", callback_data=f"edit_ad_{ad_id}")],
            [B("بن کاربر", callback_data=f"ban_{query.from_user.id}")]
        ]))
    await query.edit_message_text("فرم و عکس‌ها دریافت شد ✅\nپس از بررسی نتیجه اطلاع داده می‌شود.")
    context.user_data.clear()

async def submit_pricing(update, context):
    query = update.callback_query
    data = context.user_data
    ids = data.get("pricing_messages", [])
    text = data.get("pricing_text", "").strip()
    if not ids and not text:
        return await query.edit_message_text("محتوایی دریافت نشد.")
    req_id = new_record("pricing_requests", query.from_user.id, ",".join(map(str, ids + (["text"] if text else []))))
    admin_ids = []
    if text:
        m = await context.bot.send_message(ADMIN_ID, text)
        admin_ids.append(m.message_id)
    for mid in ids:
        try:
            m = await context.bot.forward_message(ADMIN_ID, query.from_user.id, mid)
            admin_ids.append(m.message_id)
        except Exception:
            pass
    db("UPDATE pricing_requests SET admin_msg_ids=? WHERE id=?", (",".join(map(str, admin_ids)), req_id))
    commit()
    await context.bot.send_message(ADMIN_ID, f"💰 درخواست قیمت‌گذاری #{req_id}\nکاربر: {query.from_user.id}",
        reply_markup=K([[B("ارسال قیمت", callback_data=f"send_price_{req_id}"), B("رد", callback_data=f"reject_pricing_{req_id}")]]))
    await query.edit_message_text("اطلاعات شما دریافت شد ✅")
    context.user_data.clear()

async def submit_buy(update, context):
    query = update.callback_query
    data = context.user_data
    ids, link = data.get("buy_messages", []), data.get("buy_link", "")
    if not ids and not link:
        return await query.edit_message_text("لینک یا محتوایی دریافت نشد.")
    req_id = new_record("buy_requests", query.from_user.id, ",".join(map(str, ids)), {"link": link})
    admin_ids = []
    for mid in ids:
        try:
            m = await context.bot.forward_message(ADMIN_ID, query.from_user.id, mid)
            admin_ids.append(m.message_id)
        except Exception:
            pass
    db("UPDATE buy_requests SET admin_msg_ids=? WHERE id=?", (",".join(map(str, admin_ids)), req_id))
    commit()
    await context.bot.send_message(ADMIN_ID, f"🛒 درخواست خرید #{req_id}\nکاربر: {query.from_user.id}\nلینک: {link}",
        reply_markup=K([[B("ارسال پاسخ", callback_data=f"reply_buy_{req_id}")]]))
    await query.edit_message_text("درخواست خرید دریافت شد ✅")
    context.user_data.clear()
    async def ban_user_action(update, context, uid):
    db("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
    commit()
    for ch, _ in CHANNELS:
        try:
            await context.bot.ban_chat_member(ch, uid)
        except Exception:
            pass
    try:
        await context.bot.send_message(uid, "🚫 دسترسی شما به ربات محدود شد.")
    except Exception:
        pass
    await update.callback_query.edit_message_text(f"کاربر {uid} بن شد.")

async def unban_user_action(update, context, uid):
    db("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
    commit()
    for ch, _ in CHANNELS:
        try:
            await context.bot.unban_chat_member(ch, uid)
        except Exception:
            pass
    try:
        await context.bot.send_message(uid, "✅ محدودیت شما برداشته شد.")
    except Exception:
        pass
    await admin_show_bans(update, context)

async def admin_show_bans(update, context):
    rows = db("SELECT user_id FROM users WHERE is_banned=1").fetchall()
    if not rows:
        return await update.callback_query.edit_message_text("کاربر بن‌شده‌ای وجود ندارد.", reply_markup=K([[B("برگشت", callback_data="admin_back")]]))
    buttons = [[B(f"رفع بن {val(r, 'user_id')}", callback_data=f"unban_{val(r, 'user_id')}")] for r in rows]
    buttons.append([B("برگشت", callback_data="admin_back")])
    await update.callback_query.edit_message_text("🚫 کاربران بن‌شده:", reply_markup=K(buttons))

async def admin_show_stats(update, context):
    text = (
        "📊 آمار کلی ربات\n\n"
        f"👥 کاربران: {count('users')}\n"
        f"📝 آگهی‌ها: {count('ads')}\n"
        f"💰 درخواست قیمت‌گذاری: {count('pricing_requests')}\n"
        f"🛒 درخواست خرید: {count('buy_requests')}\n"
        f"❓ سوال‌ها: {count('questions')}\n"
        f"🚫 کاربران بن‌شده: {count('users WHERE is_banned=1')}"
    )
    await update.callback_query.edit_message_text(text, reply_markup=K([[B("برگشت", callback_data="admin_back")]]))

async def admin_list(update, table, title, action):
    rows = db(f"SELECT id,user_id,status FROM {table} ORDER BY id DESC LIMIT 30").fetchall()
    if not rows:
        return await update.callback_query.edit_message_text("موردی ثبت نشده است.", reply_markup=K([[B("برگشت", callback_data="admin_back")]]))
    text, buttons = title + "\n\n", []
    for r in rows:
        rid, uid, status = val(r, "id"), val(r, "user_id"), val(r, "status")
        icon = "⏳" if status == "pending" else ("✅" if status in ("approved", "answered") else "❌")
        text += f"{icon} #{rid} - کاربر {uid}\n"
        if status == "pending":
            buttons.append([B(f"مدیریت #{rid}", callback_data=f"{action}_{rid}")])
    buttons.append([B("برگشت", callback_data="admin_back")])
    await update.callback_query.edit_message_text(text, reply_markup=K(buttons))

async def admin_show_ads(update, context):
    await admin_list(update, "ads", "📋 آگهی‌ها", "manage_ad")

async def admin_show_pricing(update, context):
    await admin_list(update, "pricing_requests", "💰 درخواست‌های قیمت‌گذاری", "send_price")

async def admin_show_buy(update, context):
    await admin_list(update, "buy_requests", "🛒 درخواست‌های خرید", "reply_buy")

async def admin_show_questions(update, context):
    rows = db("SELECT id,user_id,question_text FROM questions WHERE status='pending' ORDER BY id").fetchall()
    if not rows:
        return await update.callback_query.edit_message_text("سوال بی‌پاسخی وجود ندارد.", reply_markup=K([[B("برگشت", callback_data="admin_back")]]))
    text, buttons = "❓ سوال‌های بی‌پاسخ:\n\n", []
    for r in rows:
        qid, uid, question = val(r, "id"), val(r, "user_id"), val(r, "question_text")
        text += f"#{qid} - کاربر {uid}\n{question}\n\n"
        buttons.append([B(f"پاسخ به #{qid}", callback_data=f"admin_answer_{qid}"), B("بن کاربر", callback_data=f"ban_{uid}")])
    buttons.append([B("برگشت", callback_data="admin_back")])
    await update.callback_query.edit_message_text(text, reply_markup=K(buttons))

async def approve_ad(update, context, ad_id):
    row = db("SELECT user_id,admin_msg_ids,status FROM ads WHERE id=?", (ad_id,)).fetchone()
    if not row or val(row, "status", 2) != "pending":
        return await update.callback_query.edit_message_text("این آگهی قبلاً بررسی شده یا وجود ندارد.")
    uid = val(row, "user_id")
    mids = val(row, "admin_msg_ids", 1) or ""
    sent = 0
    for mid in mids.split(","):
        if mid.isdigit():
            try:
                await context.bot.copy_message(AD_CHANNEL_ID, ADMIN_ID, int(mid))
                sent += 1
            except Exception as e:
                logger.warning("Publish failed: %s", e)
    if not sent:
        return await update.callback_query.edit_message_text("❌ انتشار انجام نشد؛ پیام‌های آگهی در دسترس نیستند.")
    db("UPDATE ads SET status='approved' WHERE id=?", (ad_id,))
    commit()
    try:
        await context.bot.send_message(uid, f"✅ آگهی #{ad_id} تایید و منتشر شد.")
    except Exception:
        pass
    await update.callback_query.edit_message_text(f"✅ آگهی #{ad_id} منتشر شد.")

async def reject_ad(update, context, ad_id):
    row = db("SELECT user_id,status FROM ads WHERE id=?", (ad_id,)).fetchone()
    if not row:
        return await update.callback_query.edit_message_text("آگهی پیدا نشد.")
    uid = val(row, "user_id")
    db("UPDATE ads SET status='rejected' WHERE id=?", (ad_id,))
    commit()
    try:
        await context.bot.send_message(uid, f"❌ آگهی #{ad_id} رد شد.")
    except Exception:
        pass
    await update.callback_query.edit_message_text("❌ آگهی رد شد.")

async def edit_ad_start(update, context, ad_id):
    context.user_data.update(state="admin_editing_ad", edit_ad_id=ad_id)
    await update.callback_query.edit_message_text("متن جدید آگهی را ارسال کنید:", reply_markup=K([[B("لغو", callback_data="admin_back")]]))

async def admin_manage_ad(update, context, ad_id):
    row = db("SELECT user_id,status FROM ads WHERE id=?", (ad_id,)).fetchone()
    if not row:
        return await update.callback_query.edit_message_text("آگهی پیدا نشد.")
    await update.callback_query.edit_message_text(
        f"آگهی #{ad_id} - کاربر {val(row, 'user_id')}",
        reply_markup=K([
            [B("تایید", callback_data=f"approve_ad_{ad_id}"), B("رد", callback_data=f"reject_ad_{ad_id}")],
            [B("ویرایش متن", callback_data=f"edit_ad_{ad_id}")],
            [B("برگشت", callback_data="admin_ads")]
        ]))

async def start_send_price(update, context, rid):
    row = db("SELECT user_id,status FROM pricing_requests WHERE id=?", (rid,)).fetchone()
    if not row:
        return await update.callback_query.edit_message_text("درخواست پیدا نشد.")
    context.user_data.update(state="admin_send_price", admin_send_price_for={"user_id": val(row, "user_id"), "id": rid})
    await update.callback_query.edit_message_text(f"قیمت را برای کاربر {val(row, 'user_id')} بنویسید:", reply_markup=K([[B("لغو", callback_data="admin_back")]]))

async def reject_pricing(update, context, rid):
    row = db("SELECT user_id FROM pricing_requests WHERE id=?", (rid,)).fetchone()
    if not row:
        return await update.callback_query.edit_message_text("درخواست پیدا نشد.")
    db("UPDATE pricing_requests SET status='rejected' WHERE id=?", (rid,))
    commit()
    try:
        await context.bot.send_message(val(row, "user_id"), f"درخواست قیمت‌گذاری #{rid} رد شد.")
    except Exception:
        pass
    await update.callback_query.edit_message_text("درخواست رد شد.")

async def start_reply_buy(update, context, rid):
    row = db("SELECT user_id FROM buy_requests WHERE id=?", (rid,)).fetchone()
    if not row:
        return await update.callback_query.edit_message_text("درخواست پیدا نشد.")
    context.user_data.update(state="admin_reply_buy", admin_reply_buy_for={"user_id": val(row, "user_id"), "id": rid})
    await update.callback_query.edit_message_text(f"پاسخ را برای کاربر {val(row, 'user_id')} بفرستید:", reply_markup=K([[B("لغو", callback_data="admin_back")]]))

async def start_answering_question(update, context, qid):
    row = db("SELECT user_id,question_text FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        return await update.callback_query.edit_message_text("سوال پیدا نشد.")
    context.user_data.update(state="admin_answering_q", admin_answer_q={"user_id": val(row, "user_id"), "id": qid})
    await update.callback_query.edit_message_text(f"سوال:\n{val(row, 'question_text')}\n\nپاسخ را بنویسید:", reply_markup=K([[B("لغو", callback_data="admin_back")]]))

async def ask_glass_button(update, context, msg):
    context.user_data["broadcast_data"] = {"msg_id": msg.message_id}
    context.user_data["state"] = "admin_broadcast_glass"
    await msg.reply_text("پیام دکمه‌دار باشد؟", reply_markup=K([[B("بله", callback_data="glass_yes"), B("خیر", callback_data="glass_no")]]))

async def do_broadcast(context, msg_id, markup=None):
    rows = db("SELECT user_id FROM users WHERE is_banned=0").fetchall()
    success = failed = 0
    for row in rows:
        uid = val(row, "user_id")
        try:
            await context.bot.copy_message(uid, ADMIN_ID, msg_id, reply_markup=markup)
            success += 1
        except Exception:
            failed += 1
    return success, failed
    async def button_handler(update, context):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id

    admin_prefixes = (
        "admin_", "approve_ad_", "reject_ad_", "send_price_",
        "reject_pricing_", "reply_buy_", "manage_ad_", "ban_",
        "unban_", "edit_ad_", "edit_txt_", "glass_", "ch_glass_"
    )
    if data.startswith(admin_prefixes) and not is_admin(uid):
        return await query.answer("دسترسی ندارید.", show_alert=True)

    await query.answer()

    if data == "check_join":
        if await check_membership(uid, context.bot):
            return await query.answer("هنوز عضو کانال‌ها نشدید.", show_alert=True)
        return await show_user_menu(update, context)

    if data == "restart":
        context.user_data.clear()
        return await (show_admin_panel(update, context) if is_admin(uid) else show_user_menu(update, context))

    routes = {
        "mediator": mediator_handler,
        "mediator_confirm": mediator_confirm,
        "post_ad": post_ad_handler,
        "pricing": pricing_handler,
        "buy_account": buy_handler,
        "free_mediator": free_mediator_handler,
        "report": report_handler,
        "ask_question": ask_question_handler,
        "stars_menu": stars_menu,
        "submit_ad": submit_ad,
        "submit_pricing": submit_pricing,
        "submit_buy": submit_buy,
        "admin_back": show_admin_panel,
        "admin_stats": admin_show_stats,
        "admin_ads": admin_show_ads,
        "admin_pricing": admin_show_pricing,
        "admin_buy": admin_show_buy,
        "admin_questions": admin_show_questions,
        "admin_bans": admin_show_bans,
        "admin_settings": admin_settings_menu,
        "admin_transfer": admin_transfer_start,
        "admin_broadcast": admin_broadcast_start
    }
    if data in routes:
        return await routes[data](update, context)

    if data.startswith("pay_stars_"):
        return await send_stars_invoice(update, context, int(data.split("_")[-1]))
    if data.startswith("edit_txt_"):
        return await start_edit_text(update, context, data[9:])
    if data.startswith("edit_ad_"):
        return await edit_ad_start(update, context, int(data.split("_")[-1]))
    if data.startswith("ban_"):
        return await ban_user_action(update, context, int(data.split("_")[-1]))
    if data.startswith("unban_"):
        return await unban_user_action(update, context, int(data.split("_")[-1]))
    if data.startswith("approve_ad_"):
        return await approve_ad(update, context, int(data.split("_")[-1]))
    if data.startswith("reject_ad_"):
        return await reject_ad(update, context, int(data.split("_")[-1]))
    if data.startswith("manage_ad_"):
        return await admin_manage_ad(update, context, int(data.split("_")[-1]))
    if data.startswith("send_price_"):
        return await start_send_price(update, context, int(data.split("_")[-1]))
    if data.startswith("reject_pricing_"):
        return await reject_pricing(update, context, int(data.split("_")[-1]))
    if data.startswith("reply_buy_"):
        return await start_reply_buy(update, context, int(data.split("_")[-1]))
    if data.startswith("admin_answer_"):
        return await start_answering_question(update, context, int(data.split("_")[-1]))

    if data == "glass_yes":
        context.user_data["state"] = "admin_broadcast_btn_txt"
        return await query.edit_message_text("متن دکمه را بفرستید:")
    if data == "glass_no":
        mid = context.user_data["broadcast_data"]["msg_id"]
        await query.edit_message_text("در حال ارسال...")
        ok, fail = await do_broadcast(context, mid)
        context.user_data.clear()
        return await context.bot.send_message(uid, f"ارسال تمام شد.\nموفق: {ok}\nناموفق: {fail}")

    if data.startswith("ch_glass_no_"):
        return await query.edit_message_text("پیام بدون تغییر ماند.")
    if data.startswith("ch_glass_yes_"):
        context.user_data.update(state="admin_ch_glass_txt", ch_msg_id=int(data.split("_")[-1]))
        return await query.edit_message_text("متن دکمه را بفرستید:")


async def message_handler(update, context):
    msg = update.message
    if not msg:
        return
    uid = update.effective_user.id
    name = update.effective_user.first_name or "کاربر"

    if msg.successful_payment:
        payment = msg.successful_payment
        await context.bot.send_message(
            STARS_ADMIN_ID,
            f"💰 پرداخت جدید\nکاربر: {name}\nآیدی: {uid}\n"
            f"استارز: {payment.total_amount}\nشناسه: {payment.telegram_payment_charge_id}"
        )
        return await msg.reply_text("✅ پرداخت شما با موفقیت انجام شد.")

    if is_banned(uid):
        return await msg.reply_text("🚫 شما از ربات بن شده‌اید.")

    state = context.user_data.get("state")
    if not state:
        return

    if state.startswith("admin_") and not is_admin(uid):
        return

    if state == "admin_editing_text":
        set_text(context.user_data["edit_text_key"], msg.text or "")
        context.user_data.clear()
        await msg.reply_text("✅ متن ذخیره شد.")
        return await show_admin_panel(update, context)

    if state == "admin_editing_ad":
        ad_id = context.user_data["edit_ad_id"]
        old = db("SELECT admin_msg_ids FROM ads WHERE id=?", (ad_id,)).fetchone()
        if not old:
            context.user_data.clear()
            return await msg.reply_text("آگهی پیدا نشد.")
        sent = await context.bot.send_message(ADMIN_ID, msg.text or " ")
        mids = val(old, "admin_msg_ids", 0) or ""
        mids = ",".join(x for x in [mids, str(sent.message_id)] if x)
        db("UPDATE ads SET admin_msg_ids=? WHERE id=?", (mids, ad_id))
        db("UPDATE ads SET message_ids=CASE WHEN message_ids='' THEN 'text' ELSE message_ids || ',text' END WHERE id=?", (ad_id,))
        commit()
        context.user_data.clear()
        return await msg.reply_text("✅ متن جدید به آگهی اضافه شد. پیام قبلی حذف نمی‌شود؛ هنگام تایید، هر دو متن منتشر خواهند شد.")

    if state == "admin_transfer_id":
        try:
            target = int(msg.text)
            if not db("SELECT user_id FROM users WHERE user_id=?", (target,)).fetchone():
                return await msg.reply_text("این کاربر هنوز ربات را استارت نکرده است.")
            context.user_data.update(state="admin_transfer_points", target_id=target)
            return await msg.reply_text("تعداد امتیاز را وارد کنید:")
        except Exception:
            return await msg.reply_text("آیدی عددی معتبر وارد کنید.")

    if state == "admin_transfer_points":
        try:
            points = int(msg.text)
            if points <= 0:
                raise ValueError()
            target = context.user_data["target_id"]
            db("UPDATE users SET points=points+? WHERE user_id=?", (points, target))
            commit()
            try:
                await context.bot.send_message(target, f"🎁 {points} امتیاز از مدیریت دریافت کردید.")
            except Exception:
                pass
            context.user_data.clear()
            return await msg.reply_text("✅ امتیاز ثبت شد.")
        except Exception:
            return await msg.reply_text("عدد مثبت وارد کنید.")

    if state == "admin_send_price":
        info = context.user_data["admin_send_price_for"]
        await context.bot.send_message(info["user_id"], f"💰 قیمت تقریبی اکانت:\n\n{msg.text}\n\n@Vasete_armin_azizi")
        db("UPDATE pricing_requests SET status='answered' WHERE id=?", (info["id"],))
        commit()
        context.user_data.clear()
        return await msg.reply_text("✅ قیمت ارسال شد.")

    if state == "admin_reply_buy":
        info = context.user_data["admin_reply_buy_for"]
        await context.bot.copy_message(info["user_id"], uid, msg.message_id)
        db("UPDATE buy_requests SET status='answered' WHERE id=?", (info["id"],))
        commit()
        context.user_data.clear()
        return await msg.reply_text("✅ پاسخ ارسال شد.")

    if state == "admin_answering_q":
        info = context.user_data["admin_answer_q"]
        await context.bot.send_message(info["user_id"], f"📬 پاسخ سوال شما:\n\n{msg.text}")
        db("UPDATE questions SET status='answered',answer_text=? WHERE id=?", (msg.text, info["id"]))
        commit()
        context.user_data.clear()
        return await msg.reply_text("✅ پاسخ ارسال شد.")

    if state == "admin_broadcast_msg":
        context.user_data["broadcast_data"] = {"msg_id": msg.message_id}
        return await ask_glass_button(update, context, msg)

    if state == "admin_broadcast_btn_txt":
        context.user_data["broadcast_data"]["btn_txt"] = msg.text
        context.user_data["state"] = "admin_broadcast_btn_url"
        return await msg.reply_text("لینک دکمه را بفرستید:")

    if state == "admin_broadcast_btn_url":
        url = msg.text.strip()
        if not url.startswith(("https://", "http://")):
            url = "https://" + url
        if not url.startswith("https://"):
            return await msg.reply_text("لینک معتبر وارد کنید.")
        info = context.user_data["broadcast_data"]
        markup = K([[B(info["btn_txt"], url=url)]])
        ok, fail = await do_broadcast(context, info["msg_id"], markup)
        context.user_data.clear()
        return await msg.reply_text(f"✅ ارسال تمام شد.\nموفق: {ok}\nناموفق: {fail}")

    if state == "admin_ch_glass_txt":
        context.user_data["ch_btn_txt"] = msg.text
        context.user_data["state"] = "admin_ch_glass_url"
        return await msg.reply_text("لینک دکمه را بفرستید:")

    if state == "admin_ch_glass_url":
        url = msg.text.strip()
        if not url.startswith(("https://", "http://")):
            url = "https://" + url
        try:
            markup = K([[B(context.user_data["ch_btn_txt"], url=url)]])
            await context.bot.edit_message_reply_markup(AD_CHANNEL_ID, context.user_data["ch_msg_id"], reply_markup=markup)
            await msg.reply_text("✅ دکمه به پیام کانال اضافه شد.")
        except Exception as e:
            await msg.reply_text(f"خطا: {e}")
        context.user_data.clear()
        return

    if not is_admin(uid) and await check_membership(uid, context.bot):
        buttons = [[B(f"عضویت در {ch}", url=link)] for ch, link in CHANNELS]
        buttons.append([B("عضو شدم", callback_data="check_join")])
        return await msg.reply_text("ابتدا عضو کانال‌ها شوید:", reply_markup=K(buttons))

    if state == "question_waiting":
        if not msg.text:
            return await msg.reply_text("لطفاً سوال را متنی ارسال کنید.")
        db("INSERT INTO questions(user_id,question_text) VALUES(?,?)", (uid, msg.text))
        commit()
        await msg.reply_text("✅ سوال شما ثبت شد.")
        await context.bot.send_message(ADMIN_ID, f"❓ سوال از کاربر {uid}:\n\n{msg.text}",
            reply_markup=K([[B("بن کاربر", callback_data=f"ban_{uid}")]]))
        context.user_data.clear()
        return

    if state == "report_waiting":
        await context.bot.forward_message(ADMIN_ID, uid, msg.message_id)
        await msg.reply_text("گزارش شما ارسال شد ✅")
        context.user_data.clear()
        return

    if state == "ad_waiting":
        if msg.text:
            context.user_data["ad_text"] = (context.user_data.get("ad_text", "") + "\n" + msg.text).strip()
        elif msg.photo:
            context.user_data["ad_messages"].append(msg.message_id)
            context.user_data.setdefault("ad_photos", []).append(msg.message_id)
        else:
            return await msg.reply_text("برای آگهی فقط فرم متنی و عکس ارسال کنید.")
        if not context.user_data.get("prompted"):
            context.user_data["prompted"] = True
            await msg.reply_text("📥 دریافت شد. بعد از ارسال فرم و عکس‌ها، دکمه پایان را بزنید:",
                reply_markup=K([[B("پایان و ارسال", callback_data="submit_ad")]]))
        return

    if state == "pricing_waiting":
        if msg.text:
            context.user_data["pricing_text"] = (context.user_data.get("pricing_text", "") + "\n" + msg.text).strip()
        elif msg.photo or msg.document or msg.video:
            context.user_data["pricing_messages"].append(msg.message_id)
        else:
            return
        if not context.user_data.get("prompted"):
            context.user_data["prompted"] = True
            await msg.reply_text("📥 دریافت شد:", reply_markup=K([[B("پایان و ارسال", callback_data="submit_pricing")]]))
        return

    if state == "buy_waiting":
        if msg.text:
            context.user_data["buy_link"] = msg.text
        elif msg.photo or msg.document or msg.video:
            context.user_data["buy_messages"].append(msg.message_id)
        else:
            return
        if not context.user_data.get("prompted"):
            context.user_data["prompted"] = True
            await msg.reply_text("📥 دریافت شد:", reply_markup=K([[B("ارسال درخواست", callback_data="submit_buy")]]))
        return


app = FastAPI()
bot_app = Application.builder().token(BOT_TOKEN).updater(None).build()

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
bot_app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post_handler))
bot_app.add_handler(CallbackQueryHandler(button_handler))
bot_app.add_handler(MessageHandler(
    (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.SUCCESSFUL_PAYMENT) & ~filters.COMMAND,
    message_handler
))

@app.on_event("startup")
async def on_startup():
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.bot.set_my_commands([BotCommand("start", "شروع مجدد ربات")])
    await bot_app.bot.set_webhook(
        f"{RENDER_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES
    )
    logger.info("Bot webhook configured: %s%s", RENDER_URL, WEBHOOK_PATH)

@app.on_event("shutdown")
async def on_shutdown():
    await bot_app.bot.delete_webhook()
    await bot_app.stop()
    await bot_app.shutdown()
    conn.close()

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.exception("Webhook error: %s", e)
        return Response(status_code=500)

@app.get("/")
async def root():
    return {"status": "Bot is running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
