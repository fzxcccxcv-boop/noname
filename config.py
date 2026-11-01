import os
from datetime import datetime, timezone, timedelta

# ================= ENVIRONMENT CONFIGURATION =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_MAIN_HOST_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "123456789"))
API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH_HERE")

# Hosting limits
MAX_BOTS_PER_USER = int(os.environ.get("MAX_BOTS_PER_USER", "10"))

# ================= DIRECTORY PATHS =================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")
MASTER_DIR = os.path.join(BASE_DIR, "master_scripts")

# Separate Master Scripts for Owner Panel
USERBOT_MASTER_PATH = os.path.join(MASTER_DIR, "master_userbot.py")
TOKEN_BOT_MASTER_PATH = os.path.join(MASTER_DIR, "master_bot.py")
DB_PATH = os.path.join(BASE_DIR, "akshu_hoster.db")

os.makedirs(WORKSPACES_DIR, exist_ok=True)
os.makedirs(MASTER_DIR, exist_ok=True)

# ================= REAL-TIME IST HELPER =================
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> str:
    """Returns current real-time timestamp in IST."""
    return datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p IST")

def format_uptime(start_epoch: float) -> str:
    """Calculates live uptime from a start epoch timestamp."""
    if not start_epoch:
        return "0s"
    seconds = max(0, int(datetime.now().timestamp() - float(start_epoch)))
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
