import os
import sys
import time
import psutil
import threading
import subprocess
from config import (
    OWNER_ID,
    API_ID,
    API_HASH,
    WORKSPACES_DIR,
    USERBOT_MASTER_PATH,
    TOKEN_BOT_MASTER_PATH,
    get_ist_now,
    format_uptime
)
from database import (
    get_instance,
    get_user_instances,
    update_instance_status,
    get_previously_running_instances
)

# Active subprocess dictionary: {instance_id: subprocess.Popen}
active_processes = {}
# Crash retry counter for the watchdog: {instance_id: int}
crash_retries = {}
MAX_CRASH_RETRIES = 3

# ================= DEFAULT MASTER SCRIPTS =================
DEFAULT_MASTER_USERBOT = '''import os
import sys
import time
import psutil
import pyrogram
from pyrogram import Client, filters

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
STRING_SESSION = os.environ.get("STRING_SESSION")
HOSTED_USER_ID = os.environ.get("HOSTED_USER_ID", "Unknown")
INSTANCE_ID = os.environ.get("INSTANCE_ID", "1")
START_TIME = time.time()

app = Client(f"userbot_{INSTANCE_ID}", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION)

@app.on_message(filters.command("alive", prefixes=[".", "/"]) & filters.me)
async def alive_cmd(client, message):
    uptime = int(time.time() - START_TIME)
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    await message.reply_text(
        f"⚡ **Akshu Host — Master Userbot Active**\\n\\n"
        f"🆔 **Slot ID:** `#{INSTANCE_ID}`\\n"
        f"👤 **Owner ID:** `{HOSTED_USER_ID}`\\n"
        f"⏱ **Uptime:** `{uptime}s`\\n"
        f"💻 **CPU / RAM:** `{cpu}%` | `{ram}%`"
    )

@app.on_message(filters.command("ping", prefixes=[".", "/"]) & filters.me)
async def ping_cmd(client, message):
    t0 = time.perf_counter()
    m = await message.reply_text("🏓 **Pinging...**")
    ms = (time.perf_counter() - t0) * 1000
    await m.edit_text(f"🏓 **Pong!** `{ms:.2f} ms` (Slot #{INSTANCE_ID})")

print(f"[USERBOT #{INSTANCE_ID}] Started for User {HOSTED_USER_ID}")
app.run()
'''

DEFAULT_MASTER_TOKEN_BOT = '''import os
import time
import psutil
import telebot

BOT_TOKEN = os.environ.get("CLIENT_BOT_TOKEN")
HOSTED_USER_ID = os.environ.get("HOSTED_USER_ID", "Unknown")
INSTANCE_ID = os.environ.get("INSTANCE_ID", "1")
START_TIME = time.time()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

@bot.message_handler(commands=['start', 'alive'])
def start_cmd(message):
    uptime = int(time.time() - START_TIME)
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    bot.reply_to(
        message,
        f"🤖 <b>Akshu Host — Master Token Bot Active!</b>\\n\\n"
        f"🆔 <b>Slot ID:</b> <code>#{INSTANCE_ID}</code>\\n"
        f"👤 <b>Hosted By:</b> <code>{HOSTED_USER_ID}</code>\\n"
        f"⏱ <b>Uptime:</b> <code>{uptime}s</code>\\n"
        f"💻 <b>CPU / RAM:</b> <code>{cpu}%</code> | <code>{ram}%</code>"
    )

@bot.message_handler(commands=['ping'])
def ping_cmd(message):
    t0 = time.perf_counter()
    msg = bot.reply_to(message, "🏓 Pinging...")
    ms = (time.perf_counter() - t0) * 1000
    bot.edit_message_text(f"🏓 <b>Pong!</b> <code>{ms:.2f} ms</code>", message.chat.id, msg.message_id)

print(f"[TOKEN_BOT #{INSTANCE_ID}] Polling started for User {HOSTED_USER_ID}")
bot.infinity_polling()
'''

def ensure_master_scripts():
    if not os.path.exists(USERBOT_MASTER_PATH):
        with open(USERBOT_MASTER_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_MASTER_USERBOT)
    if not os.path.exists(TOKEN_BOT_MASTER_PATH):
        with open(TOKEN_BOT_MASTER_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_MASTER_TOKEN_BOT)

ensure_master_scripts()

# ================= INSTANCE PROCESS CONTROLS =================
def is_instance_running(instance_id: int) -> bool:
    proc = active_processes.get(instance_id)
    return proc is not None and proc.poll() is None

def start_instance(instance_id: int, reset_retries: bool = True):
    row = get_instance(instance_id)
    if not row:
        return False, "❌ Bot slot not found in database."

    inst_id, user_id, bot_type, label, credential, custom_file, status, _, _, _ = row

    if is_instance_running(inst_id):
        return False, f"⚠️ Slot #{inst_id} ({label}) is already running!"

    user_workspace = os.path.join(WORKSPACES_DIR, str(user_id), f"slot_{inst_id}")
    os.makedirs(user_workspace, exist_ok=True)
    log_path = os.path.join(user_workspace, "session.log")

    env = os.environ.copy()
    env["API_ID"] = str(API_ID)
    env["API_HASH"] = API_HASH
    env["HOSTED_USER_ID"] = str(user_id)
    env["INSTANCE_ID"] = str(inst_id)

    if bot_type == "userbot":
        if not credential:
            update_instance_status(inst_id, "stopped")
            return False, "❌ Missing String Session for Userbot."
        env["STRING_SESSION"] = credential
        env["CLIENT_BOT_TOKEN"] = ""
        script_path = USERBOT_MASTER_PATH
    elif bot_type == "token_bot":
        if not credential:
            update_instance_status(inst_id, "stopped")
            return False, "❌ Missing Bot Token."
        env["CLIENT_BOT_TOKEN"] = credential
        env["BOT_TOKEN"] = credential
        env["STRING_SESSION"] = ""
        script_path = TOKEN_BOT_MASTER_PATH
    elif bot_type == "custom":
        script_path = os.path.join(WORKSPACES_DIR, str(user_id), custom_file)
        if not os.path.exists(script_path):
            update_instance_status(inst_id, "stopped")
            return False, "❌ Custom script file missing on server."
    else:
        update_instance_status(inst_id, "stopped")
        return False, "❌ Unknown bot type."

    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n--- [SESSION LAUNCHED AT {get_ist_now()}] ---\n")
    log_file.flush()

    proc = subprocess.Popen(
        [sys.executable, "-u", script_path],
        cwd=user_workspace,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True
    )
    now_epoch = time.time()
    now_str = get_ist_now()
    active_processes[inst_id] = proc
    if reset_retries:
        crash_retries[inst_id] = 0
    update_instance_status(inst_id, "running", proc.pid, now_epoch, now_str)

    return True, (
        f"✅ <b>Slot #{inst_id} Started!</b>\n"
        f"🏷 <b>Label:</b> <code>{label}</code>\n"
        f"⚙️ <b>Type:</b> <code>{bot_type.upper()}</code>\n"
        f"🆔 <b>PID:</b> <code>{proc.pid}</code>\n"
        f"🕒 <b>Started:</b> <code>{now_str}</code>"
    )

def stop_instance(instance_id: int):
    crash_retries.pop(instance_id, None)
    if not is_instance_running(instance_id):
        update_instance_status(instance_id, "stopped")
        return False, f"⚠️ Slot #{instance_id} is not currently running."

    proc = active_processes[instance_id]
    proc.terminate()
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()

    active_processes.pop(instance_id, None)
    update_instance_status(instance_id, "stopped")
    return True, f"🛑 <b>Slot #{instance_id}</b> stopped cleanly."

def stop_all_user_instances(user_id: int) -> int:
    instances = get_user_instances(user_id)
    stopped_count = 0
    for row in instances:
        inst_id = row[0]
        if is_instance_running(inst_id):
            stop_instance(inst_id)
            stopped_count += 1
    return stopped_count

def get_instance_logs(user_id: int, instance_id: int) -> str:
    log_path = os.path.join(WORKSPACES_DIR, str(user_id), f"slot_{instance_id}", "session.log")
    if not os.path.exists(log_path):
        return "No logs generated for this slot yet."
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()[-3500:] or "Log file is empty."

# ================= STARTUP RECOVERY & AUTO-RESTART WATCHDOG =================
def recover_running_instances(bot=None):
    """Automatically restarts all bots that were marked 'running' prior to a container reboot."""
    rows = get_previously_running_instances()
    if not rows:
        print("ℹ️ [Startup Recovery] No previously running slots found in database.")
        return

    print(f"🔄 [Startup Recovery] Found {len(rows)} active slot(s) to restore...")
    restored = []
    failed = []

    for inst_id, user_id, bot_type, label in rows:
        ok, _ = start_instance(inst_id, reset_retries=True)
        if ok:
            pid = active_processes[inst_id].pid
            restored.append(f"• Slot <code>#{inst_id}</code> ({bot_type.upper()} - <code>{label}</code>) → PID <code>{pid}</code>")
            print(f"  ✅ Restored Slot #{inst_id} ({label}) [PID {pid}]")
        else:
            failed.append(f"• Slot <code>#{inst_id}</code> (<code>{label}</code>)")
            print(f"  ❌ Failed to restore Slot #{inst_id} ({label})")
        time.sleep(0.5)  # Stagger process launches to avoid CPU spike on Railway

    if bot:
        report = (
            f"♻️ <b>Container Reboot — Startup Recovery Report</b>\n"
            f"🕒 <b>Time:</b> <code>{get_ist_now()}</code>\n\n"
            f"✅ <b>Restored ({len(restored)}):</b>\n" +
            ("\n".join(restored) if restored else "<i>None</i>")
        )
        if failed:
            report += f"\n\n❌ <b>Failed ({len(failed)}):</b>\n" + "\n".join(failed)
        try:
            bot.send_message(OWNER_ID, report[:4000])
        except Exception:
            pass

def _watchdog_loop(bot=None, interval: int = 30):
    """Background loop that monitors active_processes and auto-restarts crashed slots."""
    while True:
        time.sleep(interval)
        for inst_id, proc in list(active_processes.items()):
            exit_code = proc.poll()
            if exit_code is not None:
                # Process exited unexpectedly without stop_instance() being called
                active_processes.pop(inst_id, None)
                row = get_instance(inst_id)
                if not row or row[6] != "running":
                    continue

                _, user_id, bot_type, label, _, _, _, _, _, _ = row
                retries = crash_retries.get(inst_id, 0) + 1
                crash_retries[inst_id] = retries

                if retries <= MAX_CRASH_RETRIES:
                    print(f"⚠️ [Watchdog] Slot #{inst_id} ({label}) crashed (code {exit_code}). Auto-restarting ({retries}/{MAX_CRASH_RETRIES})...")
                    ok, _ = start_instance(inst_id, reset_retries=False)
                    if ok and bot:
                        try:
                            bot.send_message(
                                user_id,
                                f"♻️ <b>Auto-Restart Notice:</b>\n"
                                f"Your Slot <code>#{inst_id}</code> (<code>{label}</code>) exited unexpectedly and was automatically restarted (Attempt <code>{retries}/{MAX_CRASH_RETRIES}</code>)."
                            )
                        except Exception:
                            pass
                else:
                    print(f"🛑 [Watchdog] Slot #{inst_id} ({label}) exceeded max crash retries. Marking stopped.")
                    update_instance_status(inst_id, "stopped")
                    if bot:
                        try:
                            bot.send_message(
                                user_id,
                                f"❌ <b>Slot #{inst_id} (<code>{label}</code>) Stopped:</b>\n"
                                f"Process crashed {MAX_CRASH_RETRIES} times in a row. Check <b>📜 View Logs</b> to fix the error."
                            )
                        except Exception:
                            pass

def start_watchdog_thread(bot=None, interval: int = 30):
    """Starts the background watchdog daemon thread."""
    t = threading.Thread(target=_watchdog_loop, args=(bot, interval), daemon=True)
    t.start()
    print(f"🛡️ [Watchdog] Crash monitor active (checking every {interval}s).")

# ================= SAFE MINI-TERMINAL ENGINE =================
def run_mini_terminal(user_id: int, cmd_text: str) -> str:
    """Executes safe, built-in diagnostic mini-terminal commands."""
    cmd = cmd_text.strip().lower()
    instances = get_user_instances(user_id)

    if cmd in ("help", "?"):
        return (
            "💻 <b>Akshu Mini-Terminal Commands:</b>\n"
            "• <code>ps</code> — List your hosted bot slots & live PIDs\n"
            "• <code>sysinfo</code> — View server CPU, RAM & Disk usage\n"
            "• <code>uptime</code> — Check live uptime of your active bots\n"
            "• <code>files</code> — List files in your personal workspace\n"
            "• <code>pip list</code> — View installed Python packages"
        )

    elif cmd == "ps":
        if not instances:
            return "No bot slots created yet."
        lines = ["PID     | SLOT | TYPE      | STATUS"]
        lines.append("-" * 40)
        for r in instances:
            inst_id, _, btype, label, _, _, _, pid, _, _ = r
            running = is_instance_running(inst_id)
            st = "RUNNING" if running else "STOPPED"
            live_pid = active_processes[inst_id].pid if running else 0
            lines.append(f"{str(live_pid):<7} | #{inst_id:<3} | {btype:<9} | {st} ({label})")
        return "\n".join(lines)

    elif cmd == "sysinfo":
        cpu = psutil.cpu_percent(interval=0.3)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return (
            f"CPU Usage   : {cpu}%\n"
            f"RAM Usage   : {ram.percent}% ({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\n"
            f"Disk Usage  : {disk.percent}%\n"
            f"Python Ver  : {sys.version.split()[0]}"
        )

    elif cmd == "uptime":
        if not instances:
            return "No hosted bots found."
        lines = []
        for r in instances:
            inst_id, _, btype, label, _, _, _, _, start_ep, start_str = r
            if is_instance_running(inst_id):
                lines.append(f"🟢 Slot #{inst_id} ({label}): Up for {format_uptime(start_ep)} (Since {start_str})")
            else:
                lines.append(f"🔴 Slot #{inst_id} ({label}): Offline")
        return "\n".join(lines)

    elif cmd == "files":
        u_dir = os.path.join(WORKSPACES_DIR, str(user_id))
        if not os.path.exists(u_dir):
            return "Workspace is empty."
        items = os.listdir(u_dir)
        return "Workspace contents:\n" + ("\n".join(f"• {x}" for x in items) if items else "Empty")

    elif cmd == "pip list":
        res = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True, timeout=15)
        return res.stdout[-3000:]

    else:
        return f"Unknown mini-terminal command: '{cmd}'. Type 'help' for supported commands."
