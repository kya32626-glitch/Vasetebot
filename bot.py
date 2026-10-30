import os, logging, sqlite3
from fastapi import FastAPI, Request, Response
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, PreCheckoutQueryHandler, filters, ContextTypes
from PIL import Image, ImageDraw, ImageFont, ImageOps
import arabic_reshaper
from bidi.algorithm import get_display
import requests

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_ID = 8396752402
AD_CHANNEL_ID = "@Vasetearminazizi"
STARS_ADMIN_IDS = [7281917579, 8396752402] 
CHANNELS = [("@Vasetearminazizi", "https://t.me/Vasetearminazizi"), ("@etemadearminazizi", "https://t.me/etemadearminazizi")]

# لینک عکس قالبی که فرستادی
TEMPLATE_URL = "https://i.imgur.com/OdLgm7J.jpeg"
FONT_URL = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf/Vazirmatn-Bold.ttf"

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import DictCursor
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = True
    c = conn.cursor(cursor_factory=DictCursor)
    def q(query): return query.replace("?", "%s")
else:
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    c = conn.cursor()
    def q(query): return query

c.execute(q('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, is_banned INT DEFAULT 0, ref_count INT DEFAULT 0, points INT DEFAULT 0)'''))
c.execute(q('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)'''))
c.execute(q('''CREATE TABLE IF NOT EXISTS referrals (invited_id BIGINT PRIMARY KEY, inviter_id BIGINT)'''))
c.execute(q('''CREATE TABLE IF NOT EXISTS ads (id SERIAL PRIMARY KEY, user_id BIGINT, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
c.execute(q('''CREATE TABLE IF NOT EXISTS pricing_requests (id SERIAL PRIMARY KEY, user_id BIGINT, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
c.execute(q('''CREATE TABLE IF NOT EXISTS buy_requests (id SERIAL PRIMARY KEY, user_id BIGINT, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', link TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
c.execute(q('''CREATE TABLE IF NOT EXISTS questions (id SERIAL PRIMARY KEY, user_id BIGINT, question_text TEXT, answer_text TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
if not DATABASE_URL: conn.commit()

try:
    c.execute(q("SELECT points FROM users LIMIT 1"))
except Exception:
    if DATABASE_URL: conn.rollback()
    c.execute(q("ALTER TABLE users ADD COLUMN points INT DEFAULT 0"))
    if not DATABASE_URL: conn.commit()

DEFAULT_TEXTS = {
    "welcome": "این تنها ربات پاسخگویی واسطه گری آرمین عزیزی است\nآیدی ادمین واسطه: @Vasete_armin_azizi\n\nسلام %name% عزیز!",
    "mediator": "قیمت های واسطه گری به این صورت است:\n\nمعامله زیر 50 هزار : رایگان\n━━━━━━━━━━━━━━━━━\nمعامله 50 هزار تا 100 هزار: رایگان\n━━━━━━━━━━━━━━━━━\nمعامله 100 تا 300 : نفری ۱۰ هزار\n━━━━━━━━━━━━━━━━━\nمعامله 400 تا 900 هزار: نفری ۵۰ هزار\n━━━━━━━━━━━━━━━━━\nمعامله 1500 تا 3 میل : نفری 100 هزار\n━━━━━━━━━━━━━━━━━\nمعامله ۴ میل تا ۱۰ میل : نفری 350 هزار\n━━━━━━━━━━━━━━━━━\nمعامله های بالای 10 میل: نفری ۵۰۰ هزار\n\nاگر با قیمت ها اوکی بودید گزینه تایید رو بزنید.\nهمچنین شما میتوانید از طریق پرداخت استارزی اقدام کنید.",
    "mediator_confirm": "لطفاً اطلاعات زیر را به ایدی زیر ارسال نمایید:\n\n@Vasete_armin_azizi\n\n1_ آیدی شما و طرف مقابل\n2_ فرم اگهی اکانت یا عکس ها\n3_ ارزش اکانت شما\n\n⚠️ توجه داشته باشید تایید دو مرحله اکانت کالاف دیوتی الزامی است.\n\n⚠️ معامله فقط توسط همین آیدی بالا انجام میشود و ربات واسطه گری نمیکند.",
    "post_ad": "📋 فرم ثبت اگهی:\n\nنوع بازی🎮:\nـــــــــــــــــــــــــــــــــــ\n\nسیو ها📥:\nـــــــــــــــــــــــــــــــــ\n\nایا قابل چنج هست:\nتعداد سیپی🪙:\nتعداد گان متیک 🟥:\nتعداد گان لجند 🟨:\nتعداد بتل پس:\nتوضیحات فروشنده:\nUid:\nقیمت:\nآیدی فروشنده:\n\nجهت خرید اکانت اگهی کردن اکانت و قیمت گزاری و درخاست واسطه به بات مراجعه کنید:\n@Vasetearminazizibot\n\nجهت ارتباط با ادمین و واسطه گری اکانت:\n@Vasete_armin_azizi\n\nچنلمون:\nhttps://t.me/Vasetearminazizi\n\nاعتماد:\nhttps://t.me/etemadearminazizi\n\nاطلاعات اکانتتونو در فرم بالا پر کنید و سپس ارسال کنید\n\n❗️ اگر اکانت شما گزینه های زیر رو نداشته باشه آگهی نمیشه:\n1_ آیدی فروشنده الزامیس\n2_ عکس حد اقل 2 و حد اکثر 9 تا\n\nفرم را همراه عکس ها ارسال کنید و پیام اضافه نفرستید.\nممنون از شما %name% ❤️",
    "pricing": "برای قیمت گزاری اکانت اطلاعات زیر را ارسال نمایید:\n\n• عکس های اکانت\n• ایتم ها\n• وضعیت سیو ها\n• سیپی منفی دارد / ندارد\n\nلطفا از ارسال پیام های دیگر خودداری نمایید.\nپس از ارسال اطلاعات نهایتا تا یک الی دو ساعت قیمت تقریبی اکانت برای شما ارسال میشود.",
    "buy": "اکانتی که قصد خرید ان را دارید لینک پیام آن را در چنل آگهی و دارید و بفرستید.\nدقت کنید اگهی فقط باید در چنل خرید فروش ما آگهی شده باشد.\n\nاز ارسال پیام های دیگر خودداری کنید.\nپس از ارسال آگهی ان اکانت استعلام گرفته میشود و سپس به شما اطلاع داده میشود.\n\nبا تشکر از همراهی شما."
}

def get_text(key, user_name=""):
    c.execute(q("SELECT value FROM settings WHERE key=?"), (key,))
    row = c.fetchone()
    txt = (row['value'] if DATABASE_URL else row[0]) if row else DEFAULT_TEXTS.get(key, "")
    return txt.replace("%name%", user_name)

def set_text(key, value):
    c.execute(q("DELETE FROM settings WHERE key=?"), (key,))
    c.execute(q("INSERT INTO settings (key, value) VALUES (?, ?)"), (key, value))
    if not DATABASE_URL: conn.commit()

def is_admin(user_id): return user_id == ADMIN_ID
def is_banned(user_id):
    c.execute(q("SELECT is_banned FROM users WHERE user_id=?"), (user_id,))
    row = c.fetchone()
    return row and (row['is_banned'] if DATABASE_URL else row[0]) == 1

def extract_clean_form(text):
    if not text: return text
    markers = ["اطلاعات اکانتتونو", "❗️ اگر اکانت شما", "فرم را همراه عکس ها", "ممنون از شما"]
    for marker in markers:
        if marker in text: text = text.split(marker)[0].strip()
    return text

def get_count(query_str):
    c.execute(q(f"SELECT COUNT(*) as count FROM {query_str}"))
    row = c.fetchone()
    return row['count'] if DATABASE_URL else row[0]

async def check_membership(user_id, bot):
    not_joined = []
    for ch, link in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in ('left', 'kicked'): not_joined.append((ch, link))
        except: pass
    return not_joined

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("درخواست واسطه گری", callback_data="mediator", style="primary")], 
        [InlineKeyboardButton("واسطه گری رایگان", callback_data="free_mediator", style="primary")], 
        [InlineKeyboardButton("ثبت اگهی", callback_data="post_ad", style="primary")], 
        [InlineKeyboardButton("🖼 ساخت تصویر آگهی", callback_data="create_ad_img", style="success")],
        [InlineKeyboardButton("قیمت گزاری روی اکانت", callback_data="pricing", style="primary")], 
        [InlineKeyboardButton("خرید اکانت", callback_data="buy_account", style="primary")], 
        [InlineKeyboardButton("پرسیدن سوال", callback_data="ask_question", style="primary")], 
        [InlineKeyboardButton("گزارش خرابی", callback_data="report", style="danger")]
    ])

def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("آمار کلی ربات", callback_data="admin_stats", style="primary")],
        [InlineKeyboardButton("آگهی های ثبت شده", callback_data="admin_ads", style="primary")],
        [InlineKeyboardButton("درخواست قیمت گزاری", callback_data="admin_pricing", style="primary")],
        [InlineKeyboardButton("خرید اکانت", callback_data="admin_buy", style="primary")],
        [InlineKeyboardButton("سوال های پرسیده شده", callback_data="admin_questions", style="primary")],
        [InlineKeyboardButton("کاربران بن شده", callback_data="admin_bans", style="danger")],
        [InlineKeyboardButton("انتقال امتیاز", callback_data="admin_transfer", style="success")],
        [InlineKeyboardButton("تنظیمات متون ربات", callback_data="admin_settings", style="primary")],
        [InlineKeyboardButton("ارسال پیام همگانی", callback_data="admin_broadcast", style="success")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    context.user_data.clear()
    if is_banned(user_id): return await update.message.reply_text("🚫 شما از ربات بن شده اید.")
    
    c.execute(q("SELECT user_id FROM users WHERE user_id=?"), (user_id,))
    is_new = not c.fetchone()
    if is_new:
        c.execute(q("INSERT INTO users (user_id) VALUES (?)"), (user_id,))
        if not DATABASE_URL: conn.commit()
        if context.args and context.args[0].startswith("ref_"):
            try:
                inviter_id = int(context.args[0].replace("ref_", ""))
                if inviter_id != user_id:
                    c.execute(q("SELECT user_id FROM users WHERE user_id=?"), (inviter_id,))
                    if c.fetchone():
                        c.execute(q("INSERT INTO referrals (invited_id, inviter_id) VALUES (?, ?)"), (user_id, inviter_id))
                        c.execute(q("UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?"), (inviter_id,))
                        if not DATABASE_URL: conn.commit()
                        c.execute(q("SELECT ref_count FROM users WHERE user_id=?"), (inviter_id,))
                        row = c.fetchone()
                        count = row['ref_count'] if DATABASE_URL else row[0]
                        try:
                            await context.bot.send_message(inviter_id, f"🎉 یک کاربر جدید با لینک شما وارد ربات شد!\n👥 تعداد کل زیرمجموعه‌های شما: {count}")
                            if count == 20: await context.bot.send_message(ADMIN_ID, f"⚠️ کاربر {inviter_id} به ۲۰ زیرمجموعه رسید!")
                        except: pass
            except Exception as e: logger.error(f"Referral error: {e}")
                
    if is_admin(user_id): return await show_admin_panel(update, context)
    not_joined = await check_membership(user_id, context.bot)
    if not_joined:
        buttons = [[InlineKeyboardButton(f"عضویت در {ch}", url=link, style="primary")] for ch, link in not_joined]
        buttons.append([InlineKeyboardButton("عضو شدم", callback_data="check_join", style="success")])
        return await update.message.reply_text("برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:", reply_markup=InlineKeyboardMarkup(buttons))
    await update.message.reply_text(get_text("welcome", user_name), reply_markup=main_menu_keyboard())

async def show_admin_panel(update, context):
    text = "🔧 پنل مدیریت\nیک گزینه را انتخاب کنید:"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=admin_menu_keyboard())
    else: await update.message.reply_text(text, reply_markup=admin_menu_keyboard())

async def show_user_menu(update, context):
    user_name = update.effective_user.first_name if not update.callback_query else update.callback_query.from_user.first_name
    if update.callback_query: await update.callback_query.edit_message_text(get_text("welcome", user_name), reply_markup=main_menu_keyboard())
    else: await update.message.reply_text(get_text("welcome", user_name), reply_markup=main_menu_keyboard())

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post
    if not post: return
    if post.chat.username and post.chat.username.lower() != AD_CHANNEL_ID.replace('@', '').lower(): return
        
    msg_id = post.message_id
    text = f"📢 **پیام جدید در کانال ثبت شد.**\n\nآیا می‌خواهید این پیام به یک پیام شیشه‌ای (دارای دکمه) تبدیل شود؟"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("بله، شیشه ای شود", callback_data=f"ch_glass_yes_{msg_id}", style="success"), InlineKeyboardButton("خیر", callback_data=f"ch_glass_no_{msg_id}", style="danger")]])
    try: await context.bot.send_message(ADMIN_ID, text, reply_markup=markup)
    except Exception as e: logger.error(f"Could not send channel post prompt: {e}")

async def stars_menu(update, context):
    text = "💳 **پرداخت استارزی واسطه گری**\n\nلطفاً یکی از معامله‌های زیر را برای پرداخت انتخاب کنید:\n"
    buttons = [
        [InlineKeyboardButton("معامله 100 تا 400 هزار (20 استارز)", callback_data="pay_stars_20", style="primary")],
        [InlineKeyboardButton("معامله 400 تا 900 هزار (30 استارز)", callback_data="pay_stars_30", style="primary")],
        [InlineKeyboardButton("معامله 1 تا 3 میلیون (50 استارز)", callback_data="pay_stars_50", style="primary")],
        [InlineKeyboardButton("معامله 4 تا 10 میلیون (100 استارز)", callback_data="pay_stars_100", style="primary")],
        [InlineKeyboardButton("معامله بالای 10 میلیون (250 استارز)", callback_data="pay_stars_250", style="primary")],
        [InlineKeyboardButton("برگشت", callback_data="mediator", style="danger")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')

async def send_stars_invoice(update, context, stars_amount):
    query = update.callback_query
    await query.answer()
    title = "واسطه گری رایگان"
    description = f"پرداخت برای معامله به ارزش {stars_amount} استارز"
    payload = f"stars_{stars_amount}"
    prices = [LabeledPrice("واسطه گری", stars_amount)]
    await context.bot.send_invoice(chat_id=query.from_user.id, title=title, description=description, payload=payload, provider_token="", currency="XTR", prices=prices)

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("stars_"): await query.answer(ok=True)
    else: await query.answer(ok=False, error_message="مشکلی پیش آمده است.")

QUESTIONS = [
    ("mythic_skin", "تعداد اسکین های متیک:"),
    ("mythic_gun", "تعداد گان های متیک:"),
    ("gold", "تعداد گلد:"),
    ("uid", "UID اکانت:"),
    ("diamond", "تعداد دایموند:"),
    ("legend_gun", "تعداد گان های لجند:"),
    ("legend_skin", "تعداد اسکین های لجند:"),
    ("cp", "سیپی:"),
    ("price", "قیمت:")
]

async def create_ad_img_start(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'img_gen_photos'
    context.user_data['img_photos'] = []
    await update.callback_query.edit_message_text(
        "📸 لطفاً **عکس‌های اکانت** خود را یکی یکی ارسال کنید.\nپس از ارسال تمام عکس‌ها، روی دکمه «اتمام عکس‌ها» بزنید.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]),
        parse_mode='Markdown'
    )

async def process_photos(update, context, msg):
    context.user_data['img_photos'].append(msg.photo[-1].file_id)
    if len(context.user_data['img_photos']) == 1:
        await msg.reply_text(
            "عکس دریافت شد. می‌توانید عکس‌های بیشتری بفرستید یا برای ادامه روی دکمه زیر بزنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("اتمام عکس‌ها و ادامه", callback_data="img_photos_done", style="success")]])
        )
    else:
        try: await context.bot.edit_message_reply_markup(chat_id=msg.chat_id, message_id=msg.message_id - 1, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"اتمام {len(context.user_data['img_photos'])} عکس و ادامه", callback_data="img_photos_done", style="success")]]))
        except: pass

async def img_photos_done(update, context):
    context.user_data['img_data'] = {}
    context.user_data['img_q_index'] = 0
    context.user_data['state'] = 'img_gen_questions'
    q_key, q_text = QUESTIONS[0]
    await update.callback_query.edit_message_text(f"سوال ۱ از {len(QUESTIONS)}:\n\n{q_text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="restart", style="danger")]]))

async def generate_ad_image(update, context):
    user_data = context.user_data['img_data']
    photo_id = context.user_data['img_photos'][0]
    msg = await update.message.reply_text("⏳ در حال ساخت تصویر آگهی... لطفاً صبر کنید.")
    
    try:
        # دانلود خودکار فونت و عکس قالب
        if not os.path.exists("font.ttf"):
            try:
                r = requests.get(FONT_URL)
                with open("font.ttf", "wb") as f: f.write(r.content)
            except Exception as e: logger.error(f"Font download failed: {e}")
                
        if not os.path.exists("template.jpg"):
            try:
                r = requests.get(TEMPLATE_URL)
                with open("template.jpg", "wb") as f: f.write(r.content)
            except Exception as e: logger.error(f"Template download failed: {e}")

        file = await context.bot.get_file(photo_id)
        await file.download_to_drive("user_photo.jpg")
        user_img = Image.open("user_photo.jpg")
        
        template = Image.open("template.jpg").convert("RGBA")
        draw = ImageDraw.Draw(template)
        
        target_width, target_height = 850, 980
        user_img = ImageOps.fit(user_img, (target_width, target_height), method=Image.Resampling.LANCZOS)
        template.paste(user_img, (20, 20))
        
        try: font = ImageFont.truetype("font.ttf", 38)
        except: font = ImageFont.load_default()
        
        positions = [
            (1350, 210), (1350, 282), (1350, 355), (1350, 428), (1350, 500),
            (1350, 570), (1350, 642), (1350, 712), (1350, 845)
        ]
        
        for i, (key, _) in enumerate(QUESTIONS):
            val = user_data.get(key, "")
            reshaped_text = arabic_reshaper.reshape(val)
            bidi_text = get_display(reshaped_text)
            draw.text(positions[i], bidi_text, font=font, fill=(255, 215, 0), anchor="ra")
            
        template.convert("RGB").save("final_ad.jpg", quality=95)
        
        with open("final_ad.jpg", "rb") as f:
            await msg.reply_photo(photo=f, caption="✅ تصویر آگهی شما با موفقیت ساخته شد!")
            
        os.remove("user_photo.jpg")
        os.remove("final_ad.jpg")
        
    except Exception as e:
        logger.error(f"Image gen error: {e}")
        await msg.reply_text("❌ متاسفانه در ساخت عکس مشکلی پیش آمد. لطفاً دوباره تلاش کنید.")
    context.user_data.clear()

async def mediator_handler(update, context):
    text = get_text("mediator", update.effective_user.first_name)
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید و ارسال به ادمین", callback_data="mediator_confirm", style="success")], 
        [InlineKeyboardButton("💳 پرداخت با استارز", callback_data="stars_menu", style="primary")],
        [InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]
    ]))

async def mediator_confirm(update, context):
    await update.callback_query.edit_message_text(get_text("mediator_confirm", update.effective_user.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]))

async def post_ad_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'ad_waiting'
    context.user_data['ad_messages'] = []
    await update.callback_query.edit_message_text(get_text("post_ad", update.effective_user.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]))

async def pricing_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'pricing_waiting'
    context.user_data['pricing_messages'] = []
    await update.callback_query.edit_message_text(get_text("pricing", update.effective_user.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]))

async def buy_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'buy_waiting'
    context.user_data['buy_messages'] = []
    await update.callback_query.edit_message_text(get_text("buy", update.effective_user.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]))

async def free_mediator_handler(update, context):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    c.execute(q("SELECT ref_count, points FROM users WHERE user_id=?"), (user_id,))
    row = c.fetchone()
    count = (row['ref_count'] if DATABASE_URL else row[0]) or 0
    points = (row['points'] if DATABASE_URL else row[1]) or 0
    
    text = f"برای واسطه گری رایگان شما باید با لینک خود زیر مجموعه گیری داخل ربات کنید.\n\n🔗 **لینک اختصاصی شما:**\n`{ref_link}`\n\n👥 **تعداد زیرمجموعه‌های شما:** {count} نفر\n💎 **امتیاز اهدایی مدیریت:** {points} امتیاز\n\n**لیست معامله‌ها:**\nمعامله 100 تا 400 هزار: 20 زیر مجموعه\nمعامله بالای 400 تا 900 هزار: 30 زیر مجموعه\nمعامله 1 تا 3 میلیون: 50 زیر مجموعه\nمعامله 4 تا 10 میلیون: 100 زیر مجموعه\nمعامله های بالای 10 میلیون: 250 زیر مجموعه"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]), parse_mode='Markdown')

async def report_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'report_waiting'
    await update.callback_query.edit_message_text("⚠️ مشکل را توضیح دهید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="restart", style="danger")]]))

async def ask_question_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'question_waiting'
    await update.callback_query.edit_message_text("❓ سوال خود را بنویسید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="restart", style="danger")]]))

async def submit_ad(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    msg_ids = context.user_data.get('ad_messages', [])
    text = context.user_data.get('ad_text', '')
    if not msg_ids and not text: return await query.edit_message_text("هیچ محتوایی دریافت نشد.")
    db_ids = msg_ids + (["text"] if text else [])
    c.execute(q("INSERT INTO ads (user_id, message_ids) VALUES (?, ?)"), (user_id, ','.join(map(str, db_ids))))
    if not DATABASE_URL: conn.commit()
    c.execute(q("SELECT id FROM ads WHERE user_id=? ORDER BY id DESC LIMIT 1"), (user_id,))
    row = c.fetchone()
    ad_id = row['id'] if DATABASE_URL else row[0]
    admin_msg_ids = []
    if text:
        m = await context.bot.send_message(ADMIN_ID, text)
        admin_msg_ids.append(m.message_id)
    for mid in msg_ids:
        try:
            fwd = await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=mid)
            admin_msg_ids.append(fwd.message_id)
        except: pass
    c.execute(q("UPDATE ads SET admin_msg_ids=? WHERE id=?"), (','.join(map(str, admin_msg_ids)), ad_id))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.send_message(ADMIN_ID, f"📝 آگهی جدید #{ad_id}\nاز کاربر: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تایید و ارسال به چنل", callback_data=f"approve_ad_{ad_id}", style="success"), InlineKeyboardButton("رد", callback_data=f"reject_ad_{ad_id}", style="danger")], [InlineKeyboardButton("ویرایش متن آگهی", callback_data=f"edit_ad_{ad_id}", style="primary")], [InlineKeyboardButton("بن کردن کاربر", callback_data=f"ban_{user_id}", style="danger")]]))
    except: pass
    await query.edit_message_text("فرم شما ارسال شد ✅🌹\n\nپس از بررسی نتیجه به شما اطلاع داده میشود.")
    context.user_data.clear()

async def submit_pricing(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    msg_ids = context.user_data.get('pricing_messages', [])
    text = context.user_data.get('pricing_text', '')
    if not msg_ids and not text: return await query.edit_message_text("هیچ محتوایی دریافت نشد.")
    db_ids = msg_ids + (["text"] if text else [])
    c.execute(q("INSERT INTO pricing_requests (user_id, message_ids) VALUES (?, ?)"), (user_id, ','.join(map(str, db_ids))))
    if not DATABASE_URL: conn.commit()
    c.execute(q("SELECT id FROM pricing_requests WHERE user_id=? ORDER BY id DESC LIMIT 1"), (user_id,))
    row = c.fetchone()
    req_id = row['id'] if DATABASE_URL else row[0]
    admin_msg_ids = []
    if text:
        m = await context.bot.send_message(ADMIN_ID, text)
        admin_msg_ids.append(m.message_id)
    for mid in msg_ids:
        try:
            fwd = await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=mid)
            admin_msg_ids.append(fwd.message_id)
        except: pass
    c.execute(q("UPDATE pricing_requests SET admin_msg_ids=? WHERE id=?"), (','.join(map(str, admin_msg_ids)), req_id))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.send_message(ADMIN_ID, f"💰 درخواست قیمت گزاری #{req_id}\nاز کاربر: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ارسال قیمت", callback_data=f"send_price_{req_id}", style="success"), InlineKeyboardButton("رد", callback_data=f"reject_pricing_{req_id}", style="danger")]]))
    except: pass
    await query.edit_message_text("اطلاعات شما دریافت شد ✅")
    context.user_data.clear()

async def submit_buy(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    msg_ids = context.user_data.get('buy_messages', [])
    link_text = context.user_data.get('buy_link', '')
    if not msg_ids: return await query.edit_message_text("هیچ محتوایی دریافت نشد.")
    c.execute(q("INSERT INTO buy_requests (user_id, message_ids, link) VALUES (?, ?, ?)"), (user_id, ','.join(map(str, msg_ids)), link_text))
    if not DATABASE_URL: conn.commit()
    c.execute(q("SELECT id FROM buy_requests WHERE user_id=? ORDER BY id DESC LIMIT 1"), (user_id,))
    row = c.fetchone()
    req_id = row['id'] if DATABASE_URL else row[0]
    admin_msg_ids = []
    for mid in msg_ids:
        try:
            fwd = await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=mid)
            admin_msg_ids.append(fwd.message_id)
        except: pass
    c.execute(q("UPDATE buy_requests SET admin_msg_ids=? WHERE id=?"), (','.join(map(str, admin_msg_ids)), req_id))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.send_message(ADMIN_ID, f"🛒 درخواست خرید #{req_id}\nاز کاربر: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ارسال پاسخ", callback_data=f"reply_buy_{req_id}", style="success")]]))
    except: pass
    await query.edit_message_text("لینک شما دریافت شد ✅")
    context.user_data.clear()

async def ban_user_action(update, context, target_id):
    c.execute(q("UPDATE users SET is_banned=1 WHERE user_id=?"), (target_id,))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.ban_chat_member(chat_id=target_id, user_id=target_id)
    except: pass
    for ch, _ in CHANNELS:
        try: await context.bot.ban_chat_member(chat_id=ch, user_id=target_id)
        except: pass
    try: await context.bot.send_message(target_id, "🚫 شما از ربات و کانال‌ها بن شدید.")
    except: pass
    await update.callback_query.answer(f"کاربر {target_id} بن شد.", show_alert=True)

async def admin_show_bans(update, context):
    c.execute(q("SELECT user_id FROM users WHERE is_banned=1"))
    rows = c.fetchall()
    if not rows: return await update.callback_query.edit_message_text("🚫 هیچ کاربر بن شده‌ای وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")]]))
    text, buttons = "🚫 لیست کاربران بن شده:\n\n", []
    for row in rows:
        uid = row['user_id'] if DATABASE_URL else row[0]
        text += f"کاربر: {uid}\n"
        buttons.append([InlineKeyboardButton(f"رفع بن {uid}", callback_data=f"unban_{uid}", style="success")])
    buttons.append([InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def unban_user_action(update, context, target_id):
    c.execute(q("UPDATE users SET is_banned=0 WHERE user_id=?"), (target_id,))
    if not DATABASE_URL: conn.commit()
    for ch, _ in CHANNELS:
        try: await context.bot.unban_chat_member(chat_id=ch, user_id=target_id)
        except: pass
    try: await context.bot.send_message(target_id, "✅ شما از ربات و کانال‌ها رفع بن شدید.")
    except: pass
    await update.callback_query.answer(f"کاربر {target_id} رفع بن شد.", show_alert=True)
    await admin_show_bans(update, context)

async def admin_show_stats(update, context):
    total_users = get_count('users')
    total_ads = get_count('ads')
    total_questions = get_count('questions')
    total_pricing = get_count('pricing_requests')
    total_buy = get_count('buy_requests')
    total_bans = get_count('users WHERE is_banned=1')
    
    text = f"📊 **آمار کلی ربات**\n\n👥 کاربران: **{total_users}**\n📝 آگهی‌ها: **{total_ads}**\n💰 قیمت‌گذاری: **{total_pricing}**\n🛒 خرید: **{total_buy}**\n❓ سوالات: **{total_questions}**\n🚫 بن شده: **{total_bans}**"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت به پنل", callback_data="admin_back", style="primary")]]), parse_mode='Markdown')

async def approve_ad(update, context, ad_id):
    c.execute(q("SELECT user_id, admin_msg_ids, status FROM ads WHERE id=?"), (ad_id,))
    row = c.fetchone()
    if not row or (row['status'] if DATABASE_URL else row[2]) != 'pending': return
    user_id = row['user_id'] if DATABASE_URL else row[0]
    admin_msg_ids_str = row['admin_msg_ids'] if DATABASE_URL else row[1]
    for amid in [int(x) for x in admin_msg_ids_str.split(',') if x]:
        try: await context.bot.copy_message(chat_id=AD_CHANNEL_ID, from_chat_id=ADMIN_ID, message_id=amid)
        except: pass
    c.execute(q("UPDATE ads SET status='approved' WHERE id=?"), (ad_id,))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.send_message(user_id, f"✅ آگهی شما (#{ad_id}) تایید و در چنل منتشر شد.")
    except: pass
    await update.callback_query.edit_message_text(f"✅ آگهی #{ad_id} تایید شد.")

async def reject_ad(update, context, ad_id):
    c.execute(q("SELECT user_id, status FROM ads WHERE id=?"), (ad_id,))
    row = c.fetchone()
    if not row or (row['status'] if DATABASE_URL else row[1]) != 'pending': return
    user_id = row['user_id'] if DATABASE_URL else row[0]
    c.execute(q("UPDATE ads SET status='rejected' WHERE id=?"), (ad_id,))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.send_message(user_id, f"❌ آگهی شما (#{ad_id}) رد شد.")
    except: pass
    await update.callback_query.edit_message_text(f"❌ آگهی #{ad_id} رد شد.")

async def edit_ad_start(update, context, ad_id):
    context.user_data['edit_ad_id'] = ad_id
    context.user_data['state'] = 'admin_editing_ad'
    await update.callback_query.edit_message_text(f"✍️ متن جدید برای آگهی #{ad_id} را بنویسید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_back", style="danger")]]))

async def start_send_price(update, context, req_id):
    c.execute(q("SELECT user_id, status FROM pricing_requests WHERE id=?"), (req_id,))
    row = c.fetchone()
    if not row or (row['status'] if DATABASE_URL else row[1]) != 'pending': return
    user_id = row['user_id'] if DATABASE_URL else row[0]
    context.user_data['admin_send_price_for'] = {'user_id': user_id, 'request_id': req_id}
    context.user_data['state'] = 'admin_send_price'
    await update.callback_query.edit_message_text(f"قیمت اکانت را برای کاربر {user_id} تایپ کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_back", style="danger")]]))

async def reject_pricing(update, context, req_id):
    c.execute(q("SELECT user_id FROM pricing_requests WHERE id=?"), (req_id,))
    row = c.fetchone()
    if not row: return
    user_id = row['user_id'] if DATABASE_URL else row[0]
    c.execute(q("UPDATE pricing_requests SET status='rejected' WHERE id=?"), (req_id,))
    if not DATABASE_URL: conn.commit()
    try: await context.bot.send_message(user_id, f"❌ درخواست قیمت گزاری شما (#{req_id}) رد شد.")
    except: pass
    await update.callback_query.edit_message_text(f"❌ درخواست #{req_id} رد شد.")

async def start_reply_buy(update, context, req_id):
    c.execute(q("SELECT user_id FROM buy_requests WHERE id=?"), (req_id,))
    row = c.fetchone()
    if not row: return
    user_id = row['user_id'] if DATABASE_URL else row[0]
    context.user_data['admin_reply_buy_for'] = {'user_id': user_id, 'request_id': req_id}
    context.user_data['state'] = 'admin_reply_buy'
    await update.callback_query.edit_message_text(f"پاسخ خود را برای کاربر {user_id} تایپ کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_back", style="danger")]]))

async def admin_show_ads(update, context):
    c.execute(q("SELECT id, user_id, status FROM ads ORDER BY id DESC LIMIT 30"))
    rows = c.fetchall()
    if not rows: return await update.callback_query.edit_message_text("هیچ آگهی ثبت نشده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")]]))
    text, buttons = "📋 آگهی های ثبت شده:\n\n", []
    for row in rows:
        ad_id = row['id'] if DATABASE_URL else row[0]
        user_id = row['user_id'] if DATABASE_URL else row[1]
        status = row['status'] if DATABASE_URL else row[2]
        text += f"{'⏳' if status == 'pending' else ('✅' if status == 'approved' else '❌')} #{ad_id} - {user_id}\n"
        if status == 'pending': buttons.append([InlineKeyboardButton(f"مدیریت #{ad_id}", callback_data=f"manage_ad_{ad_id}", style="primary")])
    buttons.append([InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_manage_ad(update, context, ad_id):
    c.execute(q("SELECT user_id, status FROM ads WHERE id=?"), (ad_id,))
    row = c.fetchone()
    if not row or (row['status'] if DATABASE_URL else row[1]) != 'pending': return
    user_id = row['user_id'] if DATABASE_URL else row[0]
    await update.callback_query.edit_message_text(f"📝 آگهی #{ad_id} - {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تایید", callback_data=f"approve_ad_{ad_id}", style="success"), InlineKeyboardButton("رد", callback_data=f"reject_ad_{ad_id}", style="danger")], [InlineKeyboardButton("ویرایش متن", callback_data=f"edit_ad_{ad_id}", style="primary")], [InlineKeyboardButton("برگشت", callback_data="admin_ads", style="primary")]]))

async def admin_show_pricing(update, context):
    c.execute(q("SELECT id, user_id, status FROM pricing_requests ORDER BY id DESC LIMIT 30"))
    rows = c.fetchall()
    if not rows: return await update.callback_query.edit_message_text("هیچ درخواستی نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")]]))
    text, buttons = "💰 قیمت گزاری:\n\n", []
    for row in rows:
        req_id = row['id'] if DATABASE_URL else row[0]
        user_id = row['user_id'] if DATABASE_URL else row[1]
        status = row['status'] if DATABASE_URL else row[2]
        text += f"{'⏳' if status == 'pending' else '✅'} #{req_id} - {user_id}\n"
        if status == 'pending': buttons.append([InlineKeyboardButton(f"ارسال قیمت #{req_id}", callback_data=f"send_price_{req_id}", style="success")])
    buttons.append([InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_show_buy(update, context):
    c.execute(q("SELECT id, user_id, status FROM buy_requests ORDER BY id DESC LIMIT 30"))
    rows = c.fetchall()
    if not rows: return await update.callback_query.edit_message_text("هیچ درخواستی نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")]]))
    text, buttons = "🛒 درخواست های خرید:\n\n", []
    for row in rows:
        req_id = row['id'] if DATABASE_URL else row[0]
        user_id = row['user_id'] if DATABASE_URL else row[1]
        status = row['status'] if DATABASE_URL else row[2]
        text += f"{'⏳' if status == 'pending' else '✅'} #{req_id} - {user_id}\n"
        if status == 'pending': buttons.append([InlineKeyboardButton(f"پاسخ #{req_id}", callback_data=f"reply_buy_{req_id}", style="success")])
    buttons.append([InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_show_questions(update, context):
    c.execute(q("SELECT id, user_id, question_text FROM questions WHERE status='pending' ORDER BY id ASC"))
    rows = c.fetchall()
    if not rows: return await update.callback_query.edit_message_text("❓ سوالی وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")]]))
    text, buttons = "❓ سوالات:\n\n", []
    for idx, row in enumerate(rows, 1):
        q_id = row['id'] if DATABASE_URL else row[0]
        user_id = row['user_id'] if DATABASE_URL else row[1]
        q_text = row['question_text'] if DATABASE_URL else row[2]
        text += f"#سوال {idx} ({user_id}):\n{q_text}\n\n"
        buttons.append([InlineKeyboardButton(f"پاسخ {idx}", callback_data=f"admin_answer_{q_id}", style="success"), InlineKeyboardButton(f"بن", callback_data=f"ban_{user_id}", style="danger")])
    buttons.append([InlineKeyboardButton("برگشت", callback_data="admin_back", style="primary")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def start_answering_question(update, context, q_id):
    c.execute(q("SELECT user_id, question_text, status FROM questions WHERE id=?"), (q_id,))
    row = c.fetchone()
    if not row or (row['status'] if DATABASE_URL else row[2]) != 'pending': return await update.callback_query.answer("قبلاً پاسخ داده شده است.", show_alert=True)
    user_id = row['user_id'] if DATABASE_URL else row[0]
    q_text = row['question_text'] if DATABASE_URL else row[1]
    context.user_data['admin_answer_q'] = {'user_id': user_id, 'q_id': q_id}
    context.user_data['state'] = 'admin_answering_q'
    await update.callback_query.edit_message_text(f"سوال: {q_text}\n\n✍️ پاسخ:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_back", style="danger")]]))

async def admin_settings_menu(update, context):
    buttons = [
        [InlineKeyboardButton("متن خوش آمدگویی", callback_data="edit_txt_welcome", style="primary")],
        [InlineKeyboardButton("متن واسطه گری", callback_data="edit_txt_mediator", style="primary")],
        [InlineKeyboardButton("متن تایید واسطه", callback_data="edit_txt_mediator_confirm", style="primary")],
        [InlineKeyboardButton("متن ثبت اگهی", callback_data="edit_txt_post_ad", style="primary")],
        [InlineKeyboardButton("متن قیمت گزاری", callback_data="edit_txt_pricing", style="primary")],
        [InlineKeyboardButton("متن خرید اکانت", callback_data="edit_txt_buy", style="primary")],
        [InlineKeyboardButton("برگشت", callback_data="admin_back", style="danger")]
    ]
    await update.callback_query.edit_message_text("⚙️ کدام متن را می‌خواهید ویرایش کنید؟", reply_markup=InlineKeyboardMarkup(buttons))

async def start_edit_text(update, context, key):
    context.user_data['edit_text_key'] = key
    context.user_data['state'] = 'admin_editing_text'
    await update.callback_query.edit_message_text(f"متن جدید را بفرستید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_settings", style="danger")]]))

async def admin_transfer_start(update, context):
    context.user_data['state'] = 'admin_transfer_id'
    await update.callback_query.edit_message_text("🎯 آیدی عددی کاربر را وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_back", style="danger")]]))

async def admin_broadcast_start(update, context):
    context.user_data['state'] = 'admin_broadcast_msg'
    context.user_data['broadcast_data'] = {}
    await update.callback_query.edit_message_text("📢 پیام خود را برای ارسال همگانی بفرستید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="admin_back", style="danger")]]))

async def ask_glass_button(update, context, msg):
    context.user_data['broadcast_data']['msg_id'] = msg.message_id
    context.user_data['state'] = 'admin_broadcast_glass'
    buttons = [[InlineKeyboardButton("بله", callback_data="glass_yes", style="success"), InlineKeyboardButton("خیر", callback_data="glass_no", style="danger")]]
    await msg.reply_text("آیا می‌خواهید این پیام دکمه شیشه‌ای داشته باشد؟", reply_markup=InlineKeyboardMarkup(buttons))

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if any(data.startswith(p) for p in ('approve_ad_', 'reject_ad_', 'send_price_', 'reject_pricing_', 'reply_buy_', 'manage_ad_', 'admin_', 'admin_answer_', 'ban_', 'unban_', 'edit_ad_', 'edit_txt_', 'glass_yes', 'glass_no', 'ch_glass_')) and not is_admin(user_id): return await query.answer("دسترسی ندارید", show_alert=True)
    
    if data == "check_join":
        if await check_membership(user_id, context.bot): return await query.answer("هنوز عضو نشدید", show_alert=True)
        await show_user_menu(update, context)
    elif data == "restart":
        context.user_data.clear()
        if is_admin(user_id): await show_admin_panel(update, context)
        else: await show_user_menu(update, context)
    elif data == "create_ad_img": await create_ad_img_start(update, context)
    elif data == "img_photos_done": await img_photos_done(update, context)
    elif data == "mediator": await mediator_handler(update, context)
    elif data == "stars_menu": await stars_menu(update, context)
    elif data.startswith("pay_stars_"): await send_stars_invoice(update, context, int(data.split('_')[-1]))
    elif data == "free_mediator": await free_mediator_handler(update, context)
    elif data == "mediator_confirm": await mediator_confirm(update, context)
    elif data == "post_ad": await post_ad_handler(update, context)
    elif data == "pricing": await pricing_handler(update, context)
    elif data == "buy_account": await buy_handler(update, context)
    elif data == "report": await report_handler(update, context)
    elif data == "ask_question": await ask_question_handler(update, context)
    elif data == "submit_ad": await submit_ad(update, context)
    elif data == "submit_pricing": await submit_pricing(update, context)
    elif data == "submit_buy": await submit_buy(update, context)
    elif data == "admin_back": await show_admin_panel(update, context)
    elif data == "admin_stats": await admin_show_stats(update, context)
    elif data == "admin_ads": await admin_show_ads(update, context)
    elif data == "admin_pricing": await admin_show_pricing(update, context)
    elif data == "admin_buy": await admin_show_buy(update, context)
    elif data == "admin_questions": await admin_show_questions(update, context)
    elif data == "admin_bans": await admin_show_bans(update, context)
    elif data == "admin_settings": await admin_settings_menu(update, context)
    elif data == "admin_transfer": await admin_transfer_start(update, context)
    elif data == "admin_broadcast": await admin_broadcast_start(update, context)
    elif data.startswith("edit_txt_"): await start_edit_text(update, context, data.replace("edit_txt_", ""))
    elif data.startswith("edit_ad_"): await edit_ad_start(update, context, int(data.split('_')[-1]))
    elif data.startswith("ban_"): await ban_user_action(update, context, int(data.split('_')[-1]))
    elif data.startswith("unban_"): await unban_user_action(update, context, int(data.split('_')[-1]))
    elif data.startswith("admin_answer_"): await start_answering_question(update, context, int(data.split('_')[-1]))
    elif data.startswith("manage_ad_"): await admin_manage_ad(update, context, int(data.split('_')[-1]))
    elif data.startswith("approve_ad_"): await approve_ad(update, context, int(data.split('_')[-1]))
    elif data.startswith("reject_ad_"): await reject_ad(update, context, int(data.split('_')[-1]))
    elif data.startswith("send_price_"): await start_send_price(update, context, int(data.split('_')[-1]))
    elif data.startswith("reject_pricing_"): await reject_pricing(update, context, int(data.split('_')[-1]))
    elif data.startswith("reply_buy_"): await start_reply_buy(update, context, int(data.split('_')[-1]))
    elif data == "glass_yes":
        context.user_data['state'] = 'admin_broadcast_btn_txt'
        await query.edit_message_text("✍️ متن دکمه شیشه‌ای:")
    elif data == "glass_no":
        msg_id = context.user_data['broadcast_data']['msg_id']
        context.user_data['state'] = None
        await query.edit_message_text("⏳ در حال ارسال...")
        await do_broadcast(context, msg_id, None)
        await query.edit_message_text("✅ ارسال شد.")
    elif data.startswith("ch_glass_no_"): await query.edit_message_text("❌ لغو شد.")
    elif data.startswith("ch_glass_yes_"):
        msg_id = int(data.split('_')[-1])
        context.user_data['ch_msg_id'] = msg_id
        context.user_data['state'] = 'admin_ch_glass_txt'
        await query.edit_message_text("✍️ متن دکمه شیشه‌ای:")

async def do_broadcast(context, msg_id, btn_markup):
    c.execute(q("SELECT user_id FROM users WHERE is_banned=0"))
    users = c.fetchall()
    success, failed = 0, 0
    for u in users:
        uid = u['user_id'] if DATABASE_URL else u[0]
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=ADMIN_ID, message_id=msg_id, reply_markup=btn_markup)
            success += 1
        except: failed += 1
    return success, failed

async def message_handler(update, context):
    msg = update.message
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if is_banned(user_id): return await msg.reply_text("🚫 شما از ربات بن شده اید.")
    
    if msg.successful_payment:
        stars = msg.successful_payment.total_amount
        for admin_star_id in STARS_ADMIN_IDS:
            try: await context.bot.send_message(admin_star_id, f"💰 **پرداخت استارزی!**\n\n👤 {user_name}\n🆔 `{user_id}`\n⭐️ {stars} استارز", parse_mode='Markdown')
            except: pass
        await msg.reply_text(f"✅ پرداخت {stars} استارز انجام شد.")
        return

    state = context.user_data.get('state')
    if not state: return

    if state == 'img_gen_photos':
        if msg.photo: await process_photos(update, context, msg)
        return
    if state == 'img_gen_questions' and not is_admin(user_id):
        idx = context.user_data.get('img_q_index', 0)
        q_key, q_text = QUESTIONS[idx]
        context.user_data['img_data'][q_key] = msg.text
        idx += 1
        context.user_data['img_q_index'] = idx
        if idx < len(QUESTIONS):
            next_key, next_q = QUESTIONS[idx]
            await msg.reply_text(f"سوال {idx+1} از {len(QUESTIONS)}:\n\n{next_q}")
        else: await generate_ad_image(update, context)
        return

    if state == 'admin_ch_glass_txt' and is_admin(user_id):
        context.user_data['ch_btn_txt'] = msg.text
        context.user_data['state'] = 'admin_ch_glass_url'
        await msg.reply_text("🔗 لینک دکمه:")
        return
    if state == 'admin_ch_glass_url' and is_admin(user_id):
        url = msg.text
        if not url.startswith("http"): url = "https://" + url
        btn_txt = context.user_data['ch_btn_txt']
        msg_id = context.user_data['ch_msg_id']
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_txt, url=url, style="primary")]])
        try:
            await context.bot.edit_message_reply_markup(chat_id=AD_CHANNEL_ID, message_id=msg_id, reply_markup=markup)
            await msg.reply_text("✅ شیشه ای شد.")
        except Exception as e: await msg.reply_text(f"❌ خطا: {e}")
        context.user_data.clear()
        return

    if state == 'admin_editing_text' and is_admin(user_id):
        set_text(context.user_data['edit_text_key'], msg.text)
        await msg.reply_text(f"✅ ذخیره شد.")
        context.user_data.clear()
        await show_admin_panel(update, context)
        return
    if state == 'admin_transfer_id' and is_admin(user_id):
        try:
            context.user_data['target_id'] = int(msg.text)
            context.user_data['state'] = 'admin_transfer_points'
            await msg.reply_text(f"تعداد امتیاز:")
        except: await msg.reply_text("آیدی معتبر وارد کنید.")
        return
    if state == 'admin_transfer_points' and is_admin(user_id):
        try:
            points = int(msg.text)
            target_id = context.user_data['target_id']
            c.execute(q("UPDATE users SET points = points + ? WHERE user_id=?"), (points, target_id))
            if not DATABASE_URL: conn.commit()
            try: await context.bot.send_message(target_id, f"🎁 از طرف مدیریت\n\n💎 {points} امتیاز اضافه شد!")
            except: pass
            await msg.reply_text("✅ منتقل شد.")
        except: await msg.reply_text("عدد معتبر وارد کنید.")
        context.user_data.clear()
        await show_admin_panel(update, context)
        return
    if state == 'admin_editing_ad' and is_admin(user_id):
        ad_id = context.user_data['edit_ad_id']
        c.execute(q("SELECT message_ids FROM ads WHERE id=?"), (ad_id,))
        row = c.fetchone()
        if row:
            old_ids = (row['message_ids'] if DATABASE_URL else row[0]).split(',')
            new_ids = [x for x in old_ids if x != 'text']
            c.execute(q("UPDATE ads SET message_ids=? WHERE id=?"), (','.join(new_ids + ['text']), ad_id))
            if not DATABASE_URL: conn.commit()
            await context.bot.send_message(ADMIN_ID, f"📝 متن ویرایش شده #{ad_id}:\n\n{msg.text}")
            await msg.reply_text("✅ ویرایش شد.")
        context.user_data.clear()
        return

    if state == 'admin_broadcast_msg' and is_admin(user_id):
        context.user_data['broadcast_data']['msg_id'] = msg.message_id
        await ask_glass_button(update, context, msg)
        return
    if state == 'admin_broadcast_btn_txt' and is_admin(user_id):
        context.user_data['broadcast_data']['btn_txt'] = msg.text
        context.user_data['state'] = 'admin_broadcast_btn_url'
        await msg.reply_text("🔗 لینک:")
        return
    if state == 'admin_broadcast_btn_url' and is_admin(user_id):
        btn_url = msg.text
        if not btn_url.startswith("http"): btn_url = "https://" + btn_url
        btn_txt = context.user_data['broadcast_data']['btn_txt']
        msg_id = context.user_data['broadcast_data']['msg_id']
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_txt, url=btn_url, style="success")]])
        context.user_data['state'] = None
        await msg.reply_text("⏳ در حال ارسال...")
        success, failed = await do_broadcast(context, msg_id, markup)
        await msg.reply_text(f"✅ پایان.\nموفق: {success}\nناموفق: {failed}")
        context.user_data.clear()
        return

    if state == 'admin_send_price' and is_admin(user_id):
        info = context.user_data['admin_send_price_for']
        try:
            await context.bot.send_message(info['user_id'], f"💰 قیمت اکانت شما:\n\n{msg.text}")
            await msg.reply_text(f"✅ ارسال شد.")
            c.execute(q("UPDATE pricing_requests SET status='answered' WHERE id=?"), (info['request_id'],))
            if not DATABASE_URL: conn.commit()
        except: pass
        context.user_data.clear()
        return
    if state == 'admin_reply_buy' and is_admin(user_id):
        info = context.user_data['admin_reply_buy_for']
        try:
            await context.bot.copy_message(chat_id=info['user_id'], from_chat_id=user_id, message_id=msg.message_id)
            await msg.reply_text(f"✅ ارسال شد.")
            c.execute(q("UPDATE buy_requests SET status='answered' WHERE id=?"), (info['request_id'],))
            if not DATABASE_URL: conn.commit()
        except: pass
        context.user_data.clear()
        return
    if state == 'admin_answering_q' and is_admin(user_id):
        info = context.user_data['admin_answer_q']
        try:
            await context.bot.send_message(info['user_id'], f"📬 پاسخ:\n\n{msg.text}")
            await msg.reply_text(f"✅ ارسال شد.")
            c.execute(q("UPDATE questions SET status='answered', answer_text=? WHERE id=?"), (msg.text, info['q_id']))
            if not DATABASE_URL: conn.commit()
        except: pass
        context.user_data.clear()
        return

    if not is_admin(user_id):
        if await check_membership(user_id, context.bot):
            buttons = [[InlineKeyboardButton(f"عضویت در {ch}", url=link, style="primary")] for ch, link in CHANNELS]
            buttons.append([InlineKeyboardButton("عضو شدم", callback_data="check_join", style="success")])
            return await msg.reply_text("ابتدا عضو شوید:", reply_markup=InlineKeyboardMarkup(buttons))
            
    if state == 'question_waiting':
        c.execute(q("INSERT INTO questions (user_id, question_text) VALUES (?, ?)"), (user_id, msg.text))
        if not DATABASE_URL: conn.commit()
        await msg.reply_text("✅ سوال ثبت شد.")
        try: await context.bot.send_message(ADMIN_ID, f"❓ سوال از {user_id}:\n\n{msg.text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بن", callback_data=f"ban_{user_id}", style="danger")]]))
        except: pass
        context.user_data.clear()
    elif state == 'ad_waiting':
        if msg.text:
            context.user_data['ad_text'] = context.user_data.get('ad_text', '') + '\n' + extract_clean_form(msg.text)
        elif msg.photo or msg.document or msg.video:
            context.user_data['ad_messages'].append(msg.message_id)
        if not context.user_data.get('prompted'):
            context.user_data['prompted'] = True
            await msg.reply_text("📥 دریافت شد.\nپایان:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("پایان و ارسال", callback_data="submit_ad", style="success")]]))
    elif state == 'pricing_waiting':
        if msg.text:
            context.user_data['pricing_text'] = context.user_data.get('pricing_text', '') + '\n' + extract_clean_form(msg.text)
        elif msg.photo or msg.document or msg.video:
            context.user_data['pricing_messages'].append(msg.message_id)
        if not context.user_data.get('prompted'):
            context.user_data['prompted'] = True
            await msg.reply_text("📥 دریافت شد.\nپایان:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("پایان و ارسال", callback_data="submit_pricing", style="success")]]))
    elif state == 'buy_waiting':
        if msg.text: context.user_data['buy_link'] = msg.text
        elif msg.photo or msg.document or msg.video: context.user_data['buy_messages'].append(msg.message_id)
        if not context.user_data.get('prompted'):
            context.user_data['prompted'] = True
            await msg.reply_text("📥 دریافت شد.\nپایان:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ارسال", callback_data="submit_buy", style="success")]]))
    elif state == 'report_waiting':
        try: await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=msg.message_id)
        except: pass
        await msg.reply_text("✅ گزارش ارسال شد.")
        context.user_data.clear()

app = FastAPI()
bot_app = Application.builder().token(BOT_TOKEN).updater(None).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
bot_app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post_handler))
bot_app.add_handler(CallbackQueryHandler(button_handler))
bot_app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.SUCCESSFUL_PAYMENT) & ~filters.COMMAND, message_handler))

@app.on_event("startup")
async def on_startup():
    await bot_app.initialize()
    await bot_app.bot.set_my_commands([BotCommand("start", "شروع مجدد ربات")])
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
    await bot_app.bot.set_webhook(f"{render_url}/{BOT_TOKEN}")

@app.post(f"/{BOT_TOKEN}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return Response(status_code=200)

@app.get("/")
async def root(): return {"status": "Bot is running!"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
