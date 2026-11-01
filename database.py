import sqlite3
from config import DB_PATH, MAX_BOTS_PER_USER, get_ist_now

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    verified INTEGER DEFAULT 0,
                    joined_at TEXT,
                    bot_limit INTEGER DEFAULT 10
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS hosted_bots (
                    instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    bot_type TEXT,
                    label TEXT,
                    credential TEXT,
                    custom_file TEXT DEFAULT '',
                    status TEXT DEFAULT 'stopped',
                    pid INTEGER DEFAULT 0,
                    started_epoch REAL DEFAULT 0,
                    started_str TEXT DEFAULT 'Never'
                )''')
    conn.commit()
    conn.close()

def register_user(user_id: int, username: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (user_id, username, verified, joined_at, bot_limit) VALUES (?, ?, 0, ?, ?)",
            (user_id, username or "NoUsername", get_ist_now(), MAX_BOTS_PER_USER)
        )
    else:
        c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username or "NoUsername", user_id))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, verified, joined_at, bot_limit FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def set_user_verified(user_id: int, verified: int = 1):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET verified = ? WHERE user_id = ?", (verified, user_id))
    conn.commit()
    conn.close()

def get_user_instances(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT instance_id, user_id, bot_type, label, credential, custom_file, status, pid, started_epoch, started_str "
        "FROM hosted_bots WHERE user_id = ? ORDER BY instance_id ASC",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def get_instance(instance_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT instance_id, user_id, bot_type, label, credential, custom_file, status, pid, started_epoch, started_str "
        "FROM hosted_bots WHERE instance_id = ?",
        (instance_id,)
    )
    row = c.fetchone()
    conn.close()
    return row

def count_user_instances(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM hosted_bots WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def add_bot_instance(user_id: int, bot_type: str, label: str, credential: str = "", custom_file: str = "") -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO hosted_bots (user_id, bot_type, label, credential, custom_file, status) VALUES (?, ?, ?, ?, ?, 'stopped')",
        (user_id, bot_type, label, credential, custom_file)
    )
    instance_id = c.lastrowid
    conn.commit()
    conn.close()
    return instance_id

def update_instance_status(instance_id: int, status: str, pid: int = 0, started_epoch: float = 0.0, started_str: str = ""):
    conn = get_conn()
    c = conn.cursor()
    if status == "running":
        c.execute(
            "UPDATE hosted_bots SET status = ?, pid = ?, started_epoch = ?, started_str = ? WHERE instance_id = ?",
            (status, pid, started_epoch, started_str, instance_id)
        )
    else:
        c.execute(
            "UPDATE hosted_bots SET status = ?, pid = 0, started_epoch = 0 WHERE instance_id = ?",
            (status, instance_id)
        )
    conn.commit()
    conn.close()

def delete_bot_instance(instance_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM hosted_bots WHERE instance_id = ?", (instance_id,))
    conn.commit()
    conn.close()

def get_all_users_summary():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, verified, joined_at, bot_limit FROM users ORDER BY joined_at DESC")
    users = c.fetchall()
    conn.close()
    return users

def get_previously_running_instances():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT instance_id, user_id, bot_type, label "
        "FROM hosted_bots WHERE status = 'running' ORDER BY instance_id ASC"
    )
    rows = c.fetchall()
    conn.close()
    return rows
