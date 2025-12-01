import os
import random
import time
import json
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Set up logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- CRITICAL CONFIGURATION ---
# Replace with your bot token
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN" 
# The admin's Telegram username WITHOUT the @ sign
ADMIN_CONTACT = "YOUR_ADMIN_USERNAME".lstrip('@') 
DATA_FILE = "users_data.json" 

TRADING_PAIRS = [
    "BTC/USD OTC", "ETH/USD OTC", "EUR/USD OTC", "EUR/GBP OTC", "USD/CHF OTC", "EUR/JPY OTC",
    "GBP/USD OTC", "GBP/JPY OTC", "AUD/CAD OTC", "USD/ZAR OTC", "USD/SGD OTC", "USD/HKD OTC",
    "USD/INR OTC", "AUD/USD OTC", "USD/CAD OTC", "AUD/JPY OTC", "GBP/CAD OTC", "GBP/CHF OTC",
    "GBP/AUD OTC", "EUR/CAD OTC", "CHF/JPY OTC", "CAD/CHF OTC", "EUR/AUD OTC", "EUR/NZD OTC",
    "USD/NOK OTC", "USD/SEK OTC", "USD/TRY OTC", "USD/PLN OTC", "AUD/CHF OTC", "AUD/NZD OTC",
    "EUR/CHF OTC", "GBP/NZD OTC", "CAD/JPY OTC", "NZD/CAD OTC", "NZD/JPY OTC", "EUR/THB OTC",
    "USD/THB OTC", "JPY/THB OTC", "CHF/NOK OTC", "NOK/JPY OTC", "USD/BRL OTC", "USD/COP OTC",
    "PEN/USD OTC", "ONDO OTC", "SHIB/USD OTC", "SNAP INC OTC", "USD/MXN OTC", "RAYDIUM OTC",
    "SUI OTC", "HBAR OTC", "RENDER OTC", "GOLD", "AMAZON OTC", "GOOGLE OTC", "TESLA OTC",
    "META OTC", "BONK OTC", "PEPE OTC", "IOTA OTC"
]

TRADING_ACTIONS = ["BUY", "SELL"]
FREE_SIGNAL_LIMIT = 20 # 👈 20 free signals per user
EXPIRY_MINUTES = 3 # Base time for calculation

# --- Persistent Storage ---

def load_user_data():
    """Loads user data from JSON file."""
    try:
        with open(DATA_FILE, 'r') as f:
            raw_data = json.load(f)
            # Adjust keys to match original intent: 'signals' for free count
            # and ensure 'paid_until' is a datetime object
            converted_data = {}
            for k, u in raw_data.items():
                if u.get("paid_until"):
                    u["paid_until"] = datetime.strptime(u["paid_until"], "%Y-%m-%d %H:%M:%S")
                # Maintain 'signals' key for compatibility with original logic
                u["signals"] = u.pop("free_signals_used", u.get("signals", 0))
                converted_data[int(k)] = u
            return converted_data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_data():
    """Saves user data to JSON file."""
    try:
        data_copy = {}
        for uid, u in user_data.items():
            # Ensure 'signals' is saved, and 'paid_until' is a string
            data_copy[str(uid)] = {
                "signals": u.get("signals", 0),
                "paid_until": u["paid_until"].strftime("%Y-%m-%d %H:%M:%S") if u.get("paid_until") else None,
            }
        with open(DATA_FILE, 'w') as f:
            json.dump(data_copy, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

user_data = load_user_data()

# --- Utility Functions & Core Logic ---

def get_next_even_minute(minutes_from_now=EXPIRY_MINUTES):
    """Calculates the next even minute for a 2-minute candle trade (as per instruction)."""
    now = datetime.now() + timedelta(minutes=minutes_from_now)
    # If minute is odd, add 1 minute to make it even
    if now.minute % 2 != 0:
        now += timedelta(minutes=1)
    return now.replace(second=0, microsecond=0)

def pick_random_pair(history: list, non_repetition: int = 6) -> str:
    """Picks a random trading pair, avoiding recent ones."""
    # history stores the full signal string, so extract only the pair
    recent_pairs = [h.split(' - ')[0].replace('🟢 ', '').replace('🔴 ', '') for h in history[-non_repetition:]]
    available_pairs = [p for p in TRADING_PAIRS if p not in recent_pairs]
    
    if not available_pairs:
        # Fallback to all pairs if all are recently used
        available_pairs = list(TRADING_PAIRS)
        
    return random.choice(available_pairs)

def format_signal(pair: str, action: str, trade_time: datetime) -> str:
    """Formats the trading signal message."""
    emoji = "🟢" if action == "BUY" else "🔴"
    time_str = trade_time.strftime('%H:%M') # Only display hour and minute
    
    # Format: 🟢 BTC/USD OTC - BUY | 2min Candle | Time: 16:03
    return f"{emoji} **{pair}** - **{action}** | 2min Candle | Time: {time_str}"

def generate_signal_logic(user_id: int) -> tuple[str | None, str | None]:
    """Core logic to generate a signal, checking for subscription status and limits."""
    
    if user_id not in user_data:
        # Initialize user with signals (free limit), no payment, and history tracking
        user_data[user_id] = {"signals": 0, "paid_until": None, "history": []}
    
    user = user_data[user_id]
    now = datetime.now()
    
    # Subscription Check
    is_paid = user.get("paid_until") and user["paid_until"] > now
    is_limit_reached = user.get("signals", 0) >= FREE_SIGNAL_LIMIT

    # 💰 LIMIT CHECK (Exact instruction logic)
    if not is_paid and is_limit_reached:
        error_msg = (
            f"💰 Free signals used or subscription expired. Please subscribe to continue.\n"
            f"Contact admin: @{ADMIN_CONTACT}"
        )
        return None, error_msg

    # Generate the signal components
    pair = pick_random_pair(user.get("history", []))
    action = random.choice(TRADING_ACTIONS)
    trade_time = get_next_even_minute()
    signal = format_signal(pair, action, trade_time)

    # Update data: history is mandatory for non-repetition logic
    user["history"] = user.get("history", []) + [signal]

    # Increment counter ONLY if the user is NOT paid
    if not is_paid:
        user["signals"] = user.get("signals", 0) + 1
        
    save_user_data()
    
    # Footer Message based on status
    if is_paid:
        expires_on = user["paid_until"].strftime('%Y-%m-%d')
        footer = f"\n(Subscription: Unlimited signals until {expires_on})"
    else:
        remaining = FREE_SIGNAL_LIMIT - user["signals"]
        footer = f"\n(Free signals remaining: {remaining})"
    
    return signal, footer

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        f"⚡ Welcome! Get fast IQOption signals instantly.\n"
        f"Free signals available: {FREE_SIGNAL_LIMIT}\n"
        f"Admin: @{ADMIN_CONTACT}\n"
        f"Commands:\n"
        "/signal - Generate a trading signal\n"
        "/free - Claim free signals\n"
        "/subscribe - View subscription info\n"
        "/howtouse - Learn to use signals and martingale\n"
        "/support - Contact support\n"
        "/about - About the bot"
    )

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /signal command."""
    user_id = update.effective_user.id
    signal, message_suffix = generate_signal_logic(user_id)
    
    if signal:
        await update.message.reply_text(f"{signal}{message_suffix}", parse_mode='Markdown')
    else:
        await update.message.reply_text(message_suffix, parse_mode='Markdown')

async def free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /free command."""
    await update.message.reply_text(f"🎁 You can claim up to {FREE_SIGNAL_LIMIT} free signals. Each `/signal` counts.")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /subscribe command."""
    await update.message.reply_text(
        f"💳 Subscription unlocks unlimited signals for one month.\n"
        f"Contact admin: @{ADMIN_CONTACT} to subscribe."
    )

async def howtouse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /howtouse command (Martingale strategy)."""
    await update.message.reply_text(
        "📘 How to Use Signals & Martingale:\n\n"
        "• Divide capital by martingale levels:\n"
        "  - 4-level → /15\n"
        "  - 6-level → /63\n"
        "  - 8-level → /256\n"
        "• Each new signal = next martingale.\n"
        "• If signal wins → next signal normal.\n"
        "• If signal loses → generate new signal, multiply stake by 2.\n"
        "• Repeat until intended martingale completed.\n"
        "• Reset on win.\n\n⚠ Learn to trade content coming soon."
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /support command."""
    await update.message.reply_text(f"📩 Contact admin for support: @{ADMIN_CONTACT}")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /about command."""
    await update.message.reply_text(
        "🤖 IQOption Binary Master Bot\n"
        "Provides fast, accurate trading signals based on real market logic.\n"
        "Designed to remove emotion and give an edge most traders can't maintain manually."
    )

async def mark_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to mark a user as paid and set expiry."""
    # Check if the user sending the command matches the ADMIN_CONTACT
    if update.effective_user.username != ADMIN_CONTACT:
        await update.message.reply_text("⛔ Access denied. Only the administrator can use this command.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /mark_paid <user_id> [days] (Default 30 days)")
        return

    try:
        user_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 30
        expire = datetime.now() + timedelta(days=days)

        if user_id not in user_data:
            user_data[user_id] = {"signals": 0, "paid_until": expire, "history": []}
        else:
            user_data[user_id]["paid_until"] = expire
            user_data[user_id]["signals"] = 0 # Reset free count upon paid subscription

        save_user_data()
        await update.message.reply_text(
            f"✅ User `{user_id}` marked PAID for **{days} days** until {expire.strftime('%Y-%m-%d %H:%M')}",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("Invalid user_id or days value.")
    except Exception as e:
        logger.error(f"Error in mark_paid: {e}")
        await update.message.reply_text("An unexpected error occurred.")


# --- Main Execution Setup ---

def main():
    """Sets up and runs the Telegram bot."""
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is not set. Please update the configuration.")
        return

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True) 
        .build()
    )

    # Add all handlers (as per instruction)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signal", signal_command))
    application.add_handler(CommandHandler("free", free))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("howtouse", howtouse))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("mark_paid", mark_paid)) 

    print("Bot is starting polling...")
    # NOTE: Use run_polling() for local testing. Use Webhook for deployment (e.g., Render).
    application.run_polling(poll_interval=3.0) 

if __name__ == "__main__":
    # main()
    pass
