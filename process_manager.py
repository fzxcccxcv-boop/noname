import os
import sys
import time
import signal
import psutil
import threading
import subprocess

try:
    import resource
    HAS_RESOURCE_MODULE = True
except ImportError:
    HAS_RESOURCE_MODULE = False

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

# ================= RESOURCE LIMIT CONFIGURATION =================
MAX_RAM_MB = int(os.environ.get("MAX_RAM_MB", "150"))
MAX_RAM_BYTES = MAX_RAM_MB * 1024 * 1024
MAX_CPU_PERCENT = float(os.environ.get("MAX_CPU_PERCENT", "85.0"))
MAX_CPU_STRIKES = 3
MAX_FILE_WRITE_BYTES = 50 * 1024 * 1024
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024

active_processes = {}
crash_retries = {}
cpu_strikes = {}
psutil_cache = {}
MAX_CRASH_RETRIES = 3

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
    proc = psutil.Process(os.getpid())
    ram_mb = proc.memory_info().rss / (1024 * 1024)
    await message.reply_text(
        f"⚡ **Akshu Host — Master Userbot Active**\\n\\n"
        f"🆔 **Slot ID:** `#{INSTANCE_ID}`\\n"
        f"👤 **Owner ID:** `{HOSTED_USER_ID}`\\n"
        f"⏱ **Uptime:** `{uptime}s`\\n"
        f"🧠 **Slot RAM:** `{ram_mb:.1f} MB / 150 MB`"
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
    proc = psutil.Process(os.getpid())
    ram_mb = proc.memory_info().rss / (1024 * 1024)
    bot.reply_to(
        message,
        f"🤖 <b>Akshu Host — Master Token Bot Active!</b>\\n\\n"
        f"🆔 <b>Slot ID:</b> <code>#{INSTANCE_ID}</code>\\n"
        f"👤 <b>Hosted By:</b> <code>{HOSTED_USER_ID}</code>\\n"
        f"⏱ <b>Uptime:</b> <code>{uptime}s</code>\\n"
        f"🧠 <b>Slot RAM:</b> <code>{ram_mb:.1f} MB / 150 MB</code>"
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

def _apply_os_resource_limits():
    try:
        os.setsid()
    except Exception:
        pass
    try:
        os.nice(10)
    except Exception:
        pass
    if HAS_RESOURCE_MODULE:
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_WRITE_BYTES, MAX_FILE_WRITE_BYTES))
        except Exception:
            pass
        try:
            vmem_ceiling = 768 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (vmem_ceiling, vmem_ceiling))
        except Exception:
            pass

def _kill_process_tree(proc: subprocess.Popen):
    if proc is None:
        return
    try:
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass

    if os.name != "nt":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass

    try:
        proc.kill()
        proc.wait(timeout=2)
    except Exception:
        pass

def get_slot_resource_usage(instance_id: int):
    proc = active_processes.get(instance_id)
    if not proc or proc.poll() is not None:
        return 0.0, 0.0
    try:
        if instance_id not in psutil_cache or psutil_cache[instance_id].pid != proc.pid:
            p = psutil.Process(proc.pid)
            p.cpu_percent(interval=None)
            psutil_cache[instance_id] = p
        else:
            p = psutil_cache[instance_id]

        rss_bytes = p.memory_info().rss
        cpu_pct = p.cpu_percent(interval=None)

        for child in p.children(recursive=True):
            try:
                rss_bytes += child.memory_info().rss
                cpu_pct += child.cpu_percent(interval=None)
            except psutil.NoSuchProcess:
                pass

        return rss_bytes / (1024 * 1024), cpu_pct
    except Exception:
        return 0.0, 0.0

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

    if os.path.exists(log_path) and os.path.getsize(log_path) > MAX_LOG_FILE_BYTES:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"--- [LOG TRUNCATED AT {get_ist_now()}] ---\n")

    env = os.environ.copy()
    env["API_ID"] = str(API_ID)
    env["API_HASH"] = API_HASH
    env["HOSTED_USER_ID"] = str(user_id)
    env["INSTANCE_ID"] = str(inst_id)
    env["MALLOC_TRIM_THRESHOLD_"] = "65536"

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
    log_file.write(f"\n--- [SESSION LAUNCHED AT {get_ist_now()} | RAM CAP: {MAX_RAM_MB}MB] ---\n")
    log_file.flush()

    popen_kwargs = {
        "cwd": user_workspace,
        "env": env,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.PIPE,
        "text": True
    }
    if os.name != "nt":
        popen_kwargs["preexec_fn"] = _apply_os_resource_limits

    proc = subprocess.Popen([sys.executable, "-u", script_path], **popen_kwargs)

    now_epoch = time.time()
    now_str = get_ist_now()
    active_processes[inst_id] = proc
    cpu_strikes[inst_id] = 0

    try:
        p = psutil.Process(proc.pid)
        p.cpu_percent(interval=None)
        psutil_cache[inst_id] = p
    except Exception:
        pass

    if reset_retries:
        crash_retries[inst_id] = 0
    update_instance_status(inst_id, "running", proc.pid, now_epoch, now_str)

    return True, (
        f"✅ <b>Slot #{inst_id} Started!</b>\n"
        f"🏷 <b>Label:</b> <code>{label}</code>\n"
        f"⚙️ <b>Type:</b> <code>{bot_type.upper()}</code>\n"
        f"🆔 <b>PID:</b> <code>{proc.pid}</code>\n"
        f"🛡️ <b>Resource Cap:</b> <code>{MAX_RAM_MB} MB RAM</code>\n"
        f"🕒 <b>Started:</b> <code>{now_str}</code>"
    )

def stop_instance(instance_id: int):
    crash_retries.pop(instance_id, None)
    cpu_strikes.pop(instance_id, None)
    psutil_cache.pop(instance_id, None)

    if not is_instance_running(instance_id):
        update_instance_status(instance_id, "stopped")
        return False, f"⚠️ Slot #{instance_id} is not currently running."

    proc = active_processes.pop(instance_id, None)
    _kill_process_tree(proc)
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

def recover_running_instances(bot=None):
    rows = get_previously_running_instances()
    if not rows:
        return
    for inst_id, user_id, bot_type, label in rows:
        start_instance(inst_id, reset_retries=True)
        time.sleep(0.5)

def _append_violation_log(user_id: int, inst_id: int, reason: str):
    log_path = os.path.join(WORKSPACES_DIR, str(user_id), f"slot_{inst_id}", "session.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n🚨 [RESOURCE GUARD KILLED PROCESS AT {get_ist_now()}]: {reason}\n")
    except Exception:
        pass

def _watchdog_loop(bot=None, interval: int = 5):
    while True:
        time.sleep(interval)
        for inst_id, proc in list(active_processes.items()):
            exit_code = proc.poll()
            if exit_code is None:
                ram_mb, cpu_pct = get_slot_resource_usage(inst_id)
                if ram_mb > MAX_RAM_MB:
                    row = get_instance(inst_id)
                    user_id = row[1] if row else OWNER_ID
                    label = row[3] if row else f"Slot #{inst_id}"

                    active_processes.pop(inst_id, None)
                    cpu_strikes.pop(inst_id, None)
                    psutil_cache.pop(inst_id, None)
                    _kill_process_tree(proc)
                    update_instance_status(inst_id, "stopped")
                    _append_violation_log(user_id, inst_id, f"Exceeded {MAX_RAM_MB} MB RAM (Used {ram_mb:.1f} MB)")

                    if bot:
                        try:
                            bot.send_message(
                                user_id,
                                f"🚨 <b>Slot #{inst_id} (<code>{label}</code>) Killed — RAM Limit Exceeded!</b>\n\n"
                                f"🧠 <b>RAM Used:</b> <code>{ram_mb:.1f} MB</code> / <code>{MAX_RAM_MB} MB</code>\n"
                                f"<i>Process terminated to protect server stability.</i>"
                            )
                        except Exception:
                            pass
                    continue

                if cpu_pct > MAX_CPU_PERCENT:
                    cpu_strikes[inst_id] = cpu_strikes.get(inst_id, 0) + 1
                    if cpu_strikes[inst_id] >= MAX_CPU_STRIKES:
                        row = get_instance(inst_id)
                        user_id = row[1] if row else OWNER_ID
                        label = row[3] if row else f"Slot #{inst_id}"

                        active_processes.pop(inst_id, None)
                        cpu_strikes.pop(inst_id, None)
                        psutil_cache.pop(inst_id, None)
                        _kill_process_tree(proc)
                        update_instance_status(inst_id, "stopped")
                        _append_violation_log(user_id, inst_id, f"Sustained CPU overload ({cpu_pct:.1f}%)")

                        if bot:
                            try:
                                bot.send_message(
                                    user_id,
                                    f"🚨 <b>Slot #{inst_id} (<code>{label}</code>) Killed — CPU Freeze!</b>\n\n"
                                    f"⚡ <b>CPU Load:</b> <code>{cpu_pct:.1f}%</code> (Sustained)\n"
                                    f"<i>Process terminated to prevent server freeze.</i>"
                                )
                            except Exception:
                                pass
                        continue
                else:
                    cpu_strikes[inst_id] = 0
            else:
                active_processes.pop(inst_id, None)
                cpu_strikes.pop(inst_id, None)
                psutil_cache.pop(inst_id, None)

                row = get_instance(inst_id)
                if not row or row[6] != "running":
                    continue

                _, user_id, bot_type, label, _, _, _, _, _, _ = row
                retries = crash_retries.get(inst_id, 0) + 1
                crash_retries[inst_id] = retries

                if retries <= MAX_CRASH_RETRIES:
                    start_instance(inst_id, reset_retries=False)
                else:
                    update_instance_status(inst_id, "stopped")
                    if bot:
                        try:
                            bot.send_message(
                                user_id,
                                f"❌ <b>Slot #{inst_id} (<code>{label}</code>) Stopped:</b>\n"
                                f"Crashed {MAX_CRASH_RETRIES} consecutive times. Check logs."
                            )
                        except Exception:
                            pass

def start_watchdog_thread(bot=None, interval: int = 5):
    t = threading.Thread(target=_watchdog_loop, args=(bot, interval), daemon=True)
    t.start()

def run_mini_terminal(user_id: int, cmd_text: str) -> str:
    cmd = cmd_text.strip().lower()
    instances = get_user_instances(user_id)

    if cmd in ("help", "?"):
        return (
            "💻 <b>Akshu Mini-Terminal Commands:</b>\n"
            "• <code>ps</code> — List hosted slots with live RAM & CPU%\n"
            "• <code>sysinfo</code> — View server CPU, RAM & Disk\n"
            "• <code>uptime</code> — Active bot uptime\n"
            "• <code>files</code> — Workspace contents\n"
            "• <code>pip list</code> — Installed packages"
        )
    elif cmd == "ps":
        if not instances:
            return "No bot slots created yet."
        lines = [f"PID     | SLOT | RAM (MAX {MAX_RAM_MB}M) | CPU%  | STATUS"]
        lines.append("-" * 54)
        for r in instances:
            inst_id, _, btype, label, _, _, _, _, _, _ = r
            running = is_instance_running(inst_id)
            if running:
                live_pid = active_processes[inst_id].pid
                ram_mb, cpu_pct = get_slot_resource_usage(inst_id)
                lines.append(f"{str(live_pid):<7} | #{inst_id:<3} | {ram_mb:.1f} MB       | {cpu_pct:.1f}%  | RUN ({label})")
            else:
                lines.append(f"0       | #{inst_id:<3} | 0.0 MB       | 0.0%  | STOP ({label})")
        return "\n".join(lines)
    elif cmd == "sysinfo":
        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory()
        return f"CPU: {cpu}%\nRAM: {ram.percent}% ({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\nSlot Cap: {MAX_RAM_MB}MB RAM"
    elif cmd == "uptime":
        if not instances:
            return "No hosted bots found."
        lines = []
        for r in instances:
            inst_id, _, btype, label, _, _, _, _, start_ep, start_str = r
            if is_instance_running(inst_id):
                ram_mb, _ = get_slot_resource_usage(inst_id)
                lines.append(f"🟢 Slot #{inst_id} ({label}): Up {format_uptime(start_ep)} | RAM: {ram_mb:.1f}MB")
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
        return f"Unknown command: '{cmd}'. Type 'help'."
