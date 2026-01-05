"""
Live Trading Dashboard
Real-time monitoring for CryptoVerge Bot
"""

import os
import sys
from pathlib import Path
import re

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
import json
import subprocess
import signal
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# HyperLiquid imports
try:
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    import eth_account
    HYPERLIQUID_AVAILABLE = True
except ImportError:
    HYPERLIQUID_AVAILABLE = False

app = FastAPI(title="Moon Dev Trading Dashboard")

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Configuration
LOG_FILE = "/tmp/bot_output.log"
ANALYSIS_DIR = PROJECT_ROOT / "src" / "data" / "analysis_reports"
TRADING_AGENT_FILE = PROJECT_ROOT / "src" / "agents" / "trading_agent.py"

# Create analysis directory if it doesn't exist
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

# P/L History tracking
PL_HISTORY_FILE = PROJECT_ROOT / "src" / "data" / "pl_history.json"

def save_account_value(value):
    """Save current account value with timestamp for P/L tracking"""
    try:
        history = []
        if PL_HISTORY_FILE.exists():
            with open(PL_HISTORY_FILE, 'r') as f:
                history = json.load(f)

        # Add new entry
        history.append({
            "timestamp": datetime.now().isoformat(),
            "value": value
        })

        # Keep only last 7 days of data (every 15 min = 672 entries)
        history = history[-700:]

        with open(PL_HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except Exception as e:
        print(f"Error saving P/L history: {e}")

def get_pl_stats():
    """Calculate 24h and 7d P/L from history"""
    try:
        if not PL_HISTORY_FILE.exists():
            return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None, "hours_24h": 0, "hours_7d": 0}

        with open(PL_HISTORY_FILE, 'r') as f:
            history = json.load(f)

        if len(history) < 2:
            return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None, "hours_24h": 0, "hours_7d": 0}

        now = datetime.now()
        current_value = history[-1]["value"]

        # Find value from 24h ago (or closest/oldest available)
        value_24h = None
        value_7d = None
        hours_24h = 0
        hours_7d = 0

        for entry in reversed(history):
            entry_time = datetime.fromisoformat(entry["timestamp"])
            age_hours = (now - entry_time).total_seconds() / 3600

            # For 24h: get entry at 24h or use oldest if less data available
            if age_hours >= 24:
                if value_24h is None:
                    value_24h = entry["value"]
                    hours_24h = 24

            # For 7d: get entry at 7d or use oldest if less data available
            if age_hours >= 168:  # 7 days
                if value_7d is None:
                    value_7d = entry["value"]
                    hours_7d = 168
                break

        # If we don't have 24h of data, use the oldest entry
        if value_24h is None and len(history) > 0:
            oldest_entry = history[0]
            oldest_time = datetime.fromisoformat(oldest_entry["timestamp"])
            hours_24h = (now - oldest_time).total_seconds() / 3600
            value_24h = oldest_entry["value"]

        # If we don't have 7d of data, use the oldest entry
        if value_7d is None and len(history) > 0:
            oldest_entry = history[0]
            oldest_time = datetime.fromisoformat(oldest_entry["timestamp"])
            hours_7d = (now - oldest_time).total_seconds() / 3600
            value_7d = oldest_entry["value"]

        result = {
            "pnl_24h": None,
            "pnl_7d": None,
            "pnl_24h_pct": None,
            "pnl_7d_pct": None,
            "hours_24h": round(hours_24h, 1),
            "hours_7d": round(hours_7d, 1)
        }

        if value_24h:
            result["pnl_24h"] = current_value - value_24h
            result["pnl_24h_pct"] = ((current_value - value_24h) / value_24h) * 100 if value_24h else 0

        if value_7d:
            result["pnl_7d"] = current_value - value_7d
            result["pnl_7d_pct"] = ((current_value - value_7d) / value_7d) * 100 if value_7d else 0

        return result
    except Exception as e:
        print(f"Error calculating P/L: {e}")
        return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None, "hours_24h": 0, "hours_7d": 0}

def get_hyperliquid_account():
    """Get HyperLiquid account from environment"""
    private_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
    if not private_key:
        return None
    return eth_account.Account.from_key(private_key)

def get_account_info():
    """Get account balance and positions from HyperLiquid"""
    if not HYPERLIQUID_AVAILABLE:
        return {"error": "HyperLiquid SDK not available"}

    try:
        account = get_hyperliquid_account()
        if not account:
            return {"error": "No HyperLiquid account configured"}

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)

        margin_summary = user_state.get("marginSummary", {})
        account_value = float(margin_summary.get("accountValue", 0))
        margin_used = float(margin_summary.get("totalMarginUsed", 0))
        withdrawable = float(margin_summary.get("withdrawable", 0))
        available_margin = account_value - margin_used

        # Get all open orders including trigger orders (TP/SL)
        try:
            frontend_orders = info.frontend_open_orders(account.address)
        except:
            frontend_orders = []

        # Build a map of TP/SL orders by symbol
        tpsl_by_symbol = {}
        for order in frontend_orders:
            coin = order.get('coin', '')
            order_type = order.get('orderType', '')
            trigger_px = order.get('triggerPx', '')

            if coin not in tpsl_by_symbol:
                tpsl_by_symbol[coin] = {'tp': None, 'sl': None, 'tp_pct': None, 'sl_pct': None}

            if 'Take Profit' in order_type:
                tpsl_by_symbol[coin]['tp'] = float(trigger_px) if trigger_px else None
            elif 'Stop' in order_type:
                tpsl_by_symbol[coin]['sl'] = float(trigger_px) if trigger_px else None

        # Calculate total unrealized P/L from positions
        total_unrealized_pnl = 0
        positions = []
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            size = float(position.get("szi", 0))
            if size != 0:
                unrealized = float(position.get("unrealizedPnl", 0))
                total_unrealized_pnl += unrealized
                symbol = position.get("coin", "")
                entry_price = float(position.get("entryPx", 0))
                is_long = size > 0

                # Get TP/SL for this position
                tpsl = tpsl_by_symbol.get(symbol, {'tp': None, 'sl': None})
                tp_price = tpsl.get('tp')
                sl_price = tpsl.get('sl')

                # Calculate TP/SL percentages from entry
                tp_pct = None
                sl_pct = None
                if entry_price > 0:
                    if tp_price:
                        if is_long:
                            tp_pct = ((tp_price - entry_price) / entry_price) * 100
                        else:
                            tp_pct = ((entry_price - tp_price) / entry_price) * 100
                    if sl_price:
                        if is_long:
                            sl_pct = ((entry_price - sl_price) / entry_price) * 100
                        else:
                            sl_pct = ((sl_price - entry_price) / entry_price) * 100

                # Calculate actual P/L percentage (price change, not leveraged ROE)
                position_value = abs(size) * entry_price
                pnl_percent = (unrealized / position_value) * 100 if position_value > 0 else 0

                positions.append({
                    "symbol": symbol,
                    "size": size,
                    "entry_price": entry_price,
                    "pnl_percent": pnl_percent,
                    "unrealized_pnl": unrealized,
                    "side": "LONG" if is_long else "SHORT",
                    "leverage": position.get("leverage", {}).get("value", "-"),
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "tp_pct": round(tp_pct, 1) if tp_pct else None,
                    "sl_pct": round(sl_pct, 1) if sl_pct else None
                })

        # equity = total account value (includes unrealized P/L)
        # balance = equity minus unrealized P/L (the deposited amount)
        equity = account_value
        balance = account_value - total_unrealized_pnl

        # Save account value for P/L tracking
        save_account_value(account_value)

        # Get P/L stats
        pl_stats = get_pl_stats()

        return {
            "equity": equity,
            "balance": balance,
            "available_margin": available_margin,
            "unrealized_pnl": total_unrealized_pnl,
            "withdrawable": withdrawable,
            "positions": positions,
            "address": account.address[:10] + "..." + account.address[-6:],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pnl_24h": pl_stats.get("pnl_24h"),
            "pnl_24h_pct": pl_stats.get("pnl_24h_pct"),
            "pnl_7d": pl_stats.get("pnl_7d"),
            "pnl_7d_pct": pl_stats.get("pnl_7d_pct"),
            "hours_24h": pl_stats.get("hours_24h", 0),
            "hours_7d": pl_stats.get("hours_7d", 0)
        }
    except Exception as e:
        return {"error": str(e)}

def get_recent_logs(lines=50):
    """Get recent log entries"""
    try:
        if not os.path.exists(LOG_FILE):
            return ["No log file found. Is the bot running?"]

        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        return [f"Error reading logs: {e}"]

def get_current_settings():
    """Read current settings from trading_agent.py"""
    try:
        with open(TRADING_AGENT_FILE, 'r') as f:
            content = f.read()

        settings = {}

        # Extract settings using regex
        patterns = {
            'leverage': r'LEVERAGE\s*=\s*(\d+)',
            'stop_loss': r'STOP_LOSS_PERCENTAGE\s*=\s*([\d.]+)',
            'take_profit': r'TAKE_PROFIT_PERCENTAGE\s*=\s*([\d.]+)',
            'max_position_pct': r'MAX_POSITION_PERCENTAGE\s*=\s*(\d+)',
            'sleep_minutes': r'SLEEP_BETWEEN_RUNS_MINUTES\s*=\s*(\d+)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                settings[key] = float(match.group(1))

        # Get enabled symbols from SYMBOLS_CONFIG
        symbols_config = get_symbols_config()
        settings['symbols'] = [sym for sym, enabled in symbols_config.items() if enabled]
        settings['all_symbols'] = symbols_config

        return settings
    except Exception as e:
        return {"error": str(e)}

def update_setting(setting_name, value):
    """Update a setting in trading_agent.py"""
    try:
        with open(TRADING_AGENT_FILE, 'r') as f:
            content = f.read()

        patterns = {
            'leverage': (r'(LEVERAGE\s*=\s*)\d+', f'\\g<1>{int(value)}'),
            'stop_loss': (r'(STOP_LOSS_PERCENTAGE\s*=\s*)[\d.]+', f'\\g<1>{float(value)}'),
            'take_profit': (r'(TAKE_PROFIT_PERCENTAGE\s*=\s*)[\d.]+', f'\\g<1>{float(value)}'),
            'max_position_pct': (r'(MAX_POSITION_PERCENTAGE\s*=\s*)\d+', f'\\g<1>{int(value)}'),
            'sleep_minutes': (r'(SLEEP_BETWEEN_RUNS_MINUTES\s*=\s*)\d+', f'\\g<1>{int(value)}'),
        }

        if setting_name in patterns:
            pattern, replacement = patterns[setting_name]
            content = re.sub(pattern, replacement, content)

            with open(TRADING_AGENT_FILE, 'w') as f:
                f.write(content)

            return {"success": True, "message": f"{setting_name} updated to {value}"}
        else:
            return {"success": False, "message": f"Unknown setting: {setting_name}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def get_indicators():
    """Get indicator toggle settings from trading_agent.py"""
    try:
        with open(TRADING_AGENT_FILE, 'r') as f:
            content = f.read()

        # Find INDICATORS dict
        match = re.search(r'INDICATORS\s*=\s*\{([^}]+)\}', content, re.DOTALL)
        if not match:
            return {}

        indicators_text = match.group(1)
        indicators = {}

        # Parse each indicator
        for line in indicators_text.split('\n'):
            indicator_match = re.search(r'"(\w+)":\s*(True|False)', line)
            if indicator_match:
                name = indicator_match.group(1)
                value = indicator_match.group(2) == 'True'
                indicators[name] = value

        return indicators
    except Exception as e:
        print(f"Error getting indicators: {e}")
        return {}

def update_indicator(indicator_name, enabled):
    """Update an indicator toggle in trading_agent.py"""
    try:
        with open(TRADING_AGENT_FILE, 'r') as f:
            content = f.read()

        # Update the specific indicator
        pattern = rf'("{indicator_name}":\s*)(True|False)'
        replacement = f'\\g<1>{"True" if enabled else "False"}'
        new_content = re.sub(pattern, replacement, content)

        if new_content != content:
            with open(TRADING_AGENT_FILE, 'w') as f:
                f.write(new_content)
            return {"success": True, "message": f"{indicator_name} {'enabled' if enabled else 'disabled'}"}
        else:
            return {"success": False, "message": f"Indicator {indicator_name} not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def get_symbols_config():
    """Get symbol toggle settings from trading_agent.py"""
    try:
        with open(TRADING_AGENT_FILE, 'r') as f:
            content = f.read()

        # Find SYMBOLS_CONFIG dict
        match = re.search(r'SYMBOLS_CONFIG\s*=\s*\{([^}]+)\}', content, re.DOTALL)
        if not match:
            return {}

        symbols_text = match.group(1)
        symbols = {}

        # Parse each symbol
        for line in symbols_text.split('\n'):
            symbol_match = re.search(r"'(\w+)':\s*(True|False)", line)
            if symbol_match:
                name = symbol_match.group(1)
                value = symbol_match.group(2) == 'True'
                symbols[name] = value

        return symbols
    except Exception as e:
        print(f"Error getting symbols config: {e}")
        return {}

def update_symbol(symbol_name, enabled):
    """Update a symbol toggle in trading_agent.py"""
    try:
        with open(TRADING_AGENT_FILE, 'r') as f:
            content = f.read()

        # Update the specific symbol
        pattern = rf"('{symbol_name}':\s*)(True|False)"
        replacement = f"\\g<1>{'True' if enabled else 'False'}"
        new_content = re.sub(pattern, replacement, content)

        if new_content != content:
            with open(TRADING_AGENT_FILE, 'w') as f:
                f.write(new_content)
            return {"success": True, "message": f"{symbol_name} {'enabled' if enabled else 'disabled'}"}
        else:
            return {"success": False, "message": f"Symbol {symbol_name} not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def parse_analysis_reports():
    """Read analysis reports from JSON file"""
    reports = {}
    try:
        analysis_file = PROJECT_ROOT / "src" / "data" / "analysis_reports.json"
        if analysis_file.exists():
            with open(analysis_file, 'r') as f:
                reports = json.load(f)
        else:
            # Fallback: parse from logs
            logs = get_recent_logs(500)
            log_text = ''.join(logs)
            pattern = r'🎯 Token: (\w+)\n🤖 (?:Swarm |AI )?Signal: (BUY|SELL|NOTHING|DO NOTHING) \((\d+)% confidence\)'
            matches = re.findall(pattern, log_text)
            for symbol, action, confidence in matches:
                action = action.replace("DO NOTHING", "NOTHING")
                reports[symbol] = {
                    "action": action,
                    "confidence": int(confidence),
                    "analysis": "Analysis not available - run bot to generate.",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
    except Exception as e:
        print(f"Error reading analysis reports: {e}")

    return reports

def get_bot_status():
    """Check if bot is running (main.py or trading_agent.py)"""
    try:
        # Check for main.py
        result1 = subprocess.run(
            ["pgrep", "-f", "python.*main.py"],
            capture_output=True,
            text=True
        )
        # Check for trading_agent.py
        result2 = subprocess.run(
            ["pgrep", "-f", "python.*trading_agent.py"],
            capture_output=True,
            text=True
        )
        return "RUNNING" if (result1.returncode == 0 or result2.returncode == 0) else "STOPPED"
    except:
        return "UNKNOWN"


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML from external file"""
    html_file = STATIC_DIR / "dashboard.html"
    with open(html_file, "r") as f:
        return f.read()

@app.get("/api/data")
async def get_data():
    return {
        "bot_status": get_bot_status(),
        "account": get_account_info(),
        "settings": get_current_settings(),
        "analysis_reports": parse_analysis_reports(),
        "logs": get_recent_logs(50),
        "fills": get_trade_fills()
    }

@app.get("/api/fear-greed")
async def get_fear_greed():
    """Fetch Crypto Fear & Greed Index from Alternative.me API"""
    try:
        import urllib.request
        import json as json_lib
        url = "https://api.alternative.me/fng/?limit=1"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json_lib.loads(response.read().decode())
            if data.get("data"):
                fg_data = data["data"][0]
                return {
                    "value": int(fg_data.get("value", 0)),
                    "label": fg_data.get("value_classification", "Unknown"),
                    "timestamp": fg_data.get("timestamp", "")
                }
    except Exception as e:
        print(f"Error fetching Fear & Greed: {e}")
    return {"value": 0, "label": "Error", "timestamp": ""}

@app.get("/api/log-scanner-status")
async def get_log_scanner_status():
    """Check if log scanner agent is running"""
    import subprocess
    try:
        result = subprocess.run(['pgrep', '-f', 'log_scanner_agent'], capture_output=True, text=True)
        is_running = result.returncode == 0
        pid = result.stdout.strip() if is_running else None

        # Get last scan time from state file
        last_scan = None
        state_file = PROJECT_ROOT / "src" / "data" / "log_scanner" / "scanner_state.json"
        if state_file.exists():
            with open(state_file, 'r') as f:
                state = json.load(f)
                last_scan_ts = state.get('last_scan')
                if last_scan_ts:
                    from datetime import datetime
                    last_scan = datetime.fromtimestamp(last_scan_ts).strftime('%H:%M:%S')

        return {
            "running": is_running,
            "pid": pid,
            "last_scan": last_scan
        }
    except Exception as e:
        return {"running": False, "error": str(e)}

@app.get("/api/daily-drawdown")
async def get_daily_drawdown():
    """Get daily drawdown status for circuit breaker"""
    from datetime import date
    try:
        drawdown_file = PROJECT_ROOT / "src" / "data" / "drawdown_state.json"

        # Default response
        result = {
            "enabled": True,
            "trading_allowed": True,
            "daily_pnl": 0,
            "daily_pnl_pct": 0,
            "limit_usd": 50,
            "starting_balance": 0,
            "current_balance": 0,
            "circuit_breaker_triggered": False,
            "triggered_at": None,
            "date": date.today().isoformat()
        }

        # Try to get settings from trading_agent
        try:
            import sys
            sys.path.insert(0, str(PROJECT_ROOT / "src" / "agents"))
            from trading_agent import DAILY_DRAWDOWN_ENABLED, DAILY_DRAWDOWN_LIMIT_USD
            result["enabled"] = DAILY_DRAWDOWN_ENABLED
            result["limit_usd"] = DAILY_DRAWDOWN_LIMIT_USD
        except:
            pass

        # Load state file
        if drawdown_file.exists():
            with open(drawdown_file, 'r') as f:
                state = json.load(f)
                result["starting_balance"] = state.get("starting_balance", 0)
                result["circuit_breaker_triggered"] = state.get("circuit_breaker_triggered", False)
                result["triggered_at"] = state.get("triggered_at")
                result["date"] = state.get("date", date.today().isoformat())

        # Get current balance
        if HYPERLIQUID_AVAILABLE:
            account = get_hyperliquid_account()
            if account:
                info = Info(constants.MAINNET_API_URL, skip_ws=True)
                user_state = info.user_state(account.address)
                current_balance = float(user_state.get('marginSummary', {}).get('accountValue', 0))
                result["current_balance"] = current_balance

                starting = result["starting_balance"] or current_balance
                if starting > 0:
                    daily_pnl = current_balance - starting
                    daily_pnl_pct = (daily_pnl / starting) * 100
                    result["daily_pnl"] = daily_pnl
                    result["daily_pnl_pct"] = daily_pnl_pct
                    result["trading_allowed"] = not result["circuit_breaker_triggered"]

        return result
    except Exception as e:
        return {"error": str(e), "trading_allowed": True}

@app.post("/api/daily-drawdown/reset")
async def reset_daily_drawdown():
    """Reset daily drawdown circuit breaker"""
    from datetime import date
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)
        current_balance = float(user_state.get('marginSummary', {}).get('accountValue', 0))

        # Save new state
        drawdown_file = PROJECT_ROOT / "src" / "data" / "drawdown_state.json"
        state = {
            "date": date.today().isoformat(),
            "starting_balance": current_balance,
            "circuit_breaker_triggered": False,
            "triggered_at": None
        }
        with open(drawdown_file, 'w') as f:
            json.dump(state, f, indent=2)

        return {"success": True, "message": f"Reset successful. New starting balance: ${current_balance:,.2f}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ============================================================================
# ALERTS API
# ============================================================================

ALERT_SETTINGS_FILE = PROJECT_ROOT / "src" / "data" / "alert_settings.json"

@app.get("/api/alerts")
async def get_alert_settings():
    """Get alert settings"""
    try:
        default_settings = {
            "enabled": True,
            "discord_webhook": "",
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
            }
        }

        if ALERT_SETTINGS_FILE.exists():
            with open(ALERT_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Merge with defaults
                for key in default_settings:
                    if key not in settings:
                        settings[key] = default_settings[key]
                return settings

        return default_settings
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/alerts")
async def save_alert_settings(request: dict):
    """Save alert settings"""
    try:
        ALERT_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_SETTINGS_FILE, 'w') as f:
            json.dump(request, f, indent=2)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/alerts/test")
async def test_alert():
    """Send a test alert"""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from alerts import test_alerts, load_alert_settings

        settings = load_alert_settings()
        if not settings.get("discord_webhook"):
            return {"success": False, "message": "No Discord webhook configured"}

        success = test_alerts()
        return {"success": success, "message": "Test alert sent!" if success else "Failed to send test alert"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/prices")
async def get_prices():
    """Get current prices and 24h change for tracked coins from HyperLiquid"""
    try:
        if HYPERLIQUID_AVAILABLE:
            info = Info(constants.MAINNET_API_URL, skip_ws=True)

            # Get meta and asset contexts (includes prevDayPx)
            meta_and_ctxs = info.meta_and_asset_ctxs()
            universe = meta_and_ctxs[0]['universe']
            asset_ctxs = meta_and_ctxs[1]

            symbols = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
            prices = {}

            for i, asset in enumerate(universe):
                symbol = asset['name']
                if symbol in symbols and i < len(asset_ctxs):
                    ctx = asset_ctxs[i]
                    current_price = float(ctx.get('midPx', 0))
                    prev_day_price = float(ctx.get('prevDayPx', 0))

                    # Calculate 24h change percentage
                    if prev_day_price > 0:
                        change_pct = ((current_price - prev_day_price) / prev_day_price) * 100
                    else:
                        change_pct = 0.0

                    prices[symbol] = {
                        "price": current_price,
                        "change": change_pct
                    }

            return {"prices": prices}
    except Exception as e:
        print(f"Error fetching prices: {e}")
    return {"prices": {}}

@app.post("/api/start")
async def start_bot():
    try:
        if get_bot_status() == "RUNNING":
            return {"success": False, "message": "Bot is already running"}

        bot_dir = str(PROJECT_ROOT)
        subprocess.Popen(
            [f"{bot_dir}/venv/bin/python", "src/main.py"],
            cwd=bot_dir,
            stdout=open(LOG_FILE, 'w'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )
        return {"success": True, "message": "Bot started"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/stop")
async def stop_bot():
    try:
        result = subprocess.run(["pkill", "-f", "python.*main.py"], capture_output=True)
        return {"success": True, "message": "Bot stopped"} if result.returncode == 0 else {"success": False, "message": "No bot running"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/restart")
async def restart_bot():
    try:
        subprocess.run(["pkill", "-f", "python.*main.py"], capture_output=True)
        await asyncio.sleep(2)

        bot_dir = str(PROJECT_ROOT)
        subprocess.Popen(
            [f"{bot_dir}/venv/bin/python", "src/main.py"],
            cwd=bot_dir,
            stdout=open(LOG_FILE, 'w'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )
        return {"success": True, "message": "Bot restarted"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/clear-logs")
async def clear_logs():
    try:
        with open(LOG_FILE, 'w') as f:
            f.write("")
        return {"success": True, "message": "Logs cleared"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/run-analysis")
async def run_analysis():
    """Stop current bot, clear logs, and start fresh analysis"""
    try:
        bot_dir = PROJECT_ROOT
        python_path = bot_dir / "venv" / "bin" / "python"
        agent_path = bot_dir / "src" / "agents" / "trading_agent.py"

        # Kill any existing trading agent processes (non-blocking)
        subprocess.run(["pkill", "-f", "trading_agent.py"], capture_output=True, timeout=2)

        # Clear logs for fresh output
        with open(LOG_FILE, 'w') as f:
            f.write("Starting fresh analysis...\n")

        # Start trading agent in background with proper detachment
        # Using Path objects handles spaces in paths correctly
        subprocess.Popen(
            [str(python_path), str(agent_path)],
            cwd=str(bot_dir),
            stdout=open(LOG_FILE, 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )

        return {"success": True, "message": "Analysis started - check Live Output"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/setting/{setting_name}/{value}")
async def update_setting_endpoint(setting_name: str, value: str):
    return update_setting(setting_name, value)

@app.post("/api/confidence/{value}")
async def update_confidence_endpoint(value: int):
    """Update the min confidence threshold for trading"""
    try:
        settings_file = PROJECT_ROOT / "src" / "data" / "dashboard_settings.json"
        settings = {"min_confidence": value, "updated_at": datetime.now().isoformat()}
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=4)
        return {"success": True, "message": f"Min confidence set to {value}%"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/confidence")
async def get_confidence_endpoint():
    """Get the current min confidence threshold"""
    try:
        settings_file = PROJECT_ROOT / "src" / "data" / "dashboard_settings.json"
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                return {"min_confidence": settings.get("min_confidence", 70)}
        return {"min_confidence": 70}
    except:
        return {"min_confidence": 70}

@app.get("/api/auto-tpsl")
async def get_auto_tpsl():
    """Get auto TP/SL settings including ATR configuration"""
    try:
        settings_file = PROJECT_ROOT / "src" / "data" / "dashboard_settings.json"
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                return {
                    "enabled": settings.get("auto_tpsl_enabled", False),
                    "max_sl": settings.get("auto_tpsl_max_sl", 7),
                    "mode": settings.get("auto_tpsl_mode", "moderate"),
                    # ATR settings
                    "use_atr": settings.get("auto_tpsl_use_atr", False),
                    "atr_period": settings.get("atr_period", 14),
                    "atr_sl_multiplier": settings.get("atr_sl_multiplier", 2.0),
                    "atr_tp_multiplier": settings.get("atr_tp_multiplier", 3.0),
                    "atr_min_sl": settings.get("atr_min_sl", 1.0),
                }
        return {
            "enabled": False, "max_sl": 7, "mode": "moderate",
            "use_atr": False, "atr_period": 14, "atr_sl_multiplier": 2.0,
            "atr_tp_multiplier": 3.0, "atr_min_sl": 1.0
        }
    except:
        return {
            "enabled": False, "max_sl": 7, "mode": "moderate",
            "use_atr": False, "atr_period": 14, "atr_sl_multiplier": 2.0,
            "atr_tp_multiplier": 3.0, "atr_min_sl": 1.0
        }

@app.post("/api/auto-tpsl")
async def save_auto_tpsl(request: dict):
    """Save auto TP/SL settings including ATR configuration"""
    try:
        settings_file = PROJECT_ROOT / "src" / "data" / "dashboard_settings.json"

        # Load existing settings
        settings = {}
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)

        # Update auto TP/SL settings
        settings["auto_tpsl_enabled"] = request.get("enabled", False)
        settings["auto_tpsl_max_sl"] = request.get("max_sl", 7)
        settings["auto_tpsl_mode"] = request.get("mode", "moderate")

        # Update ATR settings
        settings["auto_tpsl_use_atr"] = request.get("use_atr", False)
        settings["atr_period"] = request.get("atr_period", 14)
        settings["atr_sl_multiplier"] = request.get("atr_sl_multiplier", 2.0)
        settings["atr_tp_multiplier"] = request.get("atr_tp_multiplier", 3.0)
        settings["atr_min_sl"] = request.get("atr_min_sl", 1.0)

        settings["updated_at"] = datetime.now().isoformat()

        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=4)

        atr_status = "ATR stops enabled" if request.get("use_atr") else "Fixed % stops"
        return {"success": True, "message": f"Auto TP/SL settings saved ({atr_status})"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/goals")
async def get_goals():
    """Get trading goals"""
    try:
        goals_file = PROJECT_ROOT / "src" / "data" / "trading_goals.json"
        if goals_file.exists():
            with open(goals_file, 'r') as f:
                return json.load(f)
        return {}
    except:
        return {}

@app.post("/api/goals")
async def save_goals(request: dict):
    """Save trading goals"""
    try:
        goals_file = PROJECT_ROOT / "src" / "data" / "trading_goals.json"
        request["updated_at"] = datetime.now().isoformat()
        with open(goals_file, 'w') as f:
            json.dump(request, f, indent=4)
        return {"success": True, "message": "Goals saved"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/scan-settings")
async def get_scan_settings():
    """Get scan interval settings"""
    try:
        settings_file = PROJECT_ROOT / "src" / "data" / "scan_settings.json"
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                return json.load(f)
        return {"preset": "standard", "auto_adjust": True}
    except:
        return {"preset": "standard", "auto_adjust": True}

@app.post("/api/scan-settings")
async def save_scan_settings(request: dict):
    """Save scan interval settings"""
    try:
        settings_file = PROJECT_ROOT / "src" / "data" / "scan_settings.json"
        preset = request.get("preset", "standard")
        auto_adjust = request.get("auto_adjust", True)

        # Preset descriptions for feedback
        presets = {
            "scalp": "Scalp (5min scans, 15m candles)",
            "active": "Active (15min scans, 1H candles)",
            "standard": "Standard (30min scans, 1H candles)",
            "swing": "Swing (60min scans, 4H candles)",
            "patient": "Patient (120min scans, 4H candles)",
        }

        settings = {
            "preset": preset,
            "auto_adjust": auto_adjust,
            "updated_at": datetime.now().isoformat()
        }
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=4)

        msg = f"Scan interval: {presets.get(preset, preset)}"
        if auto_adjust:
            msg += " (auto-adjust ON)"
        return {"success": True, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/active-interval")
async def get_active_interval():
    """Get the current ACTIVE scan interval (accounts for auto-adjust)"""
    try:
        import src.nice_funcs_hyperliquid as n

        settings_file = PROJECT_ROOT / "src" / "data" / "scan_settings.json"
        settings = {"preset": "standard", "auto_adjust": True}
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)

        preset = settings.get("preset", "standard")
        auto_adjust = settings.get("auto_adjust", True)

        # Preset definitions
        presets = {
            "scalp": {"interval": 5, "timeframe": "15m", "name": "Scalp"},
            "active": {"interval": 15, "timeframe": "1H", "name": "Active"},
            "standard": {"interval": 30, "timeframe": "1H", "name": "Standard"},
            "swing": {"interval": 60, "timeframe": "4H", "name": "Swing"},
            "patient": {"interval": 120, "timeframe": "4H", "name": "Patient"},
        }

        active_preset = preset
        volatility = None
        volatility_level = "unknown"

        if auto_adjust:
            # Calculate volatility
            try:
                data = n.get_data("BTC", timeframe="1H", bars=20, add_indicators=True)
                if data is not None and not data.empty and 'atr' in data.columns:
                    atr = data['atr'].iloc[-1]
                    close = data['close'].iloc[-1]
                    volatility = (atr / close) * 100 if close > 0 else 2.0

                    # Determine active preset based on volatility
                    if volatility > 3.0:
                        active_preset = "active"
                        volatility_level = "High"
                    elif volatility >= 1.5:
                        active_preset = "standard"
                        volatility_level = "Medium"
                    else:
                        active_preset = "swing"
                        volatility_level = "Low"
            except:
                volatility = None

        active = presets.get(active_preset, presets["standard"])

        return {
            "saved_preset": preset,
            "active_preset": active_preset,
            "auto_adjust": auto_adjust,
            "interval_minutes": active["interval"],
            "timeframe": active["timeframe"],
            "name": active["name"],
            "volatility": round(volatility, 2) if volatility else None,
            "volatility_level": volatility_level
        }
    except Exception as e:
        return {"error": str(e), "active_preset": "standard", "interval_minutes": 30}

@app.get("/api/trade-analysis")
async def get_trade_analysis():
    """Get trade analysis/reasoning for open positions"""
    try:
        analysis_file = PROJECT_ROOT / "src" / "data" / "trade_analysis.json"
        if analysis_file.exists():
            with open(analysis_file, 'r') as f:
                return json.load(f)
        return {"trades": []}
    except:
        return {"trades": []}

@app.post("/api/trade-analysis/clear")
async def clear_trade_analysis():
    """Clear all trade analysis"""
    try:
        # Clear trade_analysis.json
        analysis_file = PROJECT_ROOT / "src" / "data" / "trade_analysis.json"
        with open(analysis_file, 'w') as f:
            json.dump({"trades": []}, f, indent=4)

        # Also clear analysis_reports.json
        reports_file = PROJECT_ROOT / "src" / "data" / "analysis_reports.json"
        with open(reports_file, 'w') as f:
            json.dump({}, f, indent=4)

        return {"success": True, "message": "Trade analysis cleared"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/indicator/{indicator_name}/{enabled}")
async def update_indicator_endpoint(indicator_name: str, enabled: str):
    return update_indicator(indicator_name, enabled.lower() == 'true')

@app.get("/api/indicators")
async def get_indicators_endpoint():
    return {"indicators": get_indicators()}

@app.get("/api/symbols")
async def get_symbols_endpoint():
    return {"symbols": get_symbols_config()}

@app.post("/api/symbol/{symbol_name}/{enabled}")
async def update_symbol_endpoint(symbol_name: str, enabled: str):
    return update_symbol(symbol_name, enabled.lower() == 'true')

TRADE_FILLS_FILE = PROJECT_ROOT / "src" / "data" / "trade_fills.json"

def save_trade_fill(symbol, qty, price, side="BUY"):
    """Save individual trade fill to history"""
    try:
        fills = {"fills": []}
        if TRADE_FILLS_FILE.exists():
            with open(TRADE_FILLS_FILE, 'r') as f:
                fills = json.load(f)

        fills["fills"].append({
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "side": side,
            "timestamp": datetime.now().isoformat(),
            "value": qty * price
        })

        with open(TRADE_FILLS_FILE, 'w') as f:
            json.dump(fills, f, indent=4)
    except Exception as e:
        print(f"Error saving trade fill: {e}")

def get_trade_fills(symbol=None):
    """Get trade fills, optionally filtered by symbol"""
    try:
        if TRADE_FILLS_FILE.exists():
            with open(TRADE_FILLS_FILE, 'r') as f:
                data = json.load(f)
                fills = data.get("fills", [])
                if symbol:
                    fills = [f for f in fills if f.get("symbol") == symbol]
                return fills
    except:
        pass
    return []

def clear_fills_for_symbol(symbol):
    """Clear fills when position is closed"""
    try:
        if TRADE_FILLS_FILE.exists():
            with open(TRADE_FILLS_FILE, 'r') as f:
                data = json.load(f)
            data["fills"] = [f for f in data.get("fills", []) if f.get("symbol") != symbol]
            with open(TRADE_FILLS_FILE, 'w') as f:
                json.dump(data, f, indent=4)
    except:
        pass

@app.post("/api/force-buy/{symbol}")
async def force_buy(symbol: str):
    """Force buy a symbol with 25% of account - with detailed logging"""
    import time
    import traceback
    start_time = time.time()

    print(f"\n{'='*50}")
    print(f"⚡ FORCE BUY REQUEST: {symbol}")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # Step 1: Check HyperLiquid SDK
        if not HYPERLIQUID_AVAILABLE:
            print("   ❌ HyperLiquid SDK not available")
            return {"success": False, "message": "HyperLiquid SDK not available"}
        print("   ✓ HyperLiquid SDK available")

        # Step 2: Import and get account
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        import nice_funcs_hyperliquid as n

        account = n._get_account_from_env()
        if not account:
            print("   ❌ No account configured (check HYPER_LIQUID_ETH_PRIVATE_KEY)")
            return {"success": False, "message": "No account configured"}
        print(f"   ✓ Account loaded: {account.address[:10]}...")

        # Step 3: Get account value
        try:
            value = n.get_account_value(account)
            print(f"   ✓ Account value: ${value:.2f}")
        except Exception as e:
            print(f"   ❌ Failed to get account value: {e}")
            return {"success": False, "message": f"Failed to get account value: {e}"}

        # Step 4: Calculate position size
        usd_size = value * 0.25
        print(f"   ✓ Trade size (25%): ${usd_size:.2f}")

        if usd_size < 10:
            print(f"   ❌ Trade size ${usd_size:.2f} below $10 minimum")
            return {"success": False, "message": f"Trade size ${usd_size:.2f} below $10 minimum"}

        # Step 5: Read leverage setting
        leverage = 20  # Default
        try:
            with open(TRADING_AGENT_FILE, 'r') as f:
                content = f.read()
                lev_match = re.search(r'LEVERAGE\s*=\s*(\d+)', content)
                if lev_match:
                    leverage = int(lev_match.group(1))
        except:
            pass
        print(f"   ✓ Leverage setting: {leverage}x")

        # Step 6: Set leverage
        try:
            n.set_leverage(symbol, leverage, account)
            print(f"   ✓ Leverage set for {symbol}")
        except Exception as e:
            print(f"   ⚠️ Leverage warning: {e}")

        # Step 7: Execute market buy
        print(f"   → Executing market buy...")
        try:
            result = n.market_buy(symbol, usd_size, account)
        except Exception as e:
            print(f"   ❌ Market buy exception: {e}")
            traceback.print_exc()
            return {"success": False, "message": f"Market buy failed: {e}"}

        # Step 8: Check result
        print(f"   → Result: {result}")

        if result and result.get('status') == 'ok':
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])

            if statuses and 'filled' in statuses[0]:
                fill_data = statuses[0]['filled']
                fill_qty = float(fill_data.get('totalSz', 0))
                fill_price = float(fill_data.get('avgPx', 0))

                print(f"   ✅ FILLED: {fill_qty} {symbol} @ ${fill_price}")

                # Save fill
                if fill_qty > 0 and fill_price > 0:
                    save_trade_fill(symbol, fill_qty, fill_price, "BUY")

                # Read TP/SL settings
                tp_pct = 10.0
                sl_pct = 3.0
                try:
                    with open(TRADING_AGENT_FILE, 'r') as f:
                        content = f.read()
                        tp_match = re.search(r'TAKE_PROFIT_PERCENTAGE\s*=\s*([\d.]+)', content)
                        sl_match = re.search(r'STOP_LOSS_PERCENTAGE\s*=\s*([\d.]+)', content)
                        if tp_match:
                            tp_pct = float(tp_match.group(1))
                        if sl_match:
                            sl_pct = float(sl_match.group(1))
                except:
                    pass

                # TP/SL will be set by market_buy auto_tpsl

                elapsed = time.time() - start_time
                msg = f"Bought {fill_qty:.5f} {symbol} @ ${fill_price:,.4f} in {elapsed:.1f}s"
                print(f"   ✅ {msg}")
                print(f"{'='*50}\n")
                return {"success": True, "message": msg}

            elif statuses and 'error' in statuses[0]:
                error = statuses[0]['error']
                print(f"   ❌ Order error: {error}")
                print(f"{'='*50}\n")
                return {"success": False, "message": f"Order rejected: {error}"}

            else:
                print(f"   ❌ Unexpected status: {statuses}")
                print(f"{'='*50}\n")
                return {"success": False, "message": f"Unexpected response: {statuses}"}

        else:
            error_msg = f"Buy failed - status: {result.get('status') if result else 'None'}"
            if result:
                error_msg += f" | response: {result}"
            print(f"   ❌ {error_msg}")
            print(f"{'='*50}\n")
            return {"success": False, "message": error_msg}

    except Exception as e:
        print(f"   ❌ EXCEPTION: {e}")
        traceback.print_exc()
        print(f"{'='*50}\n")
        return {"success": False, "message": f"Exception: {str(e)}"}

@app.post("/api/close-position/{symbol}")
async def close_position(symbol: str):
    """Close a position for a given symbol - IMMEDIATE, FAST, RELIABLE"""
    import time
    start_time = time.time()

    print(f"⚡ CLOSE REQUEST: {symbol}")

    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        from hyperliquid.exchange import Exchange

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        exchange = Exchange(account, constants.MAINNET_API_URL)

        # Step 1: Get position size (needed for response)
        t1 = time.time()
        user_state = info.user_state(account.address)
        position_size = 0
        entry_price = 0
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            if position.get("coin") == symbol:
                position_size = float(position.get("szi", 0))
                entry_price = float(position.get("entryPx", 0))
                break
        print(f"   Position check: {time.time()-t1:.3f}s")

        if position_size == 0:
            return {"success": False, "message": f"No open position for {symbol}"}

        close_size = abs(position_size)
        is_long = position_size > 0

        # Step 2: Cancel orders for this symbol (TP/SL can interfere)
        t2 = time.time()
        try:
            open_orders = info.open_orders(account.address)
            symbol_orders = [o for o in open_orders if o['coin'] == symbol]
            if symbol_orders:
                for order in symbol_orders:
                    try:
                        exchange.cancel(symbol, order['oid'])
                    except:
                        pass
                print(f"   Cancelled {len(symbol_orders)} orders: {time.time()-t2:.3f}s")
        except:
            pass

        # Step 3: MARKET CLOSE - this is the critical part
        t3 = time.time()
        result = exchange.market_close(symbol)
        close_time = time.time() - t3
        print(f"   Market close: {close_time:.3f}s")

        # Check result
        if result.get('status') == 'ok':
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'filled' in statuses[0]:
                filled = statuses[0]['filled']
                avg_px = float(filled.get('avgPx', 0))
                total_sz = filled.get('totalSz', close_size)

                # Calculate P/L
                if entry_price > 0 and avg_px > 0:
                    if is_long:
                        pnl = (avg_px - entry_price) * float(total_sz)
                    else:
                        pnl = (entry_price - avg_px) * float(total_sz)
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                else:
                    pnl_str = ""

                total_time = time.time() - start_time
                clear_fills_for_symbol(symbol)

                msg = f"Closed {symbol} @ ${avg_px:.4f} ({pnl_str}) in {total_time:.2f}s"
                print(f"   ✅ {msg}")
                return {"success": True, "message": msg}

            # No fill in response - check for errors
            if statuses and 'error' in statuses[0]:
                error = statuses[0]['error']
                print(f"   ❌ Error: {error}")
                return {"success": False, "message": f"Close failed: {error}"}

        # Unexpected response - verify position
        print(f"   ⚠️ Unexpected response, verifying...")
        time.sleep(0.3)
        user_state = info.user_state(account.address)
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            if position.get("coin") == symbol:
                remaining = float(position.get("szi", 0))
                if remaining == 0:
                    clear_fills_for_symbol(symbol)
                    return {"success": True, "message": f"Closed {symbol}"}

        # Position not found = closed
        clear_fills_for_symbol(symbol)
        return {"success": True, "message": f"Closed {symbol}"}

    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        return {"success": False, "message": str(e)}

@app.post("/api/reverse-position/{symbol}")
async def reverse_position(symbol: str):
    """Reverse a position - close current and open opposite direction"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        # Import nice_funcs for trading
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        import nice_funcs_hyperliquid as n
        import time

        # Get current position
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)

        position_size = 0
        entry_price = 0
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            if position.get("coin") == symbol:
                position_size = float(position.get("szi", 0))
                entry_price = float(position.get("entryPx", 0))
                break

        if position_size == 0:
            return {"success": False, "message": f"No open position for {symbol}"}

        is_long = position_size > 0
        abs_size = abs(position_size)
        position_value = abs_size * entry_price

        # Step 1: Close current position
        if is_long:
            n.market_sell(symbol, abs_size, account)
        else:
            n.market_buy(symbol, abs_size, account)

        time.sleep(1)

        # Step 2: Open opposite position with same value
        if is_long:
            # Was long, now go short
            n.market_sell(symbol, abs_size, account)
            new_side = "SHORT"
        else:
            # Was short, now go long
            n.market_buy(symbol, abs_size, account)
            new_side = "LONG"

        # Clear old fills and update
        clear_fills_for_symbol(symbol)

        return {"success": True, "message": f"Reversed {symbol}: {'LONG' if is_long else 'SHORT'} -> {new_side}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/set-tpsl/{symbol}")
async def set_tpsl(symbol: str):
    """Set TP/SL orders for an existing position"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        # Import nice_funcs
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from nice_funcs_hyperliquid import place_tp_sl_orders, get_position

        # Get current position
        positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = get_position(symbol, account)

        if not im_in_pos:
            return {"success": False, "message": f"No open position for {symbol}"}

        # Convert to float (API returns strings)
        pos_size = float(pos_size)
        entry_px = float(entry_px)

        # Read TP/SL settings from trading_agent.py
        tp_pct = 12.0  # Default
        sl_pct = 5.0   # Default
        try:
            with open(TRADING_AGENT_FILE, 'r') as f:
                content = f.read()
                import re
                tp_match = re.search(r'TAKE_PROFIT_PERCENTAGE\s*=\s*([\d.]+)', content)
                sl_match = re.search(r'STOP_LOSS_PERCENTAGE\s*=\s*([\d.]+)', content)
                if tp_match:
                    tp_pct = float(tp_match.group(1))
                if sl_match:
                    sl_pct = float(sl_match.group(1))
        except:
            pass

        # Place TP/SL orders
        result = place_tp_sl_orders(symbol, entry_px, abs(pos_size), is_long, tp_pct, sl_pct, account)

        if result.get("tp_result") and result.get("sl_result"):
            return {"success": True, "message": f"TP/SL set for {symbol} (TP: +{tp_pct}%, SL: -{sl_pct}%)"}
        else:
            return {"success": False, "message": f"Partial success: {result}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/equity-history")
async def get_equity_history():
    """Get equity history for charting"""
    try:
        if not PL_HISTORY_FILE.exists():
            return {"history": []}

        with open(PL_HISTORY_FILE, 'r') as f:
            history = json.load(f)

        # Format for chart.js
        chart_data = []
        for entry in history:
            chart_data.append({
                "x": entry["timestamp"],
                "y": entry["value"]
            })

        return {"history": chart_data}
    except Exception as e:
        return {"history": [], "error": str(e)}

@app.post("/api/run-backtest")
async def run_backtest_endpoint():
    """Run the backtest and return results"""
    try:
        import subprocess
        import json as json_lib

        # Run the backtest script
        result = subprocess.run(
            [f"{PROJECT_ROOT}/venv/bin/python", "-m", "src.scripts.backtest"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )

        # Find the most recent backtest result file
        backtest_dir = PROJECT_ROOT / "src" / "data" / "backtest_results"
        if backtest_dir.exists():
            result_files = sorted(backtest_dir.glob("backtest_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
            if result_files:
                with open(result_files[0], 'r') as f:
                    data = json_lib.load(f)
                    return {
                        "success": True,
                        "summary": data.get("summary", {}),
                        "close_reasons": data.get("close_reasons", {}),
                        "config": data.get("config", {})
                    }

        # If no result file found, check if backtest returned an error
        if result.returncode != 0:
            return {"error": f"Backtest failed: {result.stderr or result.stdout}"}

        return {"error": "No backtest results found"}
    except subprocess.TimeoutExpired:
        return {"error": "Backtest timed out after 2 minutes"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/set-all-tpsl")
async def set_all_tpsl():
    """Set TP/SL orders for all open positions"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)

        positions_updated = []
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            size = float(position.get("szi", 0))
            if size != 0:
                symbol = position.get("coin", "")
                result = await set_tpsl(symbol)
                positions_updated.append(f"{symbol}: {result.get('message', 'unknown')}")

        if positions_updated:
            return {"success": True, "message": f"Updated: {', '.join(positions_updated)}"}
        else:
            return {"success": False, "message": "No open positions"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/cancel-duplicate-orders")
async def cancel_duplicate_orders():
    """Cancel duplicate TP/SL orders, keeping only 2 most recent per symbol"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        exchange = Exchange(account, constants.MAINNET_API_URL)

        # Get all open orders
        open_orders = info.open_orders(account.address)

        # Group orders by symbol
        from collections import defaultdict
        orders_by_symbol = defaultdict(list)
        for order in open_orders:
            orders_by_symbol[order['coin']].append(order)

        # Keep only 2 most recent per symbol, cancel the rest
        orders_to_cancel = []
        for symbol, orders in orders_by_symbol.items():
            sorted_orders = sorted(orders, key=lambda x: int(x['oid']), reverse=True)
            if len(sorted_orders) > 2:
                orders_to_cancel.extend(sorted_orders[2:])

        if not orders_to_cancel:
            return {"success": True, "message": f"No duplicates found ({len(open_orders)} orders, all correct)"}

        # Cancel duplicates
        cancelled = 0
        for order in orders_to_cancel:
            try:
                exchange.cancel(order['coin'], order['oid'])
                cancelled += 1
            except Exception:
                pass

        remaining = len(open_orders) - cancelled
        return {"success": True, "message": f"Cancelled {cancelled} duplicates. {remaining} orders remaining."}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/cancel-all-orders")
async def cancel_all_orders():
    """Cancel ALL open orders (TP/SL)"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        from hyperliquid.exchange import Exchange

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        exchange = Exchange(account, constants.MAINNET_API_URL)

        # Get all open orders
        open_orders = info.open_orders(account.address)

        if not open_orders:
            return {"success": True, "message": "No open orders to cancel"}

        # Cancel all orders
        cancelled = 0
        for order in open_orders:
            try:
                exchange.cancel(order['coin'], order['oid'])
                cancelled += 1
            except Exception:
                pass

        return {"success": True, "message": f"Cancelled {cancelled} orders"}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ============================================================================
# LOG STREAMING API - For External Log Analyzer
# ============================================================================

LOG_FILES_CONFIG = {
    "dashboard": "/tmp/dashboard.log",
    "trading_bot": "/tmp/bot_output.log",
}

@app.get("/api/logs/stream")
async def stream_logs(source: str = "all", lines: int = 100, since_bytes: int = 0):
    """Stream logs for external log analyzer

    Args:
        source: 'dashboard', 'trading_bot', or 'all'
        lines: Number of recent lines to return
        since_bytes: Return only content after this byte position (for incremental reads)
    """
    try:
        result = {"logs": {}, "positions": {}}

        sources = LOG_FILES_CONFIG.keys() if source == "all" else [source]

        for src in sources:
            filepath = LOG_FILES_CONFIG.get(src)
            if not filepath or not os.path.exists(filepath):
                continue

            with open(filepath, 'r') as f:
                f.seek(0, 2)
                file_size = f.tell()

                if since_bytes > 0 and since_bytes < file_size:
                    # Incremental read
                    f.seek(since_bytes)
                    content = f.read()
                else:
                    # Read last N lines
                    f.seek(0)
                    all_lines = f.readlines()
                    content = ''.join(all_lines[-lines:])

                result["logs"][src] = content
                result["positions"][src] = file_size

        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/logs/state")
async def get_system_state():
    """Get current system state for verification (positions, orders, account)"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"error": "HyperLiquid not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"error": "No account configured"}

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)
        open_orders = info.open_orders(account.address)

        positions = []
        for pos in user_state.get('assetPositions', []):
            p = pos.get('position', {})
            size = float(p.get('szi', 0))
            if size != 0:
                positions.append({
                    'symbol': p.get('coin'),
                    'size': size,
                    'entry': float(p.get('entryPx', 0)),
                    'pnl': float(p.get('unrealizedPnl', 0)),
                    'pnl_pct': float(p.get('returnOnEquity', 0)) * 100,
                    'leverage': p.get('leverage', {}).get('value', 1),
                    'liquidation': p.get('liquidationPx'),
                })

        orders = [{
            'symbol': o.get('coin'),
            'side': o.get('side'),
            'size': o.get('sz'),
            'price': o.get('limitPx'),
            'type': o.get('orderType', 'limit'),
            'oid': o.get('oid'),
        } for o in open_orders]

        return {
            'account_value': float(user_state.get('marginSummary', {}).get('accountValue', 0)),
            'margin_used': float(user_state.get('marginSummary', {}).get('totalMarginUsed', 0)),
            'withdrawable': float(user_state.get('withdrawable', 0)),
            'positions': positions,
            'open_orders': orders,
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/logs/health")
async def health_check():
    """Health check endpoint for Log Analyzer"""
    return {
        "status": "ok",
        "service": "trading_bot_dashboard",
        "timestamp": datetime.now().isoformat(),
        "hyperliquid_available": HYPERLIQUID_AVAILABLE,
    }


def start_log_scanner():
    """Auto-start the log scanner agent if not already running"""
    import subprocess
    try:
        # Check if already running
        result = subprocess.run(['pgrep', '-f', 'log_scanner_agent'], capture_output=True)
        if result.returncode == 0:
            print("✅ Log Scanner already running")
            return

        # Start log scanner in background
        scanner_path = PROJECT_ROOT / "src" / "agents" / "log_scanner_agent.py"
        if scanner_path.exists():
            subprocess.Popen(
                [sys.executable, str(scanner_path)],
                stdout=open('/tmp/log_scanner.log', 'w'),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            print("✅ Log Scanner auto-started")
        else:
            print(f"⚠️ Log Scanner not found at {scanner_path}")
    except Exception as e:
        print(f"⚠️ Could not start Log Scanner: {e}")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("CryptoVerge Bot Dashboard")
    print("="*60)
    print("\nStarting dashboard at: http://localhost:8081")

    # Auto-start log scanner
    start_log_scanner()

    print("Press Ctrl+C to stop\n")

    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="warning")
