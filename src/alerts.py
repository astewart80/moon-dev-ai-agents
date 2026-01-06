"""
🔔 Moon Dev's Alert System
Sends notifications for critical trading events via Discord webhook.

Supports:
- Position opened/closed
- Stop loss / Take profit hit
- Daily drawdown warnings
- Circuit breaker triggered
- Critical errors
- Custom alerts
"""

import os
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional
from termcolor import cprint

# ============================================================================
# CONFIGURATION
# ============================================================================

# Alert settings file (shared with dashboard)
ALERT_SETTINGS_FILE = Path(__file__).parent / "data" / "alert_settings.json"

# Default settings
DEFAULT_SETTINGS = {
    "enabled": True,
    "discord_webhook": "",  # User must configure this
    "alert_types": {
        "position_opened": True,
        "position_closed": True,
        "stop_loss_hit": True,
        "take_profit_hit": True,
        "trailing_stop_hit": True,
        "drawdown_warning": True,
        "circuit_breaker": True,
        "critical_error": True,
        "daily_summary": True,
    },
    "quiet_hours": {
        "enabled": False,
        "start": "22:00",
        "end": "08:00",
    }
}

# Alert colors for Discord embeds (decimal format)
COLORS = {
    "success": 65280,      # Green #00FF00
    "warning": 16776960,   # Yellow #FFFF00
    "danger": 16711680,    # Red #FF0000
    "info": 3447003,       # Blue #3498DB
    "profit": 65280,       # Green
    "loss": 16711680,      # Red
}


# ============================================================================
# SETTINGS MANAGEMENT
# ============================================================================

def load_alert_settings() -> dict:
    """Load alert settings from file"""
    try:
        if ALERT_SETTINGS_FILE.exists():
            with open(ALERT_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Merge with defaults to ensure all keys exist
                merged = DEFAULT_SETTINGS.copy()
                merged.update(settings)
                merged["alert_types"] = {**DEFAULT_SETTINGS["alert_types"], **settings.get("alert_types", {})}
                return merged
    except Exception as e:
        cprint(f"⚠️ Could not load alert settings: {e}", "yellow")
    return DEFAULT_SETTINGS.copy()


def save_alert_settings(settings: dict) -> bool:
    """Save alert settings to file"""
    try:
        ALERT_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        cprint(f"⚠️ Could not save alert settings: {e}", "yellow")
        return False


def is_alert_enabled(alert_type: str) -> bool:
    """Check if a specific alert type is enabled"""
    settings = load_alert_settings()
    if not settings.get("enabled", True):
        return False
    if not settings.get("discord_webhook"):
        return False
    return settings.get("alert_types", {}).get(alert_type, True)


def is_quiet_hours() -> bool:
    """Check if current time is within quiet hours"""
    settings = load_alert_settings()
    quiet = settings.get("quiet_hours", {})

    if not quiet.get("enabled", False):
        return False

    try:
        now = datetime.now().strftime("%H:%M")
        start = quiet.get("start", "22:00")
        end = quiet.get("end", "08:00")

        # Handle overnight quiet hours (e.g., 22:00 - 08:00)
        if start > end:
            return now >= start or now < end
        else:
            return start <= now < end
    except:
        return False


# ============================================================================
# DISCORD WEBHOOK
# ============================================================================

def send_discord_alert(
    title: str,
    message: str,
    color: str = "info",
    fields: Optional[list] = None,
    alert_type: str = "info"
) -> bool:
    """
    Send an alert via Discord webhook.

    Args:
        title: Alert title
        message: Alert message/description
        color: Color key (success, warning, danger, info, profit, loss)
        fields: Optional list of {"name": "Field Name", "value": "Field Value", "inline": True}
        alert_type: Type of alert for filtering (position_opened, stop_loss_hit, etc.)

    Returns:
        bool: True if sent successfully
    """
    # Check if alerts are enabled
    if not is_alert_enabled(alert_type):
        return False

    # Check quiet hours (except for critical alerts)
    if alert_type not in ["circuit_breaker", "critical_error"] and is_quiet_hours():
        cprint(f"🔕 Alert suppressed (quiet hours): {title}", "yellow")
        return False

    settings = load_alert_settings()
    webhook_url = settings.get("discord_webhook", "")

    if not webhook_url:
        cprint("⚠️ Discord webhook not configured", "yellow")
        return False

    try:
        # Build embed
        embed = {
            "title": title,
            "description": message,
            "color": COLORS.get(color, COLORS["info"]),
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": "Moon Dev Trading Bot 🌙"
            }
        }

        if fields:
            embed["fields"] = fields

        payload = {
            "embeds": [embed]
        }

        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10
        )

        if response.status_code == 204:
            cprint(f"🔔 Alert sent: {title}", "green")
            return True
        else:
            cprint(f"⚠️ Discord webhook error: {response.status_code}", "yellow")
            return False

    except Exception as e:
        cprint(f"❌ Failed to send alert: {e}", "red")
        return False


# ============================================================================
# ALERT FUNCTIONS
# ============================================================================

def alert_position_opened(
    symbol: str,
    side: str,
    size: float,
    entry_price: float,
    leverage: int = 1,
    confidence: int = 0
):
    """Alert when a new position is opened"""
    emoji = "🟢" if side.upper() == "LONG" else "🔴"
    notional = size * entry_price

    fields = [
        {"name": "Symbol", "value": symbol, "inline": True},
        {"name": "Side", "value": f"{emoji} {side.upper()}", "inline": True},
        {"name": "Leverage", "value": f"{leverage}x", "inline": True},
        {"name": "Entry Price", "value": f"${entry_price:,.4f}", "inline": True},
        {"name": "Size", "value": f"${notional:,.2f}", "inline": True},
        {"name": "Confidence", "value": f"{confidence}%", "inline": True},
    ]

    send_discord_alert(
        title=f"📈 Position Opened: {symbol}",
        message=f"Opened {side.upper()} position on {symbol}",
        color="success",
        fields=fields,
        alert_type="position_opened"
    )


def alert_position_closed(
    symbol: str,
    side: str,
    pnl: float,
    pnl_pct: float,
    reason: str = "Manual"
):
    """Alert when a position is closed"""
    emoji = "💰" if pnl >= 0 else "💸"
    color = "profit" if pnl >= 0 else "loss"

    fields = [
        {"name": "Symbol", "value": symbol, "inline": True},
        {"name": "Side", "value": side.upper(), "inline": True},
        {"name": "Reason", "value": reason, "inline": True},
        {"name": "P/L", "value": f"${pnl:+,.2f}", "inline": True},
        {"name": "P/L %", "value": f"{pnl_pct:+.2f}%", "inline": True},
    ]

    send_discord_alert(
        title=f"{emoji} Position Closed: {symbol}",
        message=f"Closed {side.upper()} with {pnl_pct:+.2f}% P/L",
        color=color,
        fields=fields,
        alert_type="position_closed"
    )


def alert_stop_loss_hit(
    symbol: str,
    pnl: float,
    pnl_pct: float,
    entry_price: float,
    exit_price: float
):
    """Alert when stop loss is triggered"""
    fields = [
        {"name": "Symbol", "value": symbol, "inline": True},
        {"name": "Entry", "value": f"${entry_price:,.4f}", "inline": True},
        {"name": "Exit", "value": f"${exit_price:,.4f}", "inline": True},
        {"name": "Loss", "value": f"${pnl:,.2f}", "inline": True},
        {"name": "Loss %", "value": f"{pnl_pct:.2f}%", "inline": True},
    ]

    send_discord_alert(
        title=f"🛑 Stop Loss Hit: {symbol}",
        message=f"Stop loss triggered at {pnl_pct:.2f}% loss",
        color="danger",
        fields=fields,
        alert_type="stop_loss_hit"
    )


def alert_take_profit_hit(
    symbol: str,
    pnl: float,
    pnl_pct: float,
    entry_price: float,
    exit_price: float
):
    """Alert when take profit is triggered"""
    fields = [
        {"name": "Symbol", "value": symbol, "inline": True},
        {"name": "Entry", "value": f"${entry_price:,.4f}", "inline": True},
        {"name": "Exit", "value": f"${exit_price:,.4f}", "inline": True},
        {"name": "Profit", "value": f"${pnl:,.2f}", "inline": True},
        {"name": "Profit %", "value": f"+{pnl_pct:.2f}%", "inline": True},
    ]

    send_discord_alert(
        title=f"🎯 Take Profit Hit: {symbol}",
        message=f"Take profit triggered at +{pnl_pct:.2f}% profit!",
        color="success",
        fields=fields,
        alert_type="take_profit_hit"
    )


def alert_trailing_stop_hit(
    symbol: str,
    pnl: float,
    pnl_pct: float,
    peak_pnl_pct: float
):
    """Alert when trailing stop is triggered"""
    fields = [
        {"name": "Symbol", "value": symbol, "inline": True},
        {"name": "Peak P/L", "value": f"+{peak_pnl_pct:.2f}%", "inline": True},
        {"name": "Exit P/L", "value": f"+{pnl_pct:.2f}%", "inline": True},
        {"name": "Locked Profit", "value": f"${pnl:,.2f}", "inline": True},
    ]

    send_discord_alert(
        title=f"📉 Trailing Stop Hit: {symbol}",
        message=f"Trailing stop triggered. Locked in {pnl_pct:.2f}% from {peak_pnl_pct:.2f}% peak",
        color="warning",
        fields=fields,
        alert_type="trailing_stop_hit"
    )


def alert_partial_profit(
    symbol: str,
    partial_num: int,
    pnl_pct: float,
    size_pct: float,
    profit_locked: float,
    new_sl_pct: float
):
    """Alert when partial profit is taken"""
    sl_status = "Breakeven (0%)" if new_sl_pct == 0 else f"+{new_sl_pct:.1f}%" if new_sl_pct > 0 else f"{new_sl_pct:.1f}%"

    fields = [
        {"name": "Partial #", "value": str(partial_num), "inline": True},
        {"name": "Trigger P/L", "value": f"+{pnl_pct:.2f}%", "inline": True},
        {"name": "Size Closed", "value": f"{size_pct}%", "inline": True},
        {"name": "Profit Locked", "value": f"~${profit_locked:,.2f}", "inline": True},
        {"name": "New Stop Loss", "value": sl_status, "inline": True},
    ]

    emoji = "💰" if partial_num == 1 else "💎"
    color = "success"

    send_discord_alert(
        title=f"{emoji} Partial Profit #{partial_num}: {symbol}",
        message=f"Took {size_pct}% off at +{pnl_pct:.2f}%\nLocked in ~${profit_locked:.2f}\nStop moved to {sl_status}",
        color=color,
        fields=fields,
        alert_type="partial_profit"
    )


def alert_drawdown_warning(
    daily_pnl: float,
    daily_pnl_pct: float,
    limit: float,
    pct_of_limit: float
):
    """Alert when approaching daily drawdown limit"""
    fields = [
        {"name": "Daily P/L", "value": f"${daily_pnl:,.2f}", "inline": True},
        {"name": "Daily P/L %", "value": f"{daily_pnl_pct:.2f}%", "inline": True},
        {"name": "Limit", "value": f"${limit:,.2f}", "inline": True},
        {"name": "% of Limit", "value": f"{pct_of_limit:.0f}%", "inline": True},
    ]

    send_discord_alert(
        title="⚠️ Drawdown Warning",
        message=f"Daily loss is at {pct_of_limit:.0f}% of your limit!\nConsider reducing exposure.",
        color="warning",
        fields=fields,
        alert_type="drawdown_warning"
    )


def alert_circuit_breaker(
    daily_pnl: float,
    daily_pnl_pct: float,
    limit: float,
    starting_balance: float,
    current_balance: float
):
    """Alert when circuit breaker is triggered"""
    fields = [
        {"name": "Starting Balance", "value": f"${starting_balance:,.2f}", "inline": True},
        {"name": "Current Balance", "value": f"${current_balance:,.2f}", "inline": True},
        {"name": "Daily Loss", "value": f"${abs(daily_pnl):,.2f}", "inline": True},
        {"name": "Daily Loss %", "value": f"{daily_pnl_pct:.2f}%", "inline": True},
        {"name": "Limit", "value": f"${limit:,.2f}", "inline": True},
    ]

    send_discord_alert(
        title="🛑 CIRCUIT BREAKER TRIGGERED",
        message="Daily drawdown limit exceeded!\n**All trading has been halted for today.**\n\nReset via dashboard if needed.",
        color="danger",
        fields=fields,
        alert_type="circuit_breaker"
    )


def alert_critical_error(
    error_type: str,
    message: str,
    details: str = ""
):
    """Alert for critical system errors"""
    fields = [
        {"name": "Error Type", "value": error_type, "inline": True},
        {"name": "Details", "value": details[:1000] if details else "No details", "inline": False},
    ]

    send_discord_alert(
        title=f"❌ Critical Error: {error_type}",
        message=message,
        color="danger",
        fields=fields,
        alert_type="critical_error"
    )


def alert_daily_summary(
    total_trades: int,
    winning_trades: int,
    daily_pnl: float,
    daily_pnl_pct: float,
    best_trade: Optional[dict] = None,
    worst_trade: Optional[dict] = None
):
    """Send daily trading summary"""
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    color = "profit" if daily_pnl >= 0 else "loss"
    emoji = "📈" if daily_pnl >= 0 else "📉"

    fields = [
        {"name": "Total Trades", "value": str(total_trades), "inline": True},
        {"name": "Win Rate", "value": f"{win_rate:.1f}%", "inline": True},
        {"name": "Daily P/L", "value": f"${daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)", "inline": True},
    ]

    if best_trade:
        fields.append({
            "name": "Best Trade",
            "value": f"{best_trade['symbol']}: +${best_trade['pnl']:.2f}",
            "inline": True
        })

    if worst_trade:
        fields.append({
            "name": "Worst Trade",
            "value": f"{worst_trade['symbol']}: ${worst_trade['pnl']:.2f}",
            "inline": True
        })

    send_discord_alert(
        title=f"{emoji} Daily Summary",
        message=f"Trading day complete with {daily_pnl_pct:+.2f}% return",
        color=color,
        fields=fields,
        alert_type="daily_summary"
    )


def alert_custom(
    title: str,
    message: str,
    color: str = "info",
    fields: Optional[list] = None
):
    """Send a custom alert"""
    send_discord_alert(
        title=title,
        message=message,
        color=color,
        fields=fields,
        alert_type="info"
    )


# ============================================================================
# TEST FUNCTION
# ============================================================================

def test_alerts():
    """Send a test alert to verify webhook is working"""
    settings = load_alert_settings()

    if not settings.get("discord_webhook"):
        cprint("❌ No Discord webhook configured!", "red")
        cprint("   Set your webhook URL in dashboard settings or:", "yellow")
        cprint("   src/data/alert_settings.json", "yellow")
        return False

    success = send_discord_alert(
        title="🧪 Test Alert",
        message="Your Discord alerts are working correctly!",
        color="success",
        fields=[
            {"name": "Status", "value": "✅ Connected", "inline": True},
            {"name": "Time", "value": datetime.now().strftime("%H:%M:%S"), "inline": True},
        ],
        alert_type="info"  # Bypass type check for test
    )

    if success:
        cprint("✅ Test alert sent successfully!", "green")
    else:
        cprint("❌ Failed to send test alert", "red")

    return success


if __name__ == "__main__":
    # Test the alert system
    cprint("\n🔔 Moon Dev's Alert System Test\n", "cyan", attrs=['bold'])

    settings = load_alert_settings()
    cprint(f"Alerts Enabled: {settings.get('enabled', True)}", "white")
    cprint(f"Webhook Configured: {'Yes' if settings.get('discord_webhook') else 'No'}", "white")

    if settings.get("discord_webhook"):
        test_alerts()
    else:
        cprint("\n⚠️ Configure your Discord webhook to enable alerts:", "yellow")
        cprint("1. Create a webhook in your Discord server (Server Settings > Integrations > Webhooks)", "white")
        cprint("2. Copy the webhook URL", "white")
        cprint("3. Add it to the dashboard settings or src/data/alert_settings.json", "white")
