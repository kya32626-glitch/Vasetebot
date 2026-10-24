import os, logging, sqlite3
from fastapi import FastAPI, Request, Response
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 8396752402
AD_CHANNEL_ID = "@Vasetearminazizi"
CHANNELS = [("@Vasetearminazizi", "https://t.me/Vasetearminazizi"), ("@etemadearminazizi", "https://t.me/etemadearminazizi")]

conn = sqlite3.connect('bot.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
try:
    c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN ref_count INTEGER DEFAULT 0")
except: pass
c.execute('''CREATE TABLE IF NOT EXISTS referrals (invited_id INTEGER PRIMARY KEY, inviter_id INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS ads (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE TABLE IF NOT EXISTS pricing_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE TABLE IF NOT EXISTS buy_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_ids TEXT, admin_msg_ids TEXT DEFAULT '', link TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, question_text TEXT, answer_text TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
conn.commit()

def is_admin(user_id): return user_id == ADMIN_ID
def is_banned(user_id):
    c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row and row[0] == 1

def extract_clean_form(text):
    if not text: return text
    markers = ["اطلاعات اکانتتونو", "❗️ اگر اکانت شما", "فرم را همراه عکس ها", "ممنون از شما"]
    for marker in markers:
        if marker in text: text = text.split(marker)[0].strip()
    return text

async def check_membership(user_id, bot):
    not_joined = []
    for ch, link in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in ('left', 'kicked'): not_joined.append((ch, link))
        except: pass
    return not_joined

def main_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📞 درخواست واسطه گری", callback_data="mediator")], [InlineKeyboardButton("🆓 واسطه گری رایگان", callback_data="free_mediator")], [InlineKeyboardButton("📝 ثبت اگهی", callback_data="post_ad")], [InlineKeyboardButton("💰 قیمت گزاری روی اکانت", callback_data="pricing")], [InlineKeyboardButton("🛒 خرید اکانت", callback_data="buy_account")], [InlineKeyboardButton("❓ پرسیدن سوال", callback_data="ask_question")], [InlineKeyboardButton("⚠️ گزارش خرابی", callback_data="report")]])

def admin_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📋 آگهی های ثبت شده", callback_data="admin_ads")], [InlineKeyboardButton("💰 درخواست قیمت گزاری", callback_data="admin_pricing")], [InlineKeyboardButton("🛒 خرید اکانت", callback_data="admin_buy")], [InlineKeyboardButton("❓ سوال های پرسیده شده", callback_data="admin_questions")], [InlineKeyboardButton("🚫 کاربران بن شده", callback_data="admin_bans")], [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")]])

WELCOME = "این تنها ربات پاسخگویی واسطه گری آرمین عزیزی است\nآیدی ادمین واسطه: @Vasete_armin_azizi"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    if is_banned(user_id): return await update.message.reply_text("🚫 شما از ربات بن شده اید.")
    
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    is_new = not c.fetchone()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    
    if is_new and context.args and context.args[0].startswith("ref_"):
        inviter_id = int(context.args[0].replace("ref_", ""))
        if inviter_id != user_id:
            c.execute("INSERT OR IGNORE INTO referrals (invited_id, inviter_id) VALUES (?, ?)", (user_id, inviter_id))
            if c.total_changes > 0:
                conn.commit()
                c.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (inviter_id,))
                count = c.fetchone()[0]
                c.execute("UPDATE users SET ref_count=? WHERE user_id=?", (count, inviter_id))
                conn.commit()
                try:
                    await context.bot.send_message(inviter_id, f"🎉 یک نفر با لینک شما وارد ربات شد!\nتعداد زیرمجموعه‌های شما: {count}")
                    if count == 20: await context.bot.send_message(ADMIN_ID, f"⚠️ کاربر {inviter_id} به ۲۰ زیرمجموعه رسید!")
                except: pass
                
    if is_admin(user_id): return await show_admin_panel(update, context)
    not_joined = await check_membership(user_id, context.bot)
    if not_joined:
        buttons = [[InlineKeyboardButton(f"🔗 عضویت در {ch}", url=link)] for ch, link in not_joined]
        buttons.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")])
        return await update.message.reply_text("برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:", reply_markup=InlineKeyboardMarkup(buttons))
    await update.message.reply_text(WELCOME, reply_markup=main_menu_keyboard())

async def show_admin_panel(update, context):
    text = "🔧 پنل مدیریت\nیک گزینه را انتخاب کنید:"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=admin_menu_keyboard())
    else: await update.message.reply_text(text, reply_markup=admin_menu_keyboard())

async def show_user_menu(update, context):
    if update.callback_query: await update.callback_query.edit_message_text(WELCOME, reply_markup=main_menu_keyboard())
    else: await update.message.reply_text(WELCOME, reply_markup=main_menu_keyboard())

async def mediator_handler(update, context):
    text = "قیمت های واسطه گری به این صورت است:\n\nمعامله زیر 50 هزار : رایگان\n━━━━━━━━━━━━━━━━━\nمعامله 50 هزار تا 100 هزار: رایگان\n━━━━━━━━━━━━━━━━━\nمعامله 100 تا 300 : نفری ۱۰ هزار\n━━━━━━━━━━━━━━━━━\nمعامله 400 تا 900 هزار: نفری ۵۰ هزار\n━━━━━━━━━━━━━━━━━\nمعامله 1500 تا 3 میل : نفری 100 هزار\n━━━━━━━━━━━━━━━━━\nمعامله ۴ میل تا ۱۰ میل : نفری 350 هزار\n━━━━━━━━━━━━━━━━━\nمعامله های بالای 10 میل: نفری ۵۰۰ هزار\n\nاگر با قیمت ها اوکی بودید گزینه تایید رو بزنید."
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data="mediator_confirm")], [InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]))

async def free_mediator_handler(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    c.execute("SELECT ref_count FROM users WHERE user_id=?", (user_id,))
    count = c.fetchone()[0] or 0
    text = f"برای واسطه گری رایگان شما باید با لینک خود زیر مجموعه گیری داخل ربات کنید.\n\n🔗 **لینک اختصاصی شما:**\n`{ref_link}`\n\n👥 **تعداد زیرمجموعه‌های شما:** {count} نفر\n\n**لیست معامله‌ها:**\nمعامله 100 هزار تا 400 هزار: 20 زیر مجموعه\nمعامله بالای 400 تا 900 هزار: 30 زیر مجموعه\nمعامله 1 میلیون تا 3 میلیون: 50 زیر مجموعه\nمعامله 4 میلیون تا 10 میلیون: 100 زیر مجموعه\nمعامله های بالای 10 میلیون: 250 زیر مجموعه"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]), parse_mode='Markdown')

async def mediator_confirm(update, context):
    text = "لطفاً اطلاعات زیر را به ایدی زیر ارسال نمایید:\n\n@Vasete_armin_azizi\n\n1_ آیدی شما و طرف مقابل\n2_ فرم اگهی اکانت یا عکس ها\n3_ ارزش اکانت شما\n\n⚠️ توجه داشته باشید تایید دو مرحله اکانت کالاف دیوتی الزامی است.\n\n⚠️ معامله فقط توسط همین آیدی بالا انجام میشود و ربات واسطه گری نمیکند."
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]))

async def post_ad_handler(update, context):
    text = "📋 فرم ثبت اگهی:\n\nنوع بازی🎮:\nـــــــــــــــــــــــــــــــــــ\n\nسیو ها📥:\nـــــــــــــــــــــــــــــــــ\n\nایا قابل چنج هست:\nتعداد سیپی🪙:\nتعداد گان متیک 🟥:\nتعداد گان لجند 🟨:\nتعداد بتل پس:\nتوضیحات فروشنده:\nUid:\nقیمت:\nآیدی فروشنده:\n\nجهت خرید اکانت اگهی کردن اکانت و قیمت گزاری و درخاست واسطه به بات مراجعه کنید:\n@Vasetearminazizibot\n\nجهت ارتباط با ادمین و واسطه گری اکانت:\n@Vasete_armin_azizi\n\nچنلمون:\nhttps://t.me/Vasetearminazizi\n\nاعتماد:\nhttps://t.me/etemadearminazizi\n\nاطلاعات اکانتتونو در فرم بالا پر کنید و سپس ارسال کنید\n\n❗️ اگر اکانت شما گزینه های زیر رو نداشته باشه آگهی نمیشه:\n1_ آیدی فروشنده الزامیس\n2_ عکس حد اقل 2 و حد اکثر 9 تا\n\nفرم را همراه عکس ها ارسال کنید و پیام اضافه نفرستید.\nممنون از شما❤️"
    context.user_data.clear()
    context.user_data['state'] = 'ad_waiting'
    context.user_data['ad_messages'] = []
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]))

async def pricing_handler(update, context):
    text = "برای قیمت گزاری اکانت اطلاعات زیر را ارسال نمایید:\n\n• عکس های اکانت\n• ایتم ها\n• وضعیت سیو ها\n• سیپی منفی دارد / ندارد\n\nلطفا از ارسال پیام های دیگر خودداری نمایید.\nپس از ارسال اطلاعات نهایتا تا یک الی دو ساعت قیمت تقریبی اکانت برای شما ارسال میشود."
    context.user_data.clear()
    context.user_data['state'] = 'pricing_waiting'
    context.user_data['pricing_messages'] = []
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]))

async def buy_handler(update, context):
    text = "اکانتی که قصد خرید ان را دارید لینک پیام آن را در چنل آگهی و دارید و بفرستید.\nدقت کنید اگهی فقط باید در چنل خرید فروش ما آگهی شده باشد.\n\nاز ارسال پیام های دیگر خودداری کنید.\nپس از ارسال آگهی ان اکانت استعلام گرفته میشود و سپس به شما اطلاع داده میشود.\n\nبا تشکر از همراهی شما."
    context.user_data.clear()
    context.user_data['state'] = 'buy_waiting'
    context.user_data['buy_messages'] = []
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]))

async def report_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'report_waiting'
    await update.callback_query.edit_message_text("⚠️ لطفاً مشکل یا باگ پیش آمده را توضیح دهید و ارسال کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="restart")]]))

async def ask_question_handler(update, context):
    context.user_data.clear()
    context.user_data['state'] = 'question_waiting'
    await update.callback_query.edit_message_text("❓ لطفاً سوال خود را بنویسید و ارسال کنید:\n(تنها یک پیام متنی بفرستید)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="restart")]]))

async def submit_ad(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    msg_ids = context.user_data.get('ad_messages', [])
    text = context.user_data.get('ad_text', '')
    if not msg_ids and not text: return await query.edit_message_text("هیچ محتوایی دریافت نشد.")
    db_ids = msg_ids + (["text"] if text else [])
    c.execute("INSERT INTO ads (user_id, message_ids) VALUES (?, ?)", (user_id, ','.join(map(str, db_ids))))
    ad_id = c.lastrowid
    conn.commit()
    admin_msg_ids = []
    if text:
        m = await context.bot.send_message(ADMIN_ID, text)
        admin_msg_ids.append(m.message_id)
    for mid in msg_ids:
        try:
            fwd = await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=mid)
            admin_msg_ids.append(fwd.message_id)
        except: pass
    c.execute("UPDATE ads SET admin_msg_ids=? WHERE id=?", (','.join(map(str, admin_msg_ids)), ad_id))
    conn.commit()
    try: await context.bot.send_message(ADMIN_ID, f"📝 آگهی جدید #{ad_id}\nاز کاربر: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید و ارسال به چنل", callback_data=f"approve_ad_{ad_id}"), InlineKeyboardButton("❌ رد", callback_data=f"reject_ad_{ad_id}")], [InlineKeyboardButton("🚫 بن کردن کاربر", callback_data=f"ban_{user_id}")]]))
    except: pass
    await query.edit_message_text("فرم شما ارسال شد ✅🌹\n\nزمان تقریبی اگهی: بین بیست دقیقه تا یک ساعت⏰\nپس از بررسی نتیجه به شما اطلاع داده میشود.")
    context.user_data.clear()

async def submit_pricing(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    msg_ids = context.user_data.get('pricing_messages', [])
    text = context.user_data.get('pricing_text', '')
    if not msg_ids and not text: return await query.edit_message_text("هیچ محتوایی دریافت نشد.")
    db_ids = msg_ids + (["text"] if text else [])
    c.execute("INSERT INTO pricing_requests (user_id, message_ids) VALUES (?, ?)", (user_id, ','.join(map(str, db_ids))))
    req_id = c.lastrowid
    conn.commit()
    admin_msg_ids = []
    if text:
        m = await context.bot.send_message(ADMIN_ID, text)
        admin_msg_ids.append(m.message_id)
    for mid in msg_ids:
        try:
            fwd = await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=mid)
            admin_msg_ids.append(fwd.message_id)
        except: pass
    c.execute("UPDATE pricing_requests SET admin_msg_ids=? WHERE id=?", (','.join(map(str, admin_msg_ids)), req_id))
    conn.commit()
    try: await context.bot.send_message(ADMIN_ID, f"💰 درخواست قیمت گزاری #{req_id}\nاز کاربر: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💵 ارسال قیمت", callback_data=f"send_price_{req_id}"), InlineKeyboardButton("❌ رد", callback_data=f"reject_pricing_{req_id}")], [InlineKeyboardButton("🚫 بن کردن کاربر", callback_data=f"ban_{user_id}")]]))
    except: pass
    await query.edit_message_text("اطلاعات شما دریافت شد ✅\nنهایتا تا یک الی دو ساعت قیمت تقریبی اکانت برای شما ارسال میشود.")
    context.user_data.clear()

async def submit_buy(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    msg_ids = context.user_data.get('buy_messages', [])
    link_text = context.user_data.get('buy_link', '')
    if not msg_ids: return await query.edit_message_text("هیچ محتوایی دریافت نشد.")
    c.execute("INSERT INTO buy_requests (user_id, message_ids, link) VALUES (?, ?, ?)", (user_id, ','.join(map(str, msg_ids)), link_text))
    req_id = c.lastrowid
    conn.commit()
    admin_msg_ids = []
    for mid in msg_ids:
        try:
            fwd = await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=mid)
            admin_msg_ids.append(fwd.message_id)
        except: pass
    c.execute("UPDATE buy_requests SET admin_msg_ids=? WHERE id=?", (','.join(map(str, admin_msg_ids)), req_id))
    conn.commit()
    try: await context.bot.send_message(ADMIN_ID, f"🛒 درخواست خرید #{req_id}\nاز کاربر: {user_id}\n\nلینک: {link_text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 ارسال پاسخ", callback_data=f"reply_buy_{req_id}")], [InlineKeyboardButton("🚫 بن کردن کاربر", callback_data=f"ban_{user_id}")]]))
    except: pass
    await query.edit_message_text("لینک شما دریافت شد ✅\nپس از استعلام به شما اطلاع داده میشود.")
    context.user_data.clear()

async def ban_user_action(update, context, target_id):
    query = update.callback_query
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
    conn.commit()
    try: await context.bot.ban_chat_member(chat_id=target_id, user_id=target_id)
    except: pass
    for ch, _ in CHANNELS:
        try: await context.bot.ban_chat_member(chat_id=ch, user_id=target_id)
        except: pass
    try: await context.bot.send_message(target_id, "🚫 شما از ربات و کانال‌ها بن شدید.")
    except: pass
    await query.answer(f"کاربر {target_id} بن شد.", show_alert=True)

async def admin_show_bans(update, context):
    query = update.callback_query
    c.execute("SELECT user_id FROM users WHERE is_banned=1")
    rows = c.fetchall()
    if not rows: return await query.edit_message_text("🚫 هیچ کاربر بن شده‌ای وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]))
    text, buttons = "🚫 لیست کاربران بن شده:\n\n", []
    for row in rows:
        uid = row[0]
        text += f"کاربر: {uid}\n"
        buttons.append([InlineKeyboardButton(f"رفع بن {uid}", callback_data=f"unban_{uid}")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def unban_user_action(update, context, target_id):
    query = update.callback_query
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
    conn.commit()
    for ch, _ in CHANNELS:
        try: await context.bot.unban_chat_member(chat_id=ch, user_id=target_id)
        except: pass
    try: await context.bot.send_message(target_id, "✅ شما از ربات و کانال‌ها رفع بن شدید. می‌توانید دوباره استارت بزنید.")
    except: pass
    await query.answer(f"کاربر {target_id} رفع بن شد.", show_alert=True)
    await admin_show_bans(update, context)

async def approve_ad(update, context, ad_id):
    query = update.callback_query
    c.execute("SELECT user_id, admin_msg_ids, status FROM ads WHERE id=?", (ad_id,))
    row = c.fetchone()
    if not row or row[2] != 'pending': return
    user_id, admin_msg_ids_str, status = row
    for amid in [int(x) for x in admin_msg_ids_str.split(',') if x]:
        try: await context.bot.copy_message(chat_id=AD_CHANNEL_ID, from_chat_id=ADMIN_ID, message_id=amid)
        except: pass
    c.execute("UPDATE ads SET status='approved' WHERE id=?", (ad_id,))
    conn.commit()
    try: await context.bot.send_message(user_id, f"✅ آگهی شما (#{ad_id}) تایید و در چنل منتشر شد.")
    except: pass
    await query.edit_message_text(f"✅ آگهی #{ad_id} تایید شد.")

async def reject_ad(update, context, ad_id):
    query = update.callback_query
    c.execute("SELECT user_id, status FROM ads WHERE id=?", (ad_id,))
    row = c.fetchone()
    if not row or row[1] != 'pending': return
    c.execute("UPDATE ads SET status='rejected' WHERE id=?", (ad_id,))
    conn.commit()
    try: await context.bot.send_message(row[0], f"❌ آگهی شما (#{ad_id}) رد شد.")
    except: pass
    await query.edit_message_text(f"❌ آگهی #{ad_id} رد شد.")

async def start_send_price(update, context, req_id):
    query = update.callback_query
    c.execute("SELECT user_id, status FROM pricing_requests WHERE id=?", (req_id,))
    row = c.fetchone()
    if not row or row[1] != 'pending': return
    context.user_data['admin_send_price_for'] = {'user_id': row[0], 'request_id': req_id}
    context.user_data['state'] = 'admin_send_price'
    await query.edit_message_text(f"قیمت اکانت را برای کاربر {row[0]} تایپ و ارسال کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="admin_back")]]))

async def reject_pricing(update, context, req_id):
    query = update.callback_query
    c.execute("SELECT user_id FROM pricing_requests WHERE id=?", (req_id,))
    row = c.fetchone()
    if not row: return
    c.execute("UPDATE pricing_requests SET status='rejected' WHERE id=?", (req_id,))
    conn.commit()
    try: await context.bot.send_message(row[0], f"❌ درخواست قیمت گزاری شما (#{req_id}) رد شد.")
    except: pass
    await query.edit_message_text(f"❌ درخواست #{req_id} رد شد.")

async def start_reply_buy(update, context, req_id):
    query = update.callback_query
    c.execute("SELECT user_id FROM buy_requests WHERE id=?", (req_id,))
    row = c.fetchone()
    if not row: return
    context.user_data['admin_reply_buy_for'] = {'user_id': row[0], 'request_id': req_id}
    context.user_data['state'] = 'admin_reply_buy'
    await query.edit_message_text(f"پاسخ خود را برای کاربر {row[0]} تایپ کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="admin_back")]]))

async def admin_show_ads(update, context):
    query = update.callback_query
    c.execute("SELECT id, user_id, status FROM ads ORDER BY id DESC LIMIT 30")
    rows = c.fetchall()
    if not rows: return await query.edit_message_text("هیچ آگهی ثبت نشده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]))
    text, buttons = "📋 آگهی های ثبت شده:\n\n", []
    for ad_id, user_id, status in rows:
        text += f"{'⏳' if status == 'pending' else ('✅' if status == 'approved' else '❌')} #{ad_id} - کاربر {user_id}\n"
        if status == 'pending': buttons.append([InlineKeyboardButton(f"مدیریت #{ad_id}", callback_data=f"manage_ad_{ad_id}")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_manage_ad(update, context, ad_id):
    query = update.callback_query
    c.execute("SELECT user_id, status FROM ads WHERE id=?", (ad_id,))
    row = c.fetchone()
    if not row or row[1] != 'pending': return
    await query.edit_message_text(f"📝 آگهی #{ad_id} - کاربر {row[0]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data=f"approve_ad_{ad_id}"), InlineKeyboardButton("❌ رد", callback_data=f"reject_ad_{ad_id}")], [InlineKeyboardButton("🔙 برگشت", callback_data="admin_ads")]]))

async def admin_show_pricing(update, context):
    query = update.callback_query
    c.execute("SELECT id, user_id, status FROM pricing_requests ORDER BY id DESC LIMIT 30")
    rows = c.fetchall()
    if not rows: return await query.edit_message_text("هیچ درخواستی وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]))
    text, buttons = "💰 درخواست های قیمت گزاری:\n\n", []
    for req_id, user_id, status in rows:
        text += f"{'⏳' if status == 'pending' else '✅'} #{req_id} - کاربر {user_id}\n"
        if status == 'pending': buttons.append([InlineKeyboardButton(f"ارسال قیمت #{req_id}", callback_data=f"send_price_{req_id}")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_show_buy(update, context):
    query = update.callback_query
    c.execute("SELECT id, user_id, status FROM buy_requests ORDER BY id DESC LIMIT 30")
    rows = c.fetchall()
    if not rows: return await query.edit_message_text("هیچ درخواست خریدی وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]))
    text, buttons = "🛒 درخواست های خرید:\n\n", []
    for req_id, user_id, status in rows:
        text += f"{'⏳' if status == 'pending' else '✅'} #{req_id} - کاربر {user_id}\n"
        if status == 'pending': buttons.append([InlineKeyboardButton(f"پاسخ #{req_id}", callback_data=f"reply_buy_{req_id}")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_show_questions(update, context):
    query = update.callback_query
    c.execute("SELECT id, user_id, question_text FROM questions WHERE status='pending' ORDER BY id ASC")
    rows = c.fetchall()
    if not rows: return await query.edit_message_text("❓ هیچ سوال بی‌پاسخی وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]))
    text, buttons = "❓ سوالات پرسیده شده:\n\n", []
    for idx, row in enumerate(rows, 1):
        q_id, user_id, q_text = row
        text += f"#سوال {idx} (از کاربر {user_id}):\n{q_text}\n\n"
        buttons.append([InlineKeyboardButton(f"پاسخ به #سوال {idx}", callback_data=f"admin_answer_{q_id}"), InlineKeyboardButton(f"🚫 بن", callback_data=f"ban_{user_id}")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def start_answering_question(update, context, q_id):
    query = update.callback_query
    c.execute("SELECT user_id, question_text, status FROM questions WHERE id=?", (q_id,))
    row = c.fetchone()
    if not row or row[2] != 'pending': return await query.answer("قبلاً پاسخ داده شده است.", show_alert=True)
    context.user_data['admin_answer_q'] = {'user_id': row[0], 'q_id': q_id}
    context.user_data['state'] = 'admin_answering_q'
    await query.edit_message_text(f"متن سوال: {row[1]}\n\n✍️ پاسخ را بنویسید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="admin_back")]]))

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if any(data.startswith(p) for p in ('approve_ad_', 'reject_ad_', 'send_price_', 'reject_pricing_', 'reply_buy_', 'manage_ad_', 'admin_', 'admin_answer_', 'ban_', 'unban_')) and not is_admin(user_id): return await query.answer("دسترسی ندارید", show_alert=True)
    
    if data == "check_join":
        if await check_membership(user_id, context.bot): return await query.answer("هنوز عضو نشدید", show_alert=True)
        await show_user_menu(update, context)
    elif data == "restart":
        context.user_data.clear()
        if is_admin(user_id): await show_admin_panel(update, context)
        else: await show_user_menu(update, context)
    elif data == "mediator": await mediator_handler(update, context)
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
    elif data == "admin_ads": await admin_show_ads(update, context)
    elif data == "admin_pricing": await admin_show_pricing(update, context)
    elif data == "admin_buy": await admin_show_buy(update, context)
    elif data == "admin_questions": await admin_show_questions(update, context)
    elif data == "admin_bans": await admin_show_bans(update, context)
    elif data == "admin_broadcast":
        context.user_data['state'] = 'admin_broadcast'
        await query.edit_message_text("📢 پیام خود را برای ارسال همگانی بفرستید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="admin_back")]]))
    elif data.startswith("ban_"): await ban_user_action(update, context, int(data.split('_')[-1]))
    elif data.startswith("unban_"): await unban_user_action(update, context, int(data.split('_')[-1]))
    elif data.startswith("admin_answer_"): await start_answering_question(update, context, int(data.split('_')[-1]))
    elif data.startswith("manage_ad_"): await admin_manage_ad(update, context, int(data.split('_')[-1]))
    elif data.startswith("approve_ad_"): await approve_ad(update, context, int(data.split('_')[-1]))
    elif data.startswith("reject_ad_"): await reject_ad(update, context, int(data.split('_')[-1]))
    elif data.startswith("send_price_"): await start_send_price(update, context, int(data.split('_')[-1]))
    elif data.startswith("reject_pricing_"): await reject_pricing(update, context, int(data.split('_')[-1]))
    elif data.startswith("reply_buy_"): await start_reply_buy(update, context, int(data.split('_')[-1]))

async def message_handler(update, context):
    msg = update.message
    user_id = update.effective_user.id
    if is_banned(user_id): return await msg.reply_text("🚫 شما از ربات بن شده اید.")
    state = context.user_data.get('state')
    if not state: return
    
    if state == 'admin_send_price' and is_admin(user_id):
        info = context.user_data['admin_send_price_for']
        try:
            await context.bot.send_message(info['user_id'], f"💰 قیمت تقریبی اکانت شما:\n\n{msg.text}\n\nجهت خرید و واسطه گری: @Vasete_armin_azizi")
            await msg.reply_text(f"✅ قیمت برای کاربر {info['user_id']} ارسال شد.")
            c.execute("UPDATE pricing_requests SET status='answered' WHERE id=?", (info['request_id'],))
            conn.commit()
        except: pass
        context.user_data.clear()
        return
    if state == 'admin_reply_buy' and is_admin(user_id):
        info = context.user_data['admin_reply_buy_for']
        try:
            await context.bot.copy_message(chat_id=info['user_id'], from_chat_id=user_id, message_id=msg.message_id)
            await msg.reply_text(f"✅ پاسخ برای کاربر {info['user_id']} ارسال شد.")
            c.execute("UPDATE buy_requests SET status='answered' WHERE id=?", (info['request_id'],))
            conn.commit()
        except: pass
        context.user_data.clear()
        return
    if state == 'admin_answering_q' and is_admin(user_id):
        info = context.user_data['admin_answer_q']
        try:
            await context.bot.send_message(info['user_id'], f"📬 پاسخ سوال شما:\n\n{msg.text}")
            await msg.reply_text(f"✅ پاسخ برای کاربر {info['user_id']} ارسال شد.")
            c.execute("UPDATE questions SET status='answered', answer_text=? WHERE id=?", (msg.text, info['q_id']))
            conn.commit()
        except: pass
        context.user_data.clear()
        return
    if state == 'admin_broadcast' and is_admin(user_id):
        c.execute("SELECT user_id FROM users WHERE is_banned=0")
        users = c.fetchall()
        success, failed = 0, 0
        progress_msg = await msg.reply_text("⏳ در حال ارسال پیام همگانی...")
        for u in users:
            try:
                await context.bot.copy_message(chat_id=u[0], from_chat_id=user_id, message_id=msg.message_id)
                success += 1
            except: failed += 1
        await progress_msg.edit_text(f"✅ پایان.\nموفق: {success}\nناموفق: {failed}")
        context.user_data.clear()
        return
    if not is_admin(user_id):
        if await check_membership(user_id, context.bot):
            buttons = [[InlineKeyboardButton(f"🔗 عضویت در {ch}", url=link)] for ch, link in CHANNELS]
            buttons.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")])
            return await msg.reply_text("ابتدا عضو شوید:", reply_markup=InlineKeyboardMarkup(buttons))
    if state == 'question_waiting':
        c.execute("INSERT INTO questions (user_id, question_text) VALUES (?, ?)", (user_id, msg.text))
        conn.commit()
        await msg.reply_text("✅ سوال شما ثبت شد.\nپاسخ ادمین به زودی برای شما ارسال میشود.")
        try: await context.bot.send_message(ADMIN_ID, f"❓ سوال جدید از کاربر {user_id}:\n\n{msg.text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 بن کردن کاربر", callback_data=f"ban_{user_id}")]]))
        except: pass
        context.user_data.clear()
    elif state == 'ad_waiting':
        if msg.text:
            cleaned = extract_clean_form(msg.text)
            context.user_data['ad_text'] = context.user_data.get('ad_text', '') + '\n' + cleaned
            context.user_data['ad_text'] = context.user_data['ad_text'].strip()
        elif msg.photo or msg.document or msg.video:
            context.user_data['ad_messages'].append(msg.message_id)
        if not context.user_data.get('prompted'):
            context.user_data['prompted'] = True
            await msg.reply_text("📥 پیام دریافت شد.\nوقتی تمام شد دکمه زیر را بزنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ پایان و ارسال", callback_data="submit_ad")]]))
    elif state == 'pricing_waiting':
        if msg.text:
            cleaned = extract_clean_form(msg.text)
            context.user_data['pricing_text'] = context.user_data.get('pricing_text', '') + '\n' + cleaned
            context.user_data['pricing_text'] = context.user_data['pricing_text'].strip()
        elif msg.photo or msg.document or msg.video:
            context.user_data['pricing_messages'].append(msg.message_id)
        if not context.user_data.get('prompted'):
            context.user_data['prompted'] = True
            await msg.reply_text("📥 اطلاعات دریافت شد.\nوقتی تمام شد دکمه زیر را بزنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ پایان و ارسال", callback_data="submit_pricing")]]))
    elif state == 'buy_waiting':
        if msg.text: context.user_data['buy_link'] = msg.text
        elif msg.photo or msg.document or msg.video: context.user_data['buy_messages'].append(msg.message_id)
        if not context.user_data.get('prompted'):
            context.user_data['prompted'] = True
            await msg.reply_text("📥 دریافت شد.\nبرای ارسال نهایی دکمه زیر را بزنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ارسال", callback_data="submit_buy")]]))
    elif state == 'report_waiting':
        try: await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=msg.message_id)
        except: pass
        await msg.reply_text("گزارش شما ارسال شد ✅\nممنون از همکاری شما 🌹")
        context.user_data.clear()

app = FastAPI()
bot_app = Application.builder().token(BOT_TOKEN).updater(None).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CallbackQueryHandler(button_handler))
bot_app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO) & ~filters.COMMAND, message_handler))

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
