import os
import sys
import ast
import asyncio
import subprocess
import threading
import telebot
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait
)

from config import (
    BOT_TOKEN,
    OWNER_ID,
    API_ID,
    API_HASH,
    MAX_BOTS_PER_USER,
    WORKSPACES_DIR,
    USERBOT_MASTER_PATH,
    TOKEN_BOT_MASTER_PATH,
    get_ist_now,
    format_uptime
)
from database import (
    init_db,
    register_user,
    get_user,
    set_user_verified,
    get_user_instances,
    get_instance,
    count_user_instances,
    add_bot_instance,
    delete_bot_instance,
    get_all_users_summary
)
from process_manager import (
    active_processes,
    is_instance_running,
    start_instance,
    stop_instance,
    stop_all_user_instances,
    get_instance_logs,
    run_mini_terminal,
    recover_running_instances,
    start_watchdog_thread
)
from keyboards import (
    main_menu_keyboard,
    user_bots_keyboard,
    slot_control_keyboard,
    mini_terminal_keyboard,
    otp_keypad_keyboard,
    owner_panel_keyboard
)

init_db()
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# State dictionaries
user_states = {}
pyro_login_sessions = {}
otp_buffers = {}

# ================= AST SECURITY SCANNER ENGINE =================
BANNED_MODULES = {
    "subprocess", "pty", "shutil", "ctypes", "importlib",
    "pickle", "cPickle", "marshal", "builtins", "__builtin__"
}

BANNED_BUILTINS = {
    "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr"
}

BANNED_OS_ATTRIBUTES = {
    "system", "popen", "fork", "forkpty", "kill", "killpg",
    "remove", "unlink", "rmdir", "removedirs", "chmod", "chown", "chroot",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe"
}

PROTECTED_PATTERNS = (
    "akshu_hoster.db",
    "master_userbot.py",
    "master_bot.py",
    "master_scripts",
    "../",
    "..\\"
)


class ASTSecurityScanner(ast.NodeVisitor):
    """Walks the Python Abstract Syntax Tree to detect dangerous calls and imports."""

    def __init__(self):
        self.violations = []
        self.os_aliases = {"os", "posix", "nt"}

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            root_mod = alias.name.split(".")[0]
            if root_mod in BANNED_MODULES:
                self.violations.append(
                    f"Line {node.lineno}: Restricted module import '{alias.name}' is blocked."
                )
            if root_mod in ("os", "posix", "nt") and alias.asname:
                self.os_aliases.add(alias.asname)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            root_mod = node.module.split(".")[0]
            if root_mod in BANNED_MODULES:
                self.violations.append(
                    f"Line {node.lineno}: Restricted import from '{node.module}' is blocked."
                )
            if root_mod in ("os", "posix", "nt"):
                for alias in node.names:
                    if alias.name in BANNED_OS_ATTRIBUTES or alias.name == "*":
                        self.violations.append(
                            f"Line {node.lineno}: Importing 'os.{alias.name}' is blocked."
                        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # 1. Check direct builtin calls: eval(), exec(), __import__(), system()
        if isinstance(node.func, ast.Name):
            fn_name = node.func.id
            if fn_name in BANNED_BUILTINS:
                self.violations.append(
                    f"Line {node.lineno}: Dynamic execution call '{fn_name}()' is blocked."
                )
            elif fn_name in BANNED_OS_ATTRIBUTES:
                self.violations.append(
                    f"Line {node.lineno}: System call '{fn_name}()' is blocked."
                )

        # 2. Check attribute calls: os.system(), subprocess.Popen(), os.popen()
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in BANNED_OS_ATTRIBUTES:
                self.violations.append(
                    f"Line {node.lineno}: Restricted system method '.{attr_name}()' is blocked."
                )
            elif isinstance(node.func.value, ast.Name):
                caller = node.func.value.id
                if caller in BANNED_MODULES or (caller in self.os_aliases and attr_name in BANNED_OS_ATTRIBUTES):
                    self.violations.append(
                        f"Line {node.lineno}: Disallowed call '{caller}.{attr_name}()' is blocked."
                    )

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # Block access to dunder internals used for sandbox escapes
        if node.attr in ("__subclasses__", "__globals__", "__builtins__", "__code__", "__mro__"):
            self.violations.append(
                f"Line {node.lineno}: Access to internal attribute '{node.attr}' is blocked."
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        # Inspect string literals for attempts to read hoster DB or traverse directories
        if isinstance(node.value, str):
            low_val = node.value.lower()
            for pattern in PROTECTED_PATTERNS:
                if pattern in low_val:
                    self.violations.append(
                        f"Line {node.lineno}: Unauthorized path reference '{pattern}' is blocked."
                    )
        self.generic_visit(node)


def scan_python_code(code_bytes: bytes):
    """
    Parses and scans uploaded Python bytes.
    Returns (is_safe: bool, violations: list[str])
    """
    try:
        source_text = code_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False, ["File is not valid UTF-8 encoded Python text."]

    try:
        tree = ast.parse(source_text)
    except SyntaxError as e:
        return False, [f"SyntaxError on line {e.lineno}: {e.msg}"]
    except Exception as e:
        return False, [f"Failed to parse Python AST: {e}"]

    scanner = ASTSecurityScanner()
    scanner.visit(tree)
    return len(scanner.violations) == 0, scanner.violations


# ================= BACKGROUND ASYNCIO LOOP FOR PYROGRAM =================
pyro_loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_background_loop, args=(pyro_loop,), daemon=True).start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, pyro_loop)
    return future.result(timeout=60)

# ================= PYROGRAM LOGIN COROUTINES =================
async def _pyro_send_otp(user_id: int, phone_number: str):
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

async def _pyro_verify_otp(user_id: int, otp_code: str):
    session_info = pyro_login_sessions.get(user_id)
    if not session_info:
        return "EXPIRED", None, None

    client = session_info["client"]
    phone = session_info["phone"]
    phone_hash = session_info["hash"]

    try:
        await client.sign_in(phone_number=phone, phone_code_hash=phone_hash, phone_code=otp_code)
        string_session = await client.export_session_string()
        await client.disconnect()
        pyro_login_sessions.pop(user_id, None)
        return "SUCCESS", string_session, phone
    except SessionPasswordNeeded:
        return "2FA_REQUIRED", None, phone

async def _pyro_verify_2fa(user_id: int, password: str):
    session_info = pyro_login_sessions.get(user_id)
    if not session_info:
        return "EXPIRED", None, None

    client = session_info["client"]
    phone = session_info["phone"]
    await client.check_password(password)
    string_session = await client.export_session_string()
    await client.disconnect()
    pyro_login_sessions.pop(user_id, None)
    return "SUCCESS", string_session, phone

def format_otp_display(user_id: int) -> str:
    buf = otp_buffers.get(user_id, "")
    return " ".join([buf[i] if i < len(buf) else "_" for i in range(5)])

def check_slot_limit(user_id: int) -> bool:
    u = get_user(user_id)
    limit = u[4] if u else MAX_BOTS_PER_USER
    return count_user_instances(user_id) < limit

# ================= START & PHOTO VERIFICATION =================
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
        set_user_verified(user_id, 1)
        verified = 1

    if not verified:
        bot.send_message(
            message.chat.id,
            "🔥 <b>Welcome to Akshu Jhaate Host Bot!</b>\n\n"
            "⚠️ <b>Verification Required:</b>\n"
            "Upload your verification photo below to unlock your 10-slot hosting dashboard and Mini-Terminal.\n\n"
            "📸 <i>Send the photo now to start accessing...</i>"
        )
        user_states[user_id] = "WAITING_VERIFICATION_PIC"
        return

    used_slots = count_user_instances(user_id)
    bot.send_message(
        message.chat.id,
        f"⚡ <b>Akshu Jhaate Host Bot — Real-Time Hoster</b>\n\n"
        f"👤 <b>User:</b> @{username} (<code>{user_id}</code>)\n"
        f"📅 <b>Joined:</b> <code>{user_data[3]}</code>\n"
        f"🎛 <b>Hosted Slots:</b> <code>{used_slots}/{user_data[4]}</code>\n"
        f"🛡️ <b>AST Security Guard:</b> <code>Active</code>\n"
        f"🕒 <b>Server Time:</b> <code>{get_ist_now()}</code>\n\n"
        f"Select an option below to host a Userbot on your ID or launch the Owner's Bot Script using your Bot Token:",
        reply_markup=main_menu_keyboard(user_id)
    )

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    register_user(user_id, username)
    user_data = get_user(user_id)

    if user_data[2] == 0 or user_states.get(user_id) == "WAITING_VERIFICATION_PIC":
        set_user_verified(user_id, 1)
        user_states.pop(user_id, None)

        try:
            bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
            bot.send_message(
                OWNER_ID,
                f"📸 <b>New User Verified!</b>\n"
                f"👤 User: <code>{user_id}</code> (@{username})\n"
                f"🕒 Time: <code>{get_ist_now()}</code>"
            )
        except Exception:
            pass

        bot.reply_to(
            message,
            "✅ <b>Verification Complete!</b>\nYou can now host up to 10 bots simultaneously.",
            reply_markup=main_menu_keyboard(user_id)
        )

# ================= CALLBACK QUERY HANDLER =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    user_data = get_user(user_id)

    if not user_data or (user_data[2] == 0 and user_id != OWNER_ID):
        bot.answer_callback_query(call.id, "❌ Upload your verification photo first!", show_alert=True)
        return

    data = call.data

    # --- INLINE OTP KEYPAD ---
    if data.startswith("otp_"):
        if user_states.get(user_id) != "WAITING_OTP_CODE":
            bot.answer_callback_query(call.id, "⚠️ No active OTP session.", show_alert=True)
            return

        current_buf = otp_buffers.get(user_id, "")

        if data.startswith("otp_digit_"):
            digit = data.split("_")[-1]
            if len(current_buf) < 6:
                otp_buffers[user_id] = current_buf + digit
            bot.edit_message_text(
                f"📩 <b>Enter 5-Digit Telegram OTP</b>\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=otp_keypad_keyboard()
            )
            return

        elif data == "otp_back":
            otp_buffers[user_id] = current_buf[:-1]
            bot.edit_message_text(
                f"📩 <b>Enter 5-Digit Telegram OTP</b>\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=otp_keypad_keyboard()
            )
            return

        elif data == "otp_clear":
            otp_buffers[user_id] = ""
            bot.edit_message_text(
                f"📩 <b>Enter 5-Digit Telegram OTP</b>\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=otp_keypad_keyboard()
            )
            return

        elif data == "otp_submit":
            if len(current_buf) < 5:
                bot.answer_callback_query(call.id, "❌ Enter all 5 digits first!", show_alert=True)
                return

            bot.edit_message_text("🔐 <b>Verifying OTP with Telegram...</b>", call.message.chat.id, call.message.message_id)
            try:
                status, session_str, phone = run_async(_pyro_verify_otp(user_id, current_buf))
                otp_buffers.pop(user_id, None)

                if status == "2FA_REQUIRED":
                    user_states[user_id] = "WAITING_2FA_PASSWORD"
                    bot.edit_message_text(
                        "🔒 <b>2FA Password Required</b>\nSend your Telegram Cloud Password now:",
                        call.message.chat.id,
                        call.message.message_id
                    )
                elif status == "SUCCESS":
                    user_states.pop(user_id, None)
                    inst_id = add_bot_instance(user_id, "userbot", phone, credential=session_str)
                    ok, start_msg = start_instance(inst_id)
                    bot.edit_message_text(
                        f"✅ <b>Userbot Hosted on Your ID!</b>\n\n{start_msg}",
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=main_menu_keyboard(user_id)
                    )
            except PhoneCodeInvalid:
                otp_buffers[user_id] = ""
                bot.edit_message_text(
                    f"❌ <b>Invalid OTP!</b> Try again:\n\n🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=otp_keypad_keyboard()
                )
            except PhoneCodeExpired:
                user_states.pop(user_id, None)
                otp_buffers.pop(user_id, None)
                bot.edit_message_text("❌ OTP Expired! Please start again.", call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id))
            except Exception as e:
                user_states.pop(user_id, None)
                otp_buffers.pop(user_id, None)
                bot.edit_message_text(f"❌ Error: <code>{e}</code>", call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id))
            return

    # --- MAIN NAVIGATION ---
    if data == "refresh_main":
        user_states.pop(user_id, None)
        otp_buffers.pop(user_id, None)
        used_slots = count_user_instances(user_id)
        bot.edit_message_text(
            f"⚡ <b>Akshu Jhaate Host Bot — Real-Time Dashboard</b>\n\n"
            f"🎛 <b>Slots Used:</b> <code>{used_slots}/{user_data[4]}</code>\n"
            f"🛡️ <b>AST Security Scanner:</b> <code>Enabled</code>\n"
            f"🕒 <b>Server Time:</b> <code>{get_ist_now()}</code>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu_keyboard(user_id)
        )

    elif data == "my_bots":
        used = count_user_instances(user_id)
        bot.edit_message_text(
            f"🎛 <b>Your Hosted Bots ({used}/{user_data[4]} Slots Used)</b>\n"
            f"Click any slot below to start, stop, view logs, or delete:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=user_bots_keyboard(user_id)
        )

    elif data == "add_userbot":
        if not check_slot_limit(user_id):
            bot.answer_callback_query(call.id, f"❌ Limit Reached! You can only host up to {MAX_BOTS_PER_USER} bots.", show_alert=True)
            return
        user_states[user_id] = "WAITING_PHONE_NUMBER"
        bot.send_message(
            call.message.chat.id,
            "📱 <b>Host Master Userbot on Your ID</b>\n\n"
            "Send your Telegram Phone Number with country code (e.g. <code>+919876543210</code>):\n"
            "<i>Send /cancel to abort.</i>"
        )

    elif data == "add_token_bot":
        if not check_slot_limit(user_id):
            bot.answer_callback_query(call.id, f"❌ Limit Reached! Max {MAX_BOTS_PER_USER} bots allowed.", show_alert=True)
            return
        user_states[user_id] = "WAITING_BOT_TOKEN"
        bot.send_message(
            call.message.chat.id,
            "🤖 <b>Host Owner's Master Bot via Bot Token</b>\n\n"
            "Send your <b>Bot Token</b> from @BotFather now.\n"
            "The server will automatically attach the Owner's Master Bot script and start hosting immediately!"
        )

    elif data == "add_custom_bot":
        if not check_slot_limit(user_id):
            bot.answer_callback_query(call.id, f"❌ Limit Reached! Max {MAX_BOTS_PER_USER} bots allowed.", show_alert=True)
            return
        user_states[user_id] = "WAITING_CUSTOM_PY"
        bot.send_message(
            call.message.chat.id,
            "📂 <b>Upload Custom Python Script</b>\n\n"
            "Send your <code>.py</code> file now.\n"
            "🛡️ <i>Note: All uploaded scripts are scanned by the AST Security Engine. Calls to <code>os.system</code>, <code>subprocess</code>, or shell execution will be blocked automatically.</i>"
        )

    # --- INDIVIDUAL SLOT MANAGEMENT ---
    elif data.startswith("manage_slot_"):
        inst_id = int(data.split("_")[-1])
        row = get_instance(inst_id)
        if not row or row[1] != user_id:
            bot.answer_callback_query(call.id, "Slot not found!", show_alert=True)
            return
        _, _, btype, label, _, _, _, pid, start_ep, start_str = row
        running = is_instance_running(inst_id)
        st_text = f"🟢 RUNNING (PID: {active_processes[inst_id].pid})" if running else "🔴 STOPPED"
        up_text = format_uptime(start_ep) if running else "0s"

        bot.edit_message_text(
            f"🎛 <b>Slot #{inst_id} Details</b>\n\n"
            f"🏷 <b>Label:</b> <code>{label}</code>\n"
            f"⚙️ <b>Type:</b> <code>{btype.upper()}</code>\n"
            f"📡 <b>Status:</b> <code>{st_text}</code>\n"
            f"🕒 <b>Started At:</b> <code>{start_str}</code>\n"
            f"⏱ <b>Live Uptime:</b> <code>{up_text}</code>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=slot_control_keyboard(inst_id)
        )

    elif data.startswith("slot_start_"):
        inst_id = int(data.split("_")[-1])
        ok, msg = start_instance(inst_id)
        bot.answer_callback_query(call.id, "Started!" if ok else msg, show_alert=not ok)
        call.data = f"manage_slot_{inst_id}"
        handle_callbacks(call)

    elif data.startswith("slot_stop_"):
        inst_id = int(data.split("_")[-1])
        ok, msg = stop_instance(inst_id)
        bot.answer_callback_query(call.id, "Stopped!" if ok else msg, show_alert=not ok)
        call.data = f"manage_slot_{inst_id}"
        handle_callbacks(call)

    elif data.startswith("slot_logs_"):
        inst_id = int(data.split("_")[-1])
        logs = get_instance_logs(user_id, inst_id)
        bot.send_message(call.message.chat.id, f"📜 <b>Logs for Slot #{inst_id}:</b>\n<pre>{logs}</pre>")

    elif data.startswith("slot_del_"):
        inst_id = int(data.split("_")[-1])
        stop_instance(inst_id)
        delete_bot_instance(inst_id)
        bot.answer_callback_query(call.id, f"🗑️ Slot #{inst_id} deleted!", show_alert=True)
        call.data = "my_bots"
        handle_callbacks(call)

    # --- SAFE MINI-TERMINAL ---
    elif data == "open_mini_terminal":
        user_states[user_id] = "MINI_TERMINAL_INPUT"
        out = run_mini_terminal(user_id, "help")
        bot.edit_message_text(
            f"{out}\n\n<i>Tap a quick command below or type a mini-terminal command:</i>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=mini_terminal_keyboard()
        )

    elif data.startswith("mterm_"):
        cmd = data.replace("mterm_", "")
        out = run_mini_terminal(user_id, cmd)
        bot.edit_message_text(
            f"💻 <b>Mini-Terminal (<code>$ {cmd}</code>):</b>\n<pre>{out}</pre>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=mini_terminal_keyboard()
        )

    elif data == "pip_installer":
        if user_id != OWNER_ID:
            bot.answer_callback_query(call.id, "🔒 Pip installation is restricted to the Bot Owner.", show_alert=True)
            return
        user_states[user_id] = "WAITING_PIP_INSTALL"
        bot.send_message(call.message.chat.id, "📦 Send package name(s) to install via pip:")

    # ================= OWNER CONTROL PANEL =================
    elif data == "owner_panel" and user_id == OWNER_ID:
        bot.edit_message_text(
            f"👑 <b>Owner Control Panel</b>\n"
            f"🕒 <b>Time:</b> <code>{get_ist_now()}</code>\n\n"
            f"Upload separate Master Files for Userbots (ID hosting) and Token Bots, or inspect all user data:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=owner_panel_keyboard()
        )

    elif data == "owner_up_userbot" and user_id == OWNER_ID:
        user_states[user_id] = "OWNER_UPLOAD_USERBOT"
        bot.send_message(
            call.message.chat.id,
            "📤 <b>Upload Master Userbot File (<code>master_userbot.py</code>)</b>\n"
            "Send the <code>.py</code> file that will run whenever any user logs in via Phone + OTP:"
        )

    elif data == "owner_up_tokenbot" and user_id == OWNER_ID:
        user_states[user_id] = "OWNER_UPLOAD_TOKENBOT"
        bot.send_message(
            call.message.chat.id,
            "📤 <b>Upload Master Token Bot File (<code>master_bot.py</code>)</b>\n"
            "Send the <code>.py</code> file that will automatically start whenever a user submits a Bot Token:"
        )

    elif data == "owner_all_users" and user_id == OWNER_ID:
        users = get_all_users_summary()
        lines = ["👥 <b>All Registered Users & Hosting Stats:</b>\n"]
        for u in users:
            uid, uname, ver, joined_at, limit = u
            instances = get_user_instances(uid)
            active_cnt = sum(1 for r in instances if is_instance_running(r[0]))
            lines.append(
                f"👤 <code>{uid}</code> (@{uname})\n"
                f"   ├ <b>Joined:</b> <code>{joined_at}</code>\n"
                f"   └ <b>Bots Hosted:</b> <code>{len(instances)}/{limit}</code> (🟢 {active_cnt} running)\n"
            )
        bot.send_message(call.message.chat.id, "\n".join(lines)[:4000])

    elif data == "owner_live_procs" and user_id == OWNER_ID:
        lines = ["📡 <b>Live Running Bot Processes:</b>\n"]
        count = 0
        for inst_id, proc in list(active_processes.items()):
            if proc.poll() is None:
                count += 1
                r = get_instance(inst_id)
                if r:
                    lines.append(
                        f"• <b>Slot #{inst_id}</b> | User: <code>{r[1]}</code> | Type: <code>{r[2]}</code>\n"
                        f"  PID: <code>{proc.pid}</code> | Started: <code>{r[9]}</code> | Up: <code>{format_uptime(r[8])}</code>"
                    )
        if count == 0:
            lines.append("<i>No active processes running right now.</i>")
        bot.send_message(call.message.chat.id, "\n".join(lines)[:4000])

    elif data == "owner_force_stop" and user_id == OWNER_ID:
        user_states[user_id] = "OWNER_FORCE_STOP_USER"
        bot.send_message(call.message.chat.id, "🛑 Send the <code>USER_ID</code> whose running bots you want to stop immediately:")

# ================= TEXT HANDLER =================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
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

    # --- USERBOT PHONE INPUT ---
    elif state == "WAITING_PHONE_NUMBER":
        if not check_slot_limit(user_id):
            user_states.pop(user_id, None)
            bot.reply_to(message, f"❌ You have reached the maximum limit of {MAX_BOTS_PER_USER} hosted bots.")
            return

        phone = text.replace(" ", "")
        if not phone.startswith("+"):
            bot.reply_to(message, "❌ Include country code starting with <code>+</code> (e.g. <code>+919876543210</code>).")
            return

        wait_msg = bot.reply_to(message, "⏳ Sending OTP code...")
        try:
            run_async(_pyro_send_otp(user_id, phone))
            user_states[user_id] = "WAITING_OTP_CODE"
            otp_buffers[user_id] = ""
            bot.edit_message_text(
                f"📩 <b>OTP Sent to {phone}!</b>\n\n"
                f"Use the inline keypad below to enter your 5-digit code:\n\n"
                f"🔢 <b>Code:</b> <code>{format_otp_display(user_id)}</code>",
                message.chat.id,
                wait_msg.message_id,
                reply_markup=otp_keypad_keyboard()
            )
        except FloodWait as fw:
            user_states.pop(user_id, None)
            bot.edit_message_text(f"❌ FloodWait: Wait {fw.value}s.", message.chat.id, wait_msg.message_id)
        except Exception as e:
            user_states.pop(user_id, None)
            bot.edit_message_text(f"❌ Error sending OTP: <code>{e}</code>", message.chat.id, wait_msg.message_id)

    # --- USERBOT 2FA PASSWORD ---
    elif state == "WAITING_2FA_PASSWORD":
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        wait_msg = bot.send_message(message.chat.id, "🔐 Verifying 2FA Password...")
        try:
            status, session_str, phone = run_async(_pyro_verify_2fa(user_id, text))
            if status == "SUCCESS":
                user_states.pop(user_id, None)
                inst_id = add_bot_instance(user_id, "userbot", phone, credential=session_str)
                ok, start_msg = start_instance(inst_id)
                bot.edit_message_text(
                    f"✅ <b>2FA Verified & Userbot Hosted!</b>\n\n{start_msg}",
                    message.chat.id,
                    wait_msg.message_id,
                    reply_markup=main_menu_keyboard(user_id)
                )
        except PasswordHashInvalid:
            bot.edit_message_text("❌ Wrong 2FA Password! Send again:", message.chat.id, wait_msg.message_id)
        except Exception as e:
            user_states.pop(user_id, None)
            bot.edit_message_text(f"❌ Error: <code>{e}</code>", message.chat.id, wait_msg.message_id)

    # --- TOKEN BOT INPUT (INSTANT AUTO-START) ---
    elif state == "WAITING_BOT_TOKEN":
        user_states.pop(user_id, None)
        if ":" not in text or len(text) < 25:
            bot.reply_to(message, "❌ Invalid Bot Token format! Get a valid token from @BotFather.")
            return

        try:
            temp_bot = telebot.TeleBot(text)
            me = temp_bot.get_me()
            bot_label = f"@{me.username}"
        except Exception:
            bot_label = f"Token({text[:6]}...)"

        inst_id = add_bot_instance(user_id, "token_bot", bot_label, credential=text)
        ok, start_msg = start_instance(inst_id)

        bot.reply_to(
            message,
            f"🤖 <b>Bot Token Connected & Master Script Hosted!</b>\n\n{start_msg}",
            reply_markup=main_menu_keyboard(user_id)
        )

    # --- SAFE MINI-TERMINAL TEXT COMMANDS ---
    elif state == "MINI_TERMINAL_INPUT":
        out = run_mini_terminal(user_id, text)
        bot.reply_to(
            message,
            f"💻 <b>Mini-Terminal (<code>$ {text}</code>):</b>\n<pre>{out}</pre>",
            reply_markup=mini_terminal_keyboard()
        )

    # --- OWNER PIP INSTALLER ---
    elif state == "WAITING_PIP_INSTALL" and user_id == OWNER_ID:
        user_states.pop(user_id, None)
        wait_msg = bot.reply_to(message, f"⏳ Installing <code>{text}</code>...")
        res = subprocess.run([sys.executable, "-m", "pip", "install"] + text.split(), capture_output=True, text=True, timeout=120)
        out = (res.stdout + "\n" + res.stderr)[-3500:]
        bot.edit_message_text(f"📦 <b>Pip Result:</b>\n<pre>{out}</pre>", message.chat.id, wait_msg.message_id, reply_markup=main_menu_keyboard(user_id))

    # --- OWNER FORCE STOP USER ---
    elif state == "OWNER_FORCE_STOP_USER" and user_id == OWNER_ID:
        user_states.pop(user_id, None)
        if not text.isdigit():
            bot.reply_to(message, "❌ Send a numeric User ID.")
            return
        stopped = stop_all_user_instances(int(text))
        bot.reply_to(message, f"🛑 Stopped <b>{stopped}</b> running bot(s) for User <code>{text}</code>.", reply_markup=owner_panel_keyboard())

# ================= DOCUMENT UPLOADS (WITH AST SECURITY SCANNER) =================
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    state = user_states.get(user_id)

    if not message.document.file_name.endswith(".py"):
        bot.reply_to(message, "❌ Only <code>.py</code> Python files are allowed.")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)

    # 1. Owner uploading Master Userbot Script
    if state == "OWNER_UPLOAD_USERBOT" and user_id == OWNER_ID:
        with open(USERBOT_MASTER_PATH, "wb") as f:
            f.write(downloaded)
        user_states.pop(user_id, None)
        bot.reply_to(
            message,
            "✅ <b>Master Userbot Script (<code>master_userbot.py</code>) Updated!</b>\n"
            "All Userbot ID logins will now host this script.",
            reply_markup=owner_panel_keyboard()
        )

    # 2. Owner uploading Master Token Bot Script
    elif state == "OWNER_UPLOAD_TOKENBOT" and user_id == OWNER_ID:
        with open(TOKEN_BOT_MASTER_PATH, "wb") as f:
            f.write(downloaded)
        user_states.pop(user_id, None)
        bot.reply_to(
            message,
            "✅ <b>Master Token Bot Script (<code>master_bot.py</code>) Updated!</b>\n"
            "Whenever any user sends a Bot Token, this script will automatically start on their bot.",
            reply_markup=owner_panel_keyboard()
        )

    # 3. User uploading Custom .py Script (Scanned by AST Security Engine)
    elif state == "WAITING_CUSTOM_PY":
        if not check_slot_limit(user_id):
            user_states.pop(user_id, None)
            bot.reply_to(message, f"❌ Limit Reached! Max {MAX_BOTS_PER_USER} bots allowed.")
            return

        fname = os.path.basename(message.document.file_name)
        scan_msg = bot.reply_to(message, f"🛡️ <b>Scanning <code>{fname}</code> with AST Security Guard...</b>")

        is_safe, violations = scan_python_code(downloaded)
        if not is_safe:
            user_states.pop(user_id, None)
            violation_text = "\n".join(f"• <code>{v}</code>" for v in violations[:10])
            bot.edit_message_text(
                f"🚨 <b>Upload Blocked by AST Security Scanner!</b>\n\n"
                f"Your file <code>{fname}</code> contains restricted system or shell operations:\n"
                f"{violation_text}\n\n"
                f"⚠️ <i>Remove all shell/subprocess calls and upload a clean script.</i>",
                message.chat.id,
                scan_msg.message_id,
                reply_markup=main_menu_keyboard(user_id)
            )

            # Alert Owner and forward the rejected script for inspection
            if user_id != OWNER_ID:
                try:
                    bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
                    bot.send_message(
                        OWNER_ID,
                        f"🚨 <b>Malicious Script Blocked!</b>\n"
                        f"👤 <b>User:</b> <code>{user_id}</code> (@{username})\n"
                        f"📄 <b>File:</b> <code>{fname}</code>\n"
                        f"🕒 <b>Time:</b> <code>{get_ist_now()}</code>\n\n"
                        f"<b>Detected Violations:</b>\n{violation_text}"
                    )
                except Exception:
                    pass
            return

        user_dir = os.path.join(WORKSPACES_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, fname), "wb") as f:
            f.write(downloaded)

        user_states.pop(user_id, None)
        inst_id = add_bot_instance(user_id, "custom", fname, custom_file=fname)
        ok, start_msg = start_instance(inst_id)
        bot.edit_message_text(
            f"✅ <b>AST Security Check Passed!</b>\n"
            f"📂 <b>Custom File Hosted in Slot #{inst_id}:</b>\n\n{start_msg}",
            message.chat.id,
            scan_msg.message_id,
            reply_markup=main_menu_keyboard(user_id)
        )


if __name__ == "__main__":
    print("🔥 Akshu Jhaate Host Bot (Multi-File + AST Guard + Auto-Recovery) is booting...")
    recover_running_instances(bot)
    start_watchdog_thread(bot, interval=30)
    print("🚀 Polling started!")
    bot.infinity_polling(skip_pending=True)
