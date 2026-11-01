from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import OWNER_ID, MAX_BOTS_PER_USER, format_uptime
from database import get_user_instances
from process_manager import is_instance_running

def main_menu_keyboard(user_id: int):
    instances = get_user_instances(user_id)
    total_used = len(instances)
    running_count = sum(1 for r in instances if is_instance_running(r[0]))

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📱 Host Userbot (OTP)", callback_data="add_userbot"),
        InlineKeyboardButton("🤖 Host Token Bot", callback_data="add_token_bot")
    )
    kb.add(
        InlineKeyboardButton("📂 Upload Custom .py", callback_data="add_custom_bot"),
        InlineKeyboardButton(f"🎛 My Hosted Bots ({total_used}/{MAX_BOTS_PER_USER})", callback_data="my_bots")
    )
    kb.add(
        InlineKeyboardButton("💻 Mini-Terminal", callback_data="open_mini_terminal"),
        InlineKeyboardButton("📦 Pip Installer", callback_data="pip_installer")
    )
    kb.add(
        InlineKeyboardButton(f"🟢 Active: {running_count}/{total_used} | 🔄 Refresh", callback_data="refresh_main")
    )
    if user_id == OWNER_ID:
        kb.add(InlineKeyboardButton("👑 Owner Control Panel", callback_data="owner_panel"))
    return kb

def user_bots_keyboard(user_id: int):
    instances = get_user_instances(user_id)
    kb = InlineKeyboardMarkup(row_width=2)
    for r in instances:
        inst_id, _, btype, label, _, _, _, _, start_ep, _ = r
        running = is_instance_running(inst_id)
        icon = "🟢" if running else "🔴"
        up_str = f" ({format_uptime(start_ep)})" if running else ""
        kb.add(
            InlineKeyboardButton(
                f"{icon} #{inst_id} [{btype.upper()}] {label}{up_str}",
                callback_data=f"manage_slot_{inst_id}"
            )
        )
    kb.add(
        InlineKeyboardButton("➕ Add Userbot", callback_data="add_userbot"),
        InlineKeyboardButton("➕ Add Token Bot", callback_data="add_token_bot")
    )
    kb.add(InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_main"))
    return kb

def slot_control_keyboard(instance_id: int):
    running = is_instance_running(instance_id)
    kb = InlineKeyboardMarkup(row_width=2)
    if running:
        kb.add(
            InlineKeyboardButton("🛑 Stop Bot", callback_data=f"slot_stop_{instance_id}"),
            InlineKeyboardButton("🔄 Refresh Stats", callback_data=f"manage_slot_{instance_id}")
        )
    else:
        kb.add(InlineKeyboardButton("▶️ Start Bot", callback_data=f"slot_start_{instance_id}"))

    kb.add(
        InlineKeyboardButton("📜 View Logs", callback_data=f"slot_logs_{instance_id}"),
        InlineKeyboardButton("🗑️ Delete Slot", callback_data=f"slot_del_{instance_id}")
    )
    kb.add(InlineKeyboardButton("🔙 Back to My Bots", callback_data="my_bots"))
    return kb

def mini_terminal_keyboard():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("📊 ps", callback_data="mterm_ps"),
        InlineKeyboardButton("💻 sysinfo", callback_data="mterm_sysinfo"),
        InlineKeyboardButton("⏱ uptime", callback_data="mterm_uptime"),
        InlineKeyboardButton("📁 files", callback_data="mterm_files"),
        InlineKeyboardButton("📦 pip list", callback_data="mterm_pip list"),
        InlineKeyboardButton("❓ help", callback_data="mterm_help")
    )
    kb.add(InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_main"))
    return kb

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
        InlineKeyboardButton("🚫 Cancel", callback_data="refresh_main")
    )
    return kb

def owner_panel_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📤 Upload Master Userbot", callback_data="owner_up_userbot"),
        InlineKeyboardButton("📤 Upload Master Token Bot", callback_data="owner_up_tokenbot")
    )
    kb.add(
        InlineKeyboardButton("👥 All Users & Data", callback_data="owner_all_users"),
        InlineKeyboardButton("📡 Live Running Processes", callback_data="owner_live_procs")
    )
    kb.add(
        InlineKeyboardButton("🛑 Force Stop User Bots", callback_data="owner_force_stop")
    )
    kb.add(InlineKeyboardButton("🔙 Back to Main Menu", callback_data="refresh_main"))
    return kb
