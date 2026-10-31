import os
import sys
import time
import sqlite3
import asyncio
import subprocess
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait
)

# ================= CONFIGURATION =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8570478868:AAGRM_w35z1kFdZbWLksjcPpB8M1l6TX41s")
OWNER_ID = int(os.environ.get("OWNER_ID", "8684812026"))      # Your Telegram User ID
API_ID = int(os.environ.get("API_ID", "35222361"))            # Telegram API_ID from my.telegram.org
API_HASH = os.environ.get("API_HASH", "37e25f9cff15259a786c55da0b0af3f3")  # Telegram API_HASH from my.telegram.org

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")
ULTIMATE_SCRIPT_DIR = os.path.join(BASE_DIR, "ultimate_master")
ULTIMATE_SCRIPT_PATH = os.path.join(ULTIMATE_SCRIPT_DIR, "ultimate_script.py")
DB_PATH = os.path.join(BASE_DIR, "akshu_hoster.db")

os.makedirs(WORKSPACES_DIR, exist_ok=True)
os.makedirs(ULTIMATE_SCRIPT_DIR, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Active hosted subprocesses: {user_id: subprocess.Popen}
active_processes = {}
# Conversation state tracker: {user_id: "STATE_NAME"}
user_states = {}
# Temporary Pyrogram login session tracker: {user_id: {"client": Client, "phone": str, "hash": str}}
pyro_login_sessions = {}
# Inline keypad buffer for OTP digits: {user_id: "123"}
otp_buffers = {}

# ================= DEDICATED ASYNCIO LOOP FOR PYROGRAM =================
pyro_loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_background_loop, args=(pyro_loop,), daemon=True).start()

def run_async(coro):
    """Executes a Pyrogram coroutine safely on the persistent background event loop."""
    future = asyncio.run_coroutine_threadsafe(coro, pyro_loop)
    return future.result(timeout=60)

# ================= DATABASE SETUP =================
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    verified INTEGER DEFAULT 0,
                    client_bot_token TEXT DEFAULT '',
                    string_session TEXT DEFAULT '',
                    phone_number TEXT DEFAULT '',
                    custom_script_name TEXT DEFAULT '',
                    hosting_mode TEXT DEFAULT 'userbot',
                    status TEXT DEFAULT 'stopped'
                )''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def register_user(user_id, username):
    if not get_user(user_id):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()

def update_user_field(user_id, field, value):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

init_db()

# ================= DEFAULT FEATURE-RICH ULTIMATE SCRIPT =================
DEFAULT_ULTIMATE_CODE = '''import os
import sys
import time
import asyncio
import psutil
import pyrogram
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
STRING_SESSION = os.environ.get("STRING_SESSION", "")
CLIENT_BOT_TOKEN = os.environ.get("CLIENT_BOT_TOKEN", "")
HOSTED_USER_ID = os.environ.get("HOSTED_USER_ID", "Unknown")

START_TIME = time.time()

if STRING_SESSION:
    MODE = "USERBOT"
    app = Client("akshu_userbot", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION)
    CMD_FILTER = filters.me
else:
    MODE = "BOT"
    app = Client("akshu_bot", api_id=API_ID, api_hash=API_HASH, bot_token=CLIENT_BOT_TOKEN)
    CMD_FILTER = filters.incoming

def get_readable_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d > 0:
        parts.append(f"{d}d")
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

@app.on_message(filters.command("alive", prefixes=[".", "/"]) & CMD_FILTER)
async def alive_cmd(client, message):
    uptime = get_readable_time(int(time.time() - START_TIME))
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    text = (
        "⚡ **Akshu Host — Ultimate Script Active**\\n\\n"
        f"🤖 **Mode:** `{MODE}`\\n"
        f"👤 **Host ID:** `{HOSTED_USER_ID}`\\n"
        f"⏱ **Uptime:** `{uptime}`\\n"
        f"💻 **CPU / RAM:** `{cpu}%` | `{ram}%`\\n"
        f"🐍 **Python:** `{sys.version.split()[0]}`\\n"
        f"🔥 **Pyrogram:** `{pyrogram.__version__}`"
    )
    await message.reply_text(text)

@app.on_message(filters.command("ping", prefixes=[".", "/"]) & CMD_FILTER)
async def ping_cmd(client, message):
    start = time.perf_counter()
    reply = await message.reply_text("🏓 **Pinging...**")
    ms = (time.perf_counter() - start) * 1000
    await reply.edit_text(f"🏓 **Pong!** `{ms:.2f} ms`")

@app.on_message(filters.command("info", prefixes=[".", "/"]) & CMD_FILTER)
async def info_cmd(client, message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if not target:
        await message.reply_text("❌ Could not resolve user details.")
        return
    info_text = (
        "👤 **User Information**\\n\\n"
        f"• **ID:** `{target.id}`\\n"
        f"• **First Name:** `{target.first_name}`\\n"
        f"• **Username:** @{target.username or 'None'}\\n"
        f"• **DC ID:** `{getattr(target, 'dc_id', 'N/A')}`\\n"
        f"• **Is Bot:** `{target.is_bot}`"
    )
    await message.reply_text(info_text)

@app.on_message(filters.command("stats", prefixes=[".", "/"]) & CMD_FILTER)
async def stats_cmd(client, message):
    if MODE != "USERBOT":
        await message.reply_text("ℹ️ `.stats` is available in Userbot mode only.")
        return
    status = await message.reply_text("📊 **Scanning dialogs...**")
    privates = groups = supergroups = channels = bots = 0
    async for dialog in client.get_dialogs():
        ctype = dialog.chat.type
        if ctype == ChatType.PRIVATE:
            privates += 1
        elif ctype == ChatType.BOT:
            bots += 1
        elif ctype == ChatType.GROUP:
            groups += 1
        elif ctype == ChatType.SUPERGROUP:
            supergroups += 1
        elif ctype == ChatType.CHANNEL:
            channels += 1
    await status.edit_text(
        "📊 **Account Dialog Statistics**\\n\\n"
        f"👤 **Private Chats:** `{privates}`\\n"
        f"👥 **Groups:** `{groups}`\\n"
        f"🌐 **Supergroups:** `{supergroups}`\\n"
        f"📢 **Channels:** `{channels}`\\n"
        f"🤖 **Bots:** `{bots}`"
    )

@app.on_message(filters.command("broadcast", prefixes=[".", "/"]) & CMD_FILTER)
async def broadcast_cmd(client, message):
    if MODE != "USERBOT":
        await message.reply_text("ℹ️ `.broadcast` requires Userbot mode.")
        return
    if not message.reply_to_message:
        await message.reply_text("⚠️ Reply to a message with `.broadcast` to send it across your groups.")
        return
    status = await message.reply_text("📡 **Starting rate-limited broadcast...**")
    sent = failed = 0
    async for dialog in client.get_dialogs():
        if dialog.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            try:
                await message.reply_to_message.copy(dialog.chat.id)
                sent += 1
                await asyncio.sleep(1.5)  # Safe delay to avoid FloodWait
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
            except Exception:
                failed += 1
    await status.edit_text(f"✅ **Broadcast Complete!**\\n• Sent: `{sent}`\\n• Failed: `{failed}`")

print(f"[{MODE}] Ultimate Script started for user {HOSTED_USER_ID}...")
app.run()
'''

if not os.path.exists(ULTIMATE_SCRIPT_PATH):
    with open(ULTIMATE_SCRIPT_PATH, "w", encoding="utf-8") as f:
        f.write(DEFAULT_ULTIMATE_CODE)

# ================= PROCESS MANAGEMENT ENGINE =================
def start_user_bot(user_id):
    user_data = get_user(user_id)
    if not user_data:
        return False, "User record not found."

    _, username, verified, client_token, string_session, phone, custom_script, mode, _ = user_data

    if user_id in active_processes and active_processes[user_id].poll() is None:
        return False, "⚠️ A session is already running! Stop it first."

    user_workspace = os.path.join(WORKSPACES_DIR, str(user_id))
    os.makedirs(user_workspace, exist_ok=True)
    log_file_path = os.path.join(user_workspace, "session.log")

    env = os.environ.copy()
    env["API_ID"] = str(API_ID)
    env["API_HASH"] = API_HASH
    env["CLIENT_BOT_TOKEN"] = client_token
    env["BOT_TOKEN"] = client_token
    env["STRING_SESSION"] = string_session
    env["HOSTED_USER_ID"] = str(user_id)

    if mode == "userbot":
        if not string_session:
            return False, "❌ Please login with your Phone & OTP first!"
        env["CLIENT_BOT_TOKEN"] = ""
        script_to_run = ULTIMATE_SCRIPT_PATH
    elif mode == "ultimate":
        if not client_token:
            return False, "❌ Please set your Bot Token first!"
        env["STRING_SESSION"] = ""
        script_to_run = ULTIMATE_SCRIPT_PATH
    else:
        if not custom_script:
            return False, "❌ Please upload your custom .py file first!"
        script_to_run = os.path.join(user_workspace, custom_script)
        if not os.path.exists(script_to_run):
            return False, "❌ Uploaded script file not found."

    log_file = open(log_file_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", script_to_run],
        cwd=user_workspace,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True
    )
    active_processes[user_id] = proc
    update_user_field(user_id, "status", "running")

    return True, f"✅ Session started! (PID: <code>{proc.pid}</code> | Mode: <b>{mode.upper()}</b>)"

def stop_user_bot(user_id):
    if user_id not in active_processes or active_processes[user_id].poll() is not None:
        update_user_field(user_id, "status", "stopped")
        return False, "⚠️ No active session is running."

    proc = active_processes[user_id]
    proc.terminate()
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()

    del active_processes[user_id]
    update_user_field(user_id, "status", "stopped")
    return True, "🛑 Session stopped cleanly."

# ================= PYROGRAM INTERACTIVE LOGIN COROUTINES =================
async def _pyro_send_otp(user_id, phone_number):
    if user_id in pyro_login_sessions:
        try:
            await pyro_login_sessions[user_id]["client"].disconnect()
        except Exception:
            pass

    client = Client(
        name=f"login_{user_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True
    )
    await client.connect()
    sent_code = await client.send_code(phone_number)
    pyro_login_sessions[user_id] = {
        "client": client,
        "phone": phone_number,
        "hash": sent_code.phone_code_hash
    }
    return True

async def _pyro_verify_otp(user_id, otp_code):
    session_info = pyro_login_sessions.get(user_id)
    if not session_info:
        return "EXPIRED", None

    client = session_info["client"]
    phone = session_info["phone"]
    phone_hash = session_info["hash"]

    try:
        await client.sign_in(phone_number=phone, phone_code_hash=phone_hash, phone_code=otp_code)
        string_session = await client.export_session_string()
        await client.disconnect()
        pyro_login_sessions.pop(user_id, None)
        return "SUCCESS", string_session
    except SessionPasswordNeeded:
        return "2FA_REQUIRED", None

async def _pyro_verify_2fa(user_id, password):
    session_info = pyro_login_sessions.get(user_id)
    if not session_info:
        return "EXPIRED", None

    client = session_info["client"]
    await client.check_password(password)
    string_session = await client.export_session_string()
    await client.disconnect()
    pyro_login_sessions.pop(user_id, None)
    return "SUCCESS", string_session

# ================= INLINE MENUS & NUMERIC OTP KEYPAD =================
def otp_keypad_keyboard():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("1️⃣", callback_data="otp_digit_1"),
        InlineKeyboardButton("2️⃣", callback_data="otp_digit_2"),
        InlineKeyboardButton("3️⃣", callback_data="otp_digit_3"),
        InlineKeyboardButton("4️⃣", callback_data="otp_digit_4"),
        InlineKeyboardButton("5️⃣", callback_data="otp_digit_5"),
        InlineKeyboardButton("6️⃣", callback_data="otp_digit_6"),
        InlineKeyboardButton("7️⃣", callback_data="otp_digit_7"),
        InlineKeyboardButton("8️⃣", callback_data="otp_digit_8"),
        InlineKeyboardButton("9️⃣", callback_data="otp_digit_9"),
        InlineKeyboardButton("⌫ Back", callback_data="otp_back"),
        InlineKeyboardButton("0️⃣", callback_data="otp_digit_0"),
        InlineKeyboardButton("🔄 Clear", callback_data="otp_clear")
    )
    kb.add(
        InlineKeyboardButton("✅ Submit OTP", callback_data="otp_submit"),
        InlineKeyboardButton("🚫 Cancel", callback_data="back_main")
    )
    return kb

def format_otp_display(user_id):
    buf = otp_buffers.get(user_id, "")
    padded = [buf[i] if i < len(buf) else "_" for i in range(5)]
    return " ".join(padded)

def main_menu_keyboard(user_id):
    user_data = get_user(user_id)
    mode = user_data[7] if user_data else "userbot"
    is_running = user_id in active_processes and active_processes[user_id].poll() is None
    status_emoji = "🟢 Running" if is_running else "🔴 Stopped"

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("▶️ Start Session", callback_data="start_session"),
        InlineKeyboardButton("🛑 Stop Session", callback_data="stop_session")
    )
    kb.add(
        InlineKeyboardButton("📱 Host Userbot (OTP Keypad)", callback_data="login_userbot_otp"),
        InlineKeyboardButton("🤖 Host via Bot Token", callback_data="set_mode_ultimate")
    )
    kb.add(
        InlineKeyboardButton("📂 Upload Custom .py", callback_data="upload_custom"),
        InlineKeyboardButton("⚙️ Host Settings", callback_data="host_settings")
    )
    kb.add(
        InlineKeyboardButton("📦 Pip Installer", callback_data="pip_installer"),
        InlineKeyboardButton("💻 Live Terminal", callback_data="terminal_cmd")
    )
    kb.add(
        InlineKeyboardButton("📜 View Session Logs", callback_data="view_logs"),
        InlineKeyboardButton(f"📊 {status_emoji} ({mode.upper()})", callback_data="refresh_menu")
    )
    if user_id == OWNER_ID:
        kb.add(InlineKeyboardButton("👑 Owner Control Panel", callback_data="owner_panel"))
    return kb

def owner_panel_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📤 Upload Ultimate Script", callback_data="owner_upload_ultimate"),
        InlineKeyboardButton("📡 Active PIDs & Sessions", callback_data="owner_active_list")
    )
    kb.add(
        InlineKeyboardButton("🔐 Send Stdin to Process", callback_data="owner_send_stdin"),
        InlineKeyboardButton("👥 Registered Users Summary", callback_data="owner_users_summary")
    )
    kb.add(InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_main"))
    return kb

# ================= HANDLERS =================
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    register_user(user_id, username)
    user_states.pop(user_id, None)
    otp_buffers.pop(user_id, None)

    user_data = get_user(user_id)
    verified = user_data[2]

    if user_id == OWNER_ID and not verified:
        update_user_field(user_id, "verified", 1)
        verified = 1

    if not verified:
        bot.send_message(
            message.chat.id,
            "🔥 <b>Welcome to Akshu Jhaate Host Bot!</b>\n\n"
            "⚠️ <b>Verification Required:</b>\n"
            "Apne Jhato Ki Pic Upload karo For Open hosting dashboard.\n\n"
            "📸 <i>Send the photo now to unlock access...</i>"
        )
        user_states[user_id] = "WAITING_VERIFICATION_PIC"
        return

    bot.send_message(
        message.chat.id,
        "⚡ <b>Akshu Jhaate Host Bot — Control Dashboard</b>\n\n"
        "Choose an option below to login your Userbot via the Inline OTP Keypad, bind a Bot Token, or manage your running session:",
        reply_markup=main_menu_keyboard(user_id)
    )

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    register_user(user_id, username)
    user_data = get_user(user_id)

    if user_data[2] == 0 or user_states.get(user_id) == "WAITING_VERIFICATION_PIC":
        update_user_field(user_id, "verified", 1)
        user_states.pop(user_id, None)

        bot.reply_to(
            message,
            "✅ <b>Verification Complete!</b>\nYour hosting dashboard is now unlocked.",
            reply_markup=main_menu_keyboard(user_id)
        )

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    user_data = get_user(user_id)

    if not user_data or (user_data[2] == 0 and user_id != OWNER_ID):
        bot.answer_callback_query(call.id, "❌ Upload your verification photo first!", show_alert=True)
        return

    data = call.data

    # --- INLINE OTP KEYPAD HANDLERS ---
    if data.startswith("otp_"):
        if user_states.get(user_id) != "WAITING_OTP_CODE":
            bot.answer_callback_query(call.id, "⚠️ No active OTP session.", show_alert=True)
            return

        current_buf = otp_buffers.get(user_id, "")

        if data.startswith("otp_digit_"):
            digit = data.split("_")[-1]
            if len(current_buf) < 6:
                otp_buffers[user_id] = current_buf + digit
            bot.answer_callback_query(call.id, f"Entered: {otp_buffers[user_id]}")
            bot.edit_message_text(
                f"📩 <b>OTP Sent! (Step 2/3)</b>\n\n"
                f"Tap the keypad below to enter your 5-digit Telegram login code without typing it in chat:\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=otp_keypad_keyboard()
            )
            return

        elif data == "otp_back":
            otp_buffers[user_id] = current_buf[:-1]
            bot.answer_callback_query(call.id, "Deleted last digit")
            bot.edit_message_text(
                f"📩 <b>OTP Sent! (Step 2/3)</b>\n\n"
                f"Tap the keypad below to enter your 5-digit Telegram login code:\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=otp_keypad_keyboard()
            )
            return

        elif data == "otp_clear":
            otp_buffers[user_id] = ""
            bot.answer_callback_query(call.id, "Cleared")
            bot.edit_message_text(
                f"📩 <b>OTP Sent! (Step 2/3)</b>\n\n"
                f"Tap the keypad below to enter your 5-digit Telegram login code:\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=otp_keypad_keyboard()
            )
            return

        elif data == "otp_submit":
            if len(current_buf) < 5:
                bot.answer_callback_query(call.id, "❌ Please enter all 5 digits first!", show_alert=True)
                return

            bot.edit_message_text(
                "🔐 <b>Verifying OTP with Telegram...</b>",
                call.message.chat.id,
                call.message.message_id
            )
            try:
                status, session_str = run_async(_pyro_verify_otp(user_id, current_buf))
                otp_buffers.pop(user_id, None)

                if status == "2FA_REQUIRED":
                    user_states[user_id] = "WAITING_2FA_PASSWORD"
                    bot.edit_message_text(
                        "🔒 <b>Two-Step Verification Enabled (Step 3/3)</b>\n\n"
                        "Please send your <b>2FA Cloud Password</b> now to complete userbot login:",
                        call.message.chat.id,
                        call.message.message_id
                    )
                elif status == "SUCCESS":
                    user_states.pop(user_id, None)
                    update_user_field(user_id, "string_session", session_str)
                    update_user_field(user_id, "hosting_mode", "userbot")

                    ok, start_msg = start_user_bot(user_id)
                    bot.edit_message_text(
                        f"✅ <b>Userbot Logged In Successfully!</b>\n{start_msg}\n\n"
                        f"<i>Try typing <code>.alive</code> or <code>.ping</code> in any chat!</i>",
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=main_menu_keyboard(user_id)
                    )
            except PhoneCodeInvalid:
                otp_buffers[user_id] = ""
                bot.edit_message_text(
                    f"❌ <b>Invalid OTP code!</b> Please enter the digits again:\n\n"
                    f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=otp_keypad_keyboard()
                )
            except PhoneCodeExpired:
                user_states.pop(user_id, None)
                otp_buffers.pop(user_id, None)
                bot.edit_message_text(
                    "❌ <b>OTP code expired!</b> Click <b>Host Userbot (OTP Keypad)</b> to request a new code.",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=main_menu_keyboard(user_id)
                )
            except Exception as e:
                user_states.pop(user_id, None)
                otp_buffers.pop(user_id, None)
                bot.edit_message_text(
                    f"❌ Login Error: <code>{e}</code>",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=main_menu_keyboard(user_id)
                )
            return

    # --- STANDARD DASHBOARD CALLBACKS ---
    if data in ("refresh_menu", "back_main"):
        user_states.pop(user_id, None)
        otp_buffers.pop(user_id, None)
        bot.edit_message_text(
            "⚡ <b>Akshu Jhaate Host Bot — Control Dashboard</b>\nSelect an option below:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu_keyboard(user_id)
        )

    elif data == "start_session":
        ok, msg = start_user_bot(user_id)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id))

    elif data == "stop_session":
        ok, msg = stop_user_bot(user_id)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id))

    elif data == "login_userbot_otp":
        update_user_field(user_id, "hosting_mode", "userbot")
        user_states[user_id] = "WAITING_PHONE_NUMBER"
        bot.send_message(
            call.message.chat.id,
            "📱 <b>Pyrogram Userbot Login (Step 1/3)</b>\n\n"
            "Send your Telegram <b>Phone Number</b> with country code.\n"
            "Example: <code>+919876543210</code>\n\n"
            "<i>Send /cancel to abort at any time.</i>"
        )

    elif data == "set_mode_ultimate":
        update_user_field(user_id, "hosting_mode", "ultimate")
        user_states[user_id] = "WAITING_CLIENT_TOKEN"
        bot.send_message(
            call.message.chat.id,
            "🤖 <b>Bot Token Hosting Mode</b>\n\n"
            "Send your <b>Bot Token</b> from @BotFather now to host the Ultimate Script on your bot:"
        )

    elif data == "upload_custom":
        update_user_field(user_id, "hosting_mode", "custom")
        user_states[user_id] = "WAITING_CUSTOM_FILE"
        bot.send_message(
            call.message.chat.id,
            "📂 <b>Custom File Hosting Mode</b>\n\n"
            "Upload your <code>.py</code> file now as a document."
        )

    elif data == "host_settings":
        _, username, _, token, s_session, phone, script_name, mode, status = user_data
        has_session = "✅ Connected" if s_session else "❌ Not Logged In"
        masked_token = (token[:8] + "...") if len(token) > 10 else ("Set" if token else "Not Set")

        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("📱 Login / Replace Userbot (Keypad)", callback_data="login_userbot_otp"),
            InlineKeyboardButton("🔑 Set / Change Bot Token", callback_data="set_mode_ultimate"),
            InlineKeyboardButton("🔄 Cycle Mode (Userbot / Bot / Custom)", callback_data="toggle_mode"),
            InlineKeyboardButton("🗑️ Logout & Wipe My Session", callback_data="wipe_session"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        )
        bot.edit_message_text(
            f"⚙️ <b>Host Settings</b>\n\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📱 <b>Phone:</b> <code>{phone or 'None'}</code>\n"
            f"🔐 <b>Userbot Session:</b> <code>{has_session}</code>\n"
            f"🤖 <b>Bot Token:</b> <code>{masked_token}</code>\n"
            f"📄 <b>Custom Script:</b> <code>{script_name or 'None'}</code>\n"
            f"🚀 <b>Active Mode:</b> <code>{mode.upper()}</code>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb
        )

    elif data == "wipe_session":
        stop_user_bot(user_id)
        update_user_field(user_id, "string_session", "")
        update_user_field(user_id, "client_bot_token", "")
        bot.answer_callback_query(call.id, "✅ Your saved session and token have been wiped.", show_alert=True)
        handle_callbacks(call)

    elif data == "toggle_mode":
        modes = ["userbot", "ultimate", "custom"]
        curr = user_data[7] if user_data[7] in modes else "userbot"
        next_mode = modes[(modes.index(curr) + 1) % len(modes)]
        update_user_field(user_id, "hosting_mode", next_mode)
        bot.answer_callback_query(call.id, f"Mode switched to {next_mode.upper()}")
        handle_callbacks(call)

    elif data == "pip_installer":
        if user_id != OWNER_ID:
            bot.answer_callback_query(call.id, "🔒 Restricted to Bot Owner for server safety.", show_alert=True)
            return
        user_states[user_id] = "WAITING_PIP_PACKAGES"
        bot.send_message(call.message.chat.id, "📦 Send package names to install (e.g. <code>requests motor</code>):")

    elif data == "terminal_cmd":
        if user_id != OWNER_ID:
            bot.answer_callback_query(call.id, "🔒 Terminal is restricted to the Bot Owner.", show_alert=True)
            return
        user_states[user_id] = "WAITING_TERMINAL_CMD"
        bot.send_message(call.message.chat.id, "💻 Send shell command to execute (or /cancel):")

    elif data == "view_logs":
        log_path = os.path.join(WORKSPACES_DIR, str(user_id), "session.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, "No logs generated yet!", show_alert=True)
            return
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            logs = f.read()[-3500:] or "Log file is empty."
        bot.send_message(call.message.chat.id, f"📜 <b>Session Logs:</b>\n<pre>{logs}</pre>")

    # ================= OWNER PANEL =================
    elif data == "owner_panel" and user_id == OWNER_ID:
        bot.edit_message_text(
            "👑 <b>Owner Control Panel</b>\nManage the master script and monitor active processes:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=owner_panel_keyboard()
        )

    elif data == "owner_upload_ultimate" and user_id == OWNER_ID:
        user_states[user_id] = "WAITING_OWNER_ULTIMATE_SCRIPT"
        bot.send_message(call.message.chat.id, "📤 Upload the new master <code>.py</code> script now:")

    elif data == "owner_active_list" and user_id == OWNER_ID:
        msg = "📡 <b>Active Hosted Processes:</b>\n\n"
        count = 0
        for uid, proc in list(active_processes.items()):
            if proc.poll() is None:
                count += 1
                u = get_user(uid)
                msg += f"• User: <code>{uid}</code> (@{u[1]}) | PID: <code>{proc.pid}</code> | Mode: <code>{u[7]}</code>\n"
        if count == 0:
            msg += "<i>No processes running.</i>"
        bot.send_message(call.message.chat.id, msg)

    elif data == "owner_send_stdin" and user_id == OWNER_ID:
        user_states[user_id] = "WAITING_OWNER_STDIN"
        bot.send_message(call.message.chat.id, "🔐 Send in format: <code>USER_ID INPUT_STRING</code>")

    elif data == "owner_users_summary" and user_id == OWNER_ID:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, username, verified, hosting_mode, status FROM users")
        rows = c.fetchall()
        conn.close()
        out = "👥 <b>Registered Users Summary:</b>\n\n"
        for r in rows:
            out += f"👤 <code>{r[0]}</code> (@{r[1]}) | Verified: {r[2]} | Mode: <code>{r[3]}</code> | Status: <code>{r[4]}</code>\n"
        bot.send_message(call.message.chat.id, out[:4000])

# ================= TEXT & LOGIN HANDLER =================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text_states(message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_states.get(user_id)

    if text == "/cancel":
        user_states.pop(user_id, None)
        otp_buffers.pop(user_id, None)
        bot.reply_to(message, "🚫 Action cancelled.", reply_markup=main_menu_keyboard(user_id))
        return

    if state == "WAITING_VERIFICATION_PIC":
        bot.reply_to(message, "📸 Please upload your verification photo first!")
        return

    # --- STEP 1: PHONE NUMBER -> LAUNCHES INLINE OTP KEYPAD ---
    elif state == "WAITING_PHONE_NUMBER":
        phone = text.replace(" ", "")
        if not phone.startswith("+"):
            bot.reply_to(message, "❌ Include your country code starting with <code>+</code> (e.g., <code>+919876543210</code>).")
            return

        wait_msg = bot.reply_to(message, "⏳ Requesting login code from Telegram...")
        try:
            run_async(_pyro_send_otp(user_id, phone))
            update_user_field(user_id, "phone_number", phone)
            user_states[user_id] = "WAITING_OTP_CODE"
            otp_buffers[user_id] = ""

            bot.edit_message_text(
                f"📩 <b>OTP Sent! (Step 2/3)</b>\n\n"
                f"Tap the numeric keypad below to enter your 5-digit Telegram login code (do not type it in chat):\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                message.chat.id,
                wait_msg.message_id,
                reply_markup=otp_keypad_keyboard()
            )
        except FloodWait as fw:
            user_states.pop(user_id, None)
            bot.edit_message_text(f"❌ Telegram FloodWait: Try again in {fw.value} seconds.", message.chat.id, wait_msg.message_id)
        except Exception as e:
            user_states.pop(user_id, None)
            bot.edit_message_text(f"❌ Failed to send OTP: <code>{e}</code>", message.chat.id, wait_msg.message_id)

    # --- STEP 3: 2FA CLOUD PASSWORD ---
    elif state == "WAITING_2FA_PASSWORD":
        password = text
        # Delete the user's plaintext password message from chat for privacy
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

        wait_msg = bot.send_message(message.chat.id, "🔐 Verifying 2FA Password...")
        try:
            status, session_str = run_async(_pyro_verify_2fa(user_id, password))
            if status == "SUCCESS":
                user_states.pop(user_id, None)
                update_user_field(user_id, "string_session", session_str)
                update_user_field(user_id, "hosting_mode", "userbot")

                ok, start_msg = start_user_bot(user_id)
                bot.edit_message_text(
                    f"✅ <b>2FA Verified & Userbot Started!</b>\n{start_msg}\n\n"
                    f"<i>Try typing <code>.alive</code> or <code>.ping</code> in any chat!</i>",
                    message.chat.id,
                    wait_msg.message_id,
                    reply_markup=main_menu_keyboard(user_id)
                )
        except PasswordHashInvalid:
            bot.edit_message_text("❌ Incorrect 2FA password! Try sending your password again:", message.chat.id, wait_msg.message_id)
        except Exception as e:
            user_states.pop(user_id, None)
            bot.edit_message_text(f"❌ 2FA Error: <code>{e}</code>", message.chat.id, wait_msg.message_id, reply_markup=main_menu_keyboard(user_id))

    # --- BOT TOKEN MODE ---
    elif state == "WAITING_CLIENT_TOKEN":
        update_user_field(user_id, "client_bot_token", text)
        update_user_field(user_id, "hosting_mode", "ultimate")
        user_states.pop(user_id, None)

        ok, start_msg = start_user_bot(user_id)
        bot.reply_to(message, f"✅ <b>Bot Token Saved!</b>\n{start_msg}", reply_markup=main_menu_keyboard(user_id))

    # --- PIP INSTALLER (OWNER ONLY) ---
    elif state == "WAITING_PIP_PACKAGES" and user_id == OWNER_ID:
        user_states.pop(user_id, None)
        status_msg = bot.reply_to(message, f"⏳ Running <code>pip install {text}</code>...")
        try:
            res = subprocess.run([sys.executable, "-m", "pip", "install"] + text.split(), capture_output=True, text=True, timeout=120)
            output = (res.stdout + "\n" + res.stderr)[-3500:]
            bot.edit_message_text(f"📦 <b>Pip Output:</b>\n<pre>{output}</pre>", message.chat.id, status_msg.message_id, reply_markup=main_menu_keyboard(user_id))
        except Exception as e:
            bot.edit_message_text(f"❌ Error: <code>{e}</code>", message.chat.id, status_msg.message_id)

    # --- LIVE TERMINAL (OWNER ONLY) ---
    elif state == "WAITING_TERMINAL_CMD" and user_id == OWNER_ID:
        user_workspace = os.path.join(WORKSPACES_DIR, str(user_id))
        os.makedirs(user_workspace, exist_ok=True)
        try:
            res = subprocess.run(text, shell=True, cwd=user_workspace, capture_output=True, text=True, timeout=30)
            output = (res.stdout + "\n" + res.stderr).strip() or "✅ Executed (no output)."
            bot.reply_to(message, f"💻 <b>Output:</b>\n<pre>{output[-3500:]}</pre>\n<i>Send next command or /cancel.</i>")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: <code>{e}</code>")

    # --- OWNER STDIN FORWARDING ---
    elif state == "WAITING_OWNER_STDIN" and user_id == OWNER_ID:
        user_states.pop(user_id, None)
        parts = text.split(" ", 1)
        if len(parts) == 2 and int(parts[0]) in active_processes:
            proc = active_processes[int(parts[0])]
            if proc.poll() is None:
                proc.stdin.write(parts[1] + "\n")
                proc.stdin.flush()
                bot.reply_to(message, "✅ Sent to process stdin!")
                return
        bot.reply_to(message, "❌ Process not active or invalid format.")

# ================= DOCUMENT UPLOADS =================
@bot.message_handler(content_types=['document'])
def handle_document(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if state == "WAITING_OWNER_ULTIMATE_SCRIPT" and user_id == OWNER_ID:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(ULTIMATE_SCRIPT_PATH, "wb") as f:
            f.write(downloaded)
        user_states.pop(user_id, None)
        bot.reply_to(message, "✅ <b>Ultimate Script Updated!</b>", reply_markup=owner_panel_keyboard())

    elif state == "WAITING_CUSTOM_FILE":
        if not message.document.file_name.endswith(".py"):
            bot.reply_to(message, "❌ Only <code>.py</code> files are allowed.")
            return
        user_workspace = os.path.join(WORKSPACES_DIR, str(user_id))
        os.makedirs(user_workspace, exist_ok=True)
        file_path = os.path.join(user_workspace, message.document.file_name)

        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(file_path, "wb") as f:
            f.write(downloaded)

        update_user_field(user_id, "custom_script_name", message.document.file_name)
        update_user_field(user_id, "hosting_mode", "custom")
        user_states.pop(user_id, None)
        bot.reply_to(message, f"✅ Saved <code>{message.document.file_name}</code>! Click <b>Start Session</b> to launch.", reply_markup=main_menu_keyboard(user_id))

print("🔥 Akshu Jhaate Host Bot (Inline Keypad + Ultimate Userbot + Railway Ready) is live...")
bot.infinity_polling()
