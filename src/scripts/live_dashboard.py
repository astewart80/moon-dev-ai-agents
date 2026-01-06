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
    from hyperliquid.exchange import Exchange
    import eth_account
    HYPERLIQUID_AVAILABLE = True
except ImportError:
    HYPERLIQUID_AVAILABLE = False

app = FastAPI(title="Moon Dev Trading Dashboard")

# === PERSISTENT HYPERLIQUID CONNECTION WITH WEBSOCKET ===
# Reuse connections for faster execution (avoid 10+ sec per new connection)
# WebSocket subscriptions provide real-time data without REST latency
_hl_info = None
_hl_exchange = None
_hl_account = None

# === CACHED DATA (updated via WebSocket) ===
_cached_meta = None  # Symbol metadata - static, fetch once
_cached_mids = {}    # Real-time prices from WebSocket
_cached_user_state = None  # Position data
_ws_initialized = False

def _on_all_mids(data):
    """WebSocket callback for real-time price updates"""
    global _cached_mids
    if data and 'mids' in data:
        _cached_mids = {k: float(v) for k, v in data['mids'].items()}

def _on_user_events(data):
    """WebSocket callback for position/balance updates"""
    global _cached_user_state
    # User events contain position updates - cache them
    if data:
        _cached_user_state = data

def init_websocket_subscriptions():
    """Initialize WebSocket subscriptions for real-time data"""
    global _ws_initialized, _hl_info, _hl_account

    if _ws_initialized or not _hl_info or not _hl_account:
        return

    try:
        from hyperliquid.utils.types import AllMidsSubscription, UserEventsSubscription

        # Subscribe to all mid prices (real-time)
        _hl_info.subscribe({"type": "allMids"}, _on_all_mids)

        # Subscribe to user events (positions, fills)
        _hl_info.subscribe({"type": "userEvents", "user": _hl_account.address}, _on_user_events)

        _ws_initialized = True
        print("   ✅ WebSocket subscriptions active (real-time prices & positions)")
    except Exception as e:
        print(f"   ⚠️ WebSocket subscription failed: {e} - falling back to REST")

def get_cached_meta():
    """Get cached metadata (symbols, decimals) - fetched once"""
    global _cached_meta, _hl_info
    if _cached_meta is None and _hl_info:
        _cached_meta = _hl_info.meta()
    return _cached_meta

def get_cached_price(symbol):
    """Get cached price from WebSocket (instant) or fallback to REST"""
    global _cached_mids, _hl_info
    if symbol in _cached_mids:
        return _cached_mids[symbol]
    # Fallback to REST if WebSocket hasn't delivered yet
    if _hl_info:
        mids = _hl_info.all_mids()
        return float(mids.get(symbol, 0))
    return 0

def get_cached_mids():
    """Get all cached prices"""
    global _cached_mids, _hl_info
    if _cached_mids:
        return _cached_mids
    # Fallback
    if _hl_info:
        return {k: float(v) for k, v in _hl_info.all_mids().items()}
    return {}

def get_hl_connection():
    """Get persistent HyperLiquid connection (creates once, reuses)"""
    global _hl_info, _hl_exchange, _hl_account, _cached_meta

    if not HYPERLIQUID_AVAILABLE:
        return None, None, None

    if _hl_account is None:
        private_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
        if not private_key:
            return None, None, None
        _hl_account = eth_account.Account.from_key(private_key)

    if _hl_info is None:
        # Enable WebSocket for real-time data
        _hl_info = Info(constants.MAINNET_API_URL, skip_ws=False)
        # Pre-cache metadata
        _cached_meta = _hl_info.meta()
        # Initialize WebSocket subscriptions
        init_websocket_subscriptions()

    if _hl_exchange is None:
        _hl_exchange = Exchange(_hl_account, constants.MAINNET_API_URL)

    return _hl_info, _hl_exchange, _hl_account

def reset_hl_connection():
    """Reset connection if it becomes stale"""
    global _hl_info, _hl_exchange, _cached_meta, _cached_mids, _ws_initialized
    _hl_info = None
    _hl_exchange = None
    _cached_meta = None
    _cached_mids = {}
    _ws_initialized = False

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
DEPOSITS_FILE = PROJECT_ROOT / "src" / "data" / "deposits.json"

# Deposit detection threshold - if value jumps more than this in one update, it's likely a deposit
DEPOSIT_THRESHOLD_PCT = 15.0  # 15% jump = likely deposit, not trading
DEPOSIT_THRESHOLD_USD = 50.0  # Or $50+ jump in short time

def load_deposits():
    """Load deposit tracking data"""
    try:
        if DEPOSITS_FILE.exists():
            with open(DEPOSITS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"total_deposits": 0, "deposit_history": []}

def save_deposits(data):
    """Save deposit tracking data"""
    try:
        with open(DEPOSITS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving deposits: {e}")

def save_account_value(value):
    """Save current account value with timestamp for P/L tracking, detecting deposits"""
    try:
        history = []
        if PL_HISTORY_FILE.exists():
            with open(PL_HISTORY_FILE, 'r') as f:
                history = json.load(f)

        # Detect deposits by checking for large jumps
        if len(history) > 0:
            last_value = history[-1]["value"]
            change = value - last_value
            change_pct = (change / last_value) * 100 if last_value > 0 else 0

            # If big positive jump, it's likely a deposit (not trading gains)
            if change > DEPOSIT_THRESHOLD_USD and change_pct > DEPOSIT_THRESHOLD_PCT:
                deposits = load_deposits()
                deposits["total_deposits"] += change
                deposits["deposit_history"].append({
                    "timestamp": datetime.now().isoformat(),
                    "amount": change,
                    "before": last_value,
                    "after": value
                })
                save_deposits(deposits)
                print(f"💰 Deposit detected: ${change:.2f} (total deposits: ${deposits['total_deposits']:.2f})")

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
    """Calculate 24h and 7d P/L from history, excluding deposits"""
    try:
        if not PL_HISTORY_FILE.exists():
            return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None, "hours_24h": 0, "hours_7d": 0, "total_deposits": 0}

        with open(PL_HISTORY_FILE, 'r') as f:
            history = json.load(f)

        if len(history) < 2:
            return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None, "hours_24h": 0, "hours_7d": 0, "total_deposits": 0}

        # Load deposits to exclude from P/L
        deposits = load_deposits()
        total_deposits = deposits.get("total_deposits", 0)

        # Calculate deposits within time windows
        deposits_24h = 0
        deposits_7d = 0
        now = datetime.now()

        for dep in deposits.get("deposit_history", []):
            dep_time = datetime.fromisoformat(dep["timestamp"])
            age_hours = (now - dep_time).total_seconds() / 3600
            if age_hours <= 24:
                deposits_24h += dep["amount"]
            if age_hours <= 168:  # 7 days
                deposits_7d += dep["amount"]

        current_value = history[-1]["value"]

        # Find value from 24h ago (or closest/oldest available)
        value_24h = None
        value_7d = None
        baseline_time_24h = None
        baseline_time_7d = None
        hours_24h = 0
        hours_7d = 0

        for entry in reversed(history):
            entry_time = datetime.fromisoformat(entry["timestamp"])
            age_hours = (now - entry_time).total_seconds() / 3600

            # For 24h: get entry at 24h or use oldest if less data available
            if age_hours >= 24:
                if value_24h is None:
                    value_24h = entry["value"]
                    baseline_time_24h = entry_time
                    hours_24h = 24

            # For 7d: get entry at 7d or use oldest if less data available
            if age_hours >= 168:  # 7 days
                if value_7d is None:
                    value_7d = entry["value"]
                    baseline_time_7d = entry_time
                    hours_7d = 168
                break

        # If we don't have 24h of data, use the oldest entry
        if value_24h is None and len(history) > 0:
            oldest_entry = history[0]
            oldest_time = datetime.fromisoformat(oldest_entry["timestamp"])
            hours_24h = (now - oldest_time).total_seconds() / 3600
            value_24h = oldest_entry["value"]
            baseline_time_24h = oldest_time

        # If we don't have 7d of data, use the oldest entry
        if value_7d is None and len(history) > 0:
            oldest_entry = history[0]
            oldest_time = datetime.fromisoformat(oldest_entry["timestamp"])
            hours_7d = (now - oldest_time).total_seconds() / 3600
            value_7d = oldest_entry["value"]
            baseline_time_7d = oldest_time

        # Calculate deposits AFTER baseline timestamps (not just within time windows)
        # Only deposits after the baseline affect the P/L calculation
        deposits_since_baseline_24h = 0
        deposits_since_baseline_7d = 0

        for dep in deposits.get("deposit_history", []):
            dep_time = datetime.fromisoformat(dep["timestamp"])
            # Only count deposits that happened AFTER the baseline
            if baseline_time_24h and dep_time > baseline_time_24h:
                deposits_since_baseline_24h += dep["amount"]
            if baseline_time_7d and dep_time > baseline_time_7d:
                deposits_since_baseline_7d += dep["amount"]

        result = {
            "pnl_24h": None,
            "pnl_7d": None,
            "pnl_24h_pct": None,
            "pnl_7d_pct": None,
            "hours_24h": round(hours_24h, 1),
            "hours_7d": round(hours_7d, 1),
            "total_deposits": total_deposits,
            "deposits_24h": deposits_since_baseline_24h,
            "deposits_7d": deposits_since_baseline_7d
        }

        if value_24h:
            # Subtract only deposits that happened AFTER the baseline
            raw_change = current_value - value_24h
            trading_pnl = raw_change - deposits_since_baseline_24h
            result["pnl_24h"] = trading_pnl
            # Calculate % based on starting value (before deposits)
            result["pnl_24h_pct"] = (trading_pnl / value_24h) * 100 if value_24h else 0

        if value_7d:
            raw_change = current_value - value_7d
            trading_pnl = raw_change - deposits_since_baseline_7d
            result["pnl_7d"] = trading_pnl
            result["pnl_7d_pct"] = (trading_pnl / value_7d) * 100 if value_7d else 0

        return result
    except Exception as e:
        print(f"Error calculating P/L: {e}")
        return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None, "hours_24h": 0, "hours_7d": 0, "total_deposits": 0}

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

                # Get liquidation price
                liq_price = position.get("liquidationPx")
                if liq_price:
                    liq_price = float(liq_price)

                # Calculate mark price from unrealized PnL
                # For long: mark = entry + (unrealized / size)
                # For short: mark = entry - (unrealized / abs(size))
                mark_price = entry_price
                if abs(size) > 0:
                    mark_price = entry_price + (unrealized / abs(size)) if is_long else entry_price - (unrealized / abs(size))

                # Calculate distance to liquidation %
                liq_distance = None
                if liq_price and mark_price > 0:
                    if is_long:
                        liq_distance = ((mark_price - liq_price) / mark_price) * 100
                    else:
                        liq_distance = ((liq_price - mark_price) / mark_price) * 100

                # Calculate Risk:Reward ratio
                rr_ratio = None
                if tp_pct and sl_pct and sl_pct > 0:
                    rr_ratio = round(tp_pct / sl_pct, 2)

                # Get leverage value
                leverage = position.get("leverage", {})
                if isinstance(leverage, dict):
                    leverage_val = leverage.get("value", 1)
                else:
                    leverage_val = leverage if leverage else 1

                # Calculate margin used (position value / leverage)
                margin_used = position_value / float(leverage_val) if leverage_val else position_value

                # Calculate ROE % (Return on Equity - P/L relative to margin)
                roe_percent = (unrealized / margin_used) * 100 if margin_used > 0 else 0

                positions.append({
                    "symbol": symbol,
                    "size": size,
                    "entry_price": entry_price,
                    "mark_price": round(mark_price, 6) if mark_price else None,
                    "pnl_percent": pnl_percent,
                    "roe_percent": round(roe_percent, 2),
                    "unrealized_pnl": unrealized,
                    "margin_used": round(margin_used, 2),
                    "side": "LONG" if is_long else "SHORT",
                    "leverage": leverage_val,
                    "liq_price": liq_price,
                    "liq_distance": round(liq_distance, 1) if liq_distance else None,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "tp_pct": round(tp_pct, 1) if tp_pct else None,
                    "sl_pct": round(sl_pct, 1) if sl_pct else None,
                    "rr_ratio": rr_ratio
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

@app.post("/api/manual-trade")
async def manual_trade(request: Request):
    """Execute a manual trade with custom amount and leverage"""
    import time
    import traceback
    from pydantic import BaseModel

    try:
        body = await request.json()
        symbol = body.get('symbol', 'BTC').upper()
        amount = float(body.get('amount', 50))
        leverage = int(body.get('leverage', 3))
        direction = body.get('direction', 'LONG').upper()
        tp_pct = float(body.get('tp_pct', 10.0))
        sl_pct = float(body.get('sl_pct', 3.0))
    except Exception as e:
        return {"success": False, "message": f"Invalid request body: {e}"}

    print(f"\n{'='*50}")
    print(f"⚡ MANUAL TRADE REQUEST")
    print(f"   Symbol: {symbol}")
    print(f"   Direction: {direction}")
    print(f"   Amount: ${amount}")
    print(f"   Leverage: {leverage}x")
    print(f"   TP: {tp_pct}% | SL: {sl_pct}%")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        if not HYPERLIQUID_AVAILABLE:
            print("   ❌ HyperLiquid SDK not available")
            return {"success": False, "message": "HyperLiquid SDK not available"}

        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        import nice_funcs_hyperliquid as n

        account = n._get_account_from_env()
        if not account:
            return {"success": False, "message": "No account configured"}
        print(f"   ✓ Account: {account.address[:10]}...")

        # Validate amount
        if amount < 10:
            return {"success": False, "message": f"Amount ${amount} below $10 minimum"}

        # Check max exposure before trading
        allowed, exposure_pct, msg = n.check_max_exposure(account, amount)
        if not allowed:
            return {"success": False, "message": f"Max exposure exceeded: {msg}"}

        # Set leverage
        try:
            n.set_leverage(symbol, leverage, account)
            print(f"   ✓ Leverage set to {leverage}x")
        except Exception as e:
            print(f"   ⚠️ Leverage warning: {e}")

        # Execute trade based on direction
        if direction == 'LONG':
            print(f"   → Executing LONG ${amount} {symbol}...")
            result = n.market_buy(symbol, amount, account, auto_tpsl=True, tp_pct=tp_pct, sl_pct=sl_pct)
        else:
            print(f"   → Executing SHORT ${amount} {symbol}...")
            result = n.open_short(symbol, amount, leverage=leverage, account=account, auto_tpsl=True, tp_pct=tp_pct, sl_pct=sl_pct)

        if result and result.get('status') == 'ok':
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'filled' in statuses[0]:
                fill_data = statuses[0]['filled']
                fill_qty = float(fill_data.get('totalSz', 0))
                fill_price = float(fill_data.get('avgPx', 0))

                print(f"   ✅ FILLED: {fill_qty} {symbol} @ ${fill_price}")
                save_trade_fill(symbol, fill_qty, fill_price, "BUY" if direction == "LONG" else "SELL")

                return {
                    "success": True,
                    "message": f"{direction} {symbol} filled",
                    "filled_qty": fill_qty,
                    "filled_price": fill_price,
                    "direction": direction
                }
            else:
                return {"success": False, "message": f"Order not filled: {statuses}"}
        else:
            return {"success": False, "message": f"Order failed: {result}"}

    except Exception as e:
        print(f"   ❌ Error: {e}")
        traceback.print_exc()
        return {"success": False, "message": str(e)}


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

@app.post("/api/manual-trade")
async def manual_trade(request: dict):
    """Execute a manual trade with specified parameters"""
    import time
    import traceback
    start_time = time.time()

    symbol = request.get("symbol", "BTC").upper()
    side = request.get("side", "long").lower()
    size_usd = float(request.get("size_usd", 50))
    leverage = int(request.get("leverage", 5))

    print(f"\n{'='*50}")
    print(f"⚡ MANUAL TRADE: {side.upper()} {symbol}")
    print(f"   Size: ${size_usd}, Leverage: {leverage}x")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        import nice_funcs_hyperliquid as n

        account = n._get_account_from_env()
        if not account:
            return {"success": False, "message": "No account configured"}

        # Validate size
        if size_usd < 10:
            return {"success": False, "message": f"Size ${size_usd} below $10 minimum"}

        # Set leverage
        try:
            n.set_leverage(symbol, leverage, account)
            print(f"   ✓ Leverage set to {leverage}x")
        except Exception as e:
            print(f"   ⚠️ Leverage warning: {e}")

        # Execute trade
        print(f"   → Executing {side} order...")
        if side == "long":
            result = n.market_buy(symbol, size_usd, account)
        else:
            result = n.market_sell(symbol, size_usd, account)

        print(f"   → Result: {result}")

        if result and result.get('status') == 'ok':
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])

            if statuses and 'filled' in statuses[0]:
                fill_data = statuses[0]['filled']
                fill_qty = float(fill_data.get('totalSz', 0))
                fill_price = float(fill_data.get('avgPx', 0))

                side_text = "LONG" if side == "long" else "SHORT"
                elapsed = time.time() - start_time
                msg = f"Opened {side_text} {fill_qty:.5f} {symbol} @ ${fill_price:,.4f} in {elapsed:.1f}s"
                print(f"   ✅ {msg}")
                print(f"{'='*50}\n")

                # Save fill
                if fill_qty > 0 and fill_price > 0:
                    save_trade_fill(symbol, fill_qty, fill_price, "BUY" if side == "long" else "SELL")

                return {"success": True, "message": msg}

            elif statuses and 'error' in statuses[0]:
                error = statuses[0]['error']
                print(f"   ❌ Order error: {error}")
                return {"success": False, "message": f"Order rejected: {error}"}

        error_msg = f"Trade failed - status: {result.get('status') if result else 'None'}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}

    except Exception as e:
        print(f"   ❌ EXCEPTION: {e}")
        traceback.print_exc()
        return {"success": False, "message": f"Exception: {str(e)}"}


@app.post("/api/close-position/{symbol}")
async def close_position(symbol: str):
    """Close a position for a given symbol - ULTRA FAST with connection pooling"""
    import time
    start_time = time.time()

    print(f"⚡ FAST CLOSE: {symbol}")

    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        # Use pooled connections - saves 200-500ms per call
        info, exchange, account = get_hl_connection()
        if not account:
            return {"success": False, "message": "No account configured"}

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

        # Step 2: Cancel ALL orders for this symbol in ONE batch call (not sequential)
        t2 = time.time()
        try:
            open_orders = info.open_orders(account.address)
            symbol_orders = [o for o in open_orders if o['coin'] == symbol]
            if symbol_orders:
                # BATCH CANCEL - single API call instead of N sequential calls
                cancel_requests = [{"coin": symbol, "oid": o['oid']} for o in symbol_orders]
                if len(cancel_requests) == 1:
                    exchange.cancel(symbol, cancel_requests[0]['oid'])
                else:
                    # Use bulk_cancel for multiple orders (single API call)
                    try:
                        exchange.bulk_cancel(cancel_requests)
                    except:
                        # Fallback: cancel first order only (TP or SL) - faster than all
                        exchange.cancel(symbol, symbol_orders[0]['oid'])
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

        # Unexpected response - verify position (no sleep - just check immediately)
        print(f"   ⚠️ Unexpected response, verifying...")
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
    """Reverse a position - close current and open opposite direction - FAST"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        # Use pooled connections
        info, exchange, account = get_hl_connection()
        if not account:
            return {"success": False, "message": "No account configured"}

        # Import nice_funcs for trading
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        import nice_funcs_hyperliquid as n

        # Get current position using pooled connection
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

        # FAST REVERSAL: Close and open in quick succession (no 1s sleep)
        # Step 1: Close current position
        if is_long:
            n.market_sell(symbol, abs_size, account)
        else:
            n.market_buy(symbol, abs_size, account)

        # Step 2: Open opposite position immediately (removed 1s sleep)
        if is_long:
            n.market_sell(symbol, abs_size, account)
            new_side = "SHORT"
        else:
            n.market_buy(symbol, abs_size, account)
            new_side = "LONG"

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


@app.get("/api/correlation")
async def get_correlation_exposure():
    """Get correlation exposure data for current positions"""
    try:
        # Import correlation groups from trading agent
        from src.agents.trading_agent import CORRELATION_GROUPS, USE_CORRELATION_SIZING, CORRELATION_REDUCTION_PCT, MAX_CORRELATED_EXPOSURE_PCT

        if not HYPERLIQUID_AVAILABLE:
            return {"error": "HyperLiquid not available"}

        # Get account data using same pattern as other endpoints
        account = get_hyperliquid_account()
        if not account:
            return {"error": "No HyperLiquid account configured"}

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)
        account_value = float(user_state.get('marginSummary', {}).get('accountValue', 0))

        # Get positions from user_state
        positions = []
        for pos in user_state.get('assetPositions', []):
            position = pos.get('position', {})
            if position:
                positions.append({
                    'symbol': position.get('coin', ''),
                    'szi': position.get('szi', 0),
                    'entryPx': position.get('entryPx', 0)
                })

        # Calculate group exposure
        group_exposure = {}
        position_groups = {}

        for pos in positions:
            symbol = pos.get('symbol', '')
            size = abs(float(pos.get('szi', 0)))
            entry_px = float(pos.get('entryPx', 0))

            if size > 0 and entry_px > 0:
                size_usd = size * entry_px

                # Find correlation groups for this symbol
                for group_name, tokens in CORRELATION_GROUPS.items():
                    if symbol.upper() in [t.upper() for t in tokens]:
                        if group_name not in group_exposure:
                            group_exposure[group_name] = 0
                            position_groups[group_name] = []
                        group_exposure[group_name] += size_usd
                        position_groups[group_name].append({
                            'symbol': symbol,
                            'size_usd': size_usd
                        })

        # Calculate percentages
        group_data = []
        for group_name, exposure in group_exposure.items():
            pct = (exposure / account_value * 100) if account_value > 0 else 0
            group_data.append({
                'group': group_name,
                'exposure_usd': exposure,
                'exposure_pct': round(pct, 1),
                'max_pct': MAX_CORRELATED_EXPOSURE_PCT,
                'at_limit': pct >= MAX_CORRELATED_EXPOSURE_PCT,
                'positions': position_groups.get(group_name, [])
            })

        return {
            'enabled': USE_CORRELATION_SIZING,
            'reduction_pct': CORRELATION_REDUCTION_PCT,
            'max_group_pct': MAX_CORRELATED_EXPOSURE_PCT,
            'account_value': account_value,
            'groups': sorted(group_data, key=lambda x: x['exposure_usd'], reverse=True),
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


def calculate_fibonacci_levels(df, lookback=50):
    """Calculate Fibonacci retracement levels from recent swing high/low"""
    try:
        recent = df.tail(lookback)
        swing_high = recent['high'].max()
        swing_low = recent['low'].min()
        diff = swing_high - swing_low

        return {
            'swing_high': swing_high,
            'swing_low': swing_low,
            'fib_236': swing_high - (diff * 0.236),
            'fib_382': swing_high - (diff * 0.382),
            'fib_500': swing_high - (diff * 0.500),
            'fib_618': swing_high - (diff * 0.618),
            'fib_786': swing_high - (diff * 0.786),
        }
    except:
        return None


def get_timeframe_signal(df):
    """Get trend signal from a timeframe dataframe"""
    if df is None or df.empty:
        return {'trend': 'NEUTRAL', 'rsi': 50, 'strength': 0}

    latest = df.iloc[-1]
    rsi = latest.get('rsi', 50)
    adx = latest.get('ADX_14', 20)
    sma_20 = latest.get('sma_20', 0)
    sma_50 = latest.get('sma_50', 0)
    close = latest.get('close', 0)

    # Determine trend
    if close > sma_20 > sma_50 and rsi > 50:
        trend = 'BULLISH'
    elif close < sma_20 < sma_50 and rsi < 50:
        trend = 'BEARISH'
    else:
        trend = 'NEUTRAL'

    return {
        'trend': trend,
        'rsi': rsi,
        'adx': adx,
        'strength': adx if adx else 20
    }


@app.post("/api/fast-trade")
async def fast_trade(request: dict):
    """
    ULTRA-FAST buy/sell using cached WebSocket data + persistent connection.
    ~2-3 seconds vs 4-5 seconds with REST lookups.
    """
    import time
    start = time.time()

    symbol_input = request.get("symbol", "BTC")
    side = request.get("side", "long").lower()  # "long" or "short"
    size_usd = float(request.get("size_usd", 100))
    leverage = int(request.get("leverage", 10))

    try:
        info, exchange, account = get_hl_connection()
        if not exchange:
            return {"success": False, "message": "No connection"}

        # Use CACHED metadata (instant - no REST call)
        meta = get_cached_meta()
        if not meta:
            meta = info.meta()

        # Find symbol (case-insensitive match)
        asset_index = None
        symbol = None
        for i, asset in enumerate(meta['universe']):
            if asset['name'].upper() == symbol_input.upper():
                asset_index = i
                symbol = asset['name']  # Use exact name from exchange
                break

        if asset_index is None:
            suggestions = [a['name'] for a in meta['universe'] if symbol_input.upper() in a['name'].upper()][:5]
            return {"success": False, "message": f"Symbol '{symbol_input}' not found. Try: {suggestions}"}

        # Use CACHED price from WebSocket (instant - no REST call)
        price = get_cached_price(symbol)
        if price == 0:
            # Fallback to REST if cache miss
            all_mids = info.all_mids()
            price = float(all_mids[symbol])

        # Get size decimals
        sz_decimals = meta['universe'][asset_index]['szDecimals']

        # Calculate size
        raw_size = size_usd / price
        size = round(raw_size, sz_decimals)

        # Set leverage (skip if turbo mode - uses existing leverage)
        turbo = request.get("turbo", False)
        if not turbo:
            try:
                exchange.update_leverage(leverage, symbol, is_cross=True)
            except:
                pass  # May already be set

        # Execute order with tighter slippage for speed
        is_buy = (side == "long")
        print(f"⚡ FAST TRADE: {side.upper()} {size} {symbol} @ ${price:.4f}")

        order_result = exchange.market_open(
            symbol,
            is_buy=is_buy,
            sz=size,
            slippage=0.02  # Tighter slippage = faster fills
        )

        elapsed = time.time() - start
        print(f"   Order result: {order_result}")

        if order_result and order_result.get('status') == 'ok':
            statuses = order_result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'filled' in statuses[0]:
                fill = statuses[0]['filled']
                fill_price = float(fill.get('avgPx', price))
                fill_size = float(fill.get('totalSz', size))
                side_str = "LONG" if is_buy else "SHORT"

                print(f"   ✅ FILLED: {fill_size} {symbol} @ ${fill_price:.4f}")

                # Auto-set TP/SL orders
                try:
                    import sys
                    sys.path.insert(0, str(PROJECT_ROOT / "src"))
                    import nice_funcs_hyperliquid as n

                    # Read TP/SL from settings
                    tp_pct = 10.0
                    sl_pct = 3.0
                    try:
                        with open(TRADING_AGENT_FILE, 'r') as f:
                            content = f.read()
                            tp_match = re.search(r'TAKE_PROFIT_PERCENTAGE\s*=\s*([\d.]+)', content)
                            sl_match = re.search(r'STOP_LOSS_PERCENTAGE\s*=\s*([\d.]+)', content)
                            if tp_match: tp_pct = float(tp_match.group(1))
                            if sl_match: sl_pct = float(sl_match.group(1))
                    except:
                        pass

                    n.place_tp_sl_orders(symbol, fill_price, fill_size, is_buy, tp_pct, sl_pct, account)
                    print(f"   ✅ TP/SL set: TP +{tp_pct}%, SL -{sl_pct}%")
                except Exception as e:
                    print(f"   ⚠️ TP/SL failed: {e}")

                return {
                    "success": True,
                    "message": f"Opened {side_str} {fill_size} {symbol} @ ${fill_price:.4f} ({elapsed:.1f}s)",
                    "fill_price": fill_price,
                    "fill_size": fill_size,
                    "elapsed": elapsed
                }
            else:
                print(f"   ❌ Not filled: {statuses}")
                return {"success": False, "message": f"Order not filled: {statuses}", "elapsed": elapsed}

        print(f"   ❌ Order failed: {order_result}")
        return {"success": False, "message": f"Order failed: {order_result}", "elapsed": elapsed}

    except Exception as e:
        import traceback
        print(f"   ❌ Exception: {e}")
        traceback.print_exc()
        return {"success": False, "message": str(e)}


@app.get("/api/connection-status")
async def connection_status():
    """Check WebSocket connection and cache status"""
    global _ws_initialized, _cached_mids, _cached_meta

    mids_count = len(_cached_mids)
    has_meta = _cached_meta is not None
    sample_prices = {k: v for k, v in list(_cached_mids.items())[:5]} if _cached_mids else {}

    return {
        "websocket_active": _ws_initialized,
        "cached_prices": mids_count,
        "cached_meta": has_meta,
        "sample_prices": sample_prices,
        "status": "FAST" if (_ws_initialized and mids_count > 0) else "NORMAL"
    }


@app.post("/api/fast-close")
async def fast_close(request: dict):
    """
    FAST close position using persistent connection.
    """
    import time
    start = time.time()

    symbol_input = request.get("symbol", "BTC")
    percent = float(request.get("percent", 100))  # % of position to close

    try:
        info, exchange, account = get_hl_connection()
        if not exchange:
            return {"success": False, "message": "No connection"}

        # Get current position - match case-insensitive
        user_state = info.user_state(account.address)
        position = None
        symbol = None
        for pos in user_state.get('assetPositions', []):
            coin = pos['position']['coin']
            if coin.upper() == symbol_input.upper():
                position = pos['position']
                symbol = coin  # Use exact symbol from exchange
                break

        if not position:
            return {"success": False, "message": f"No position for {symbol_input}"}

        size = float(position['szi'])
        if size == 0:
            return {"success": False, "message": "Position size is 0"}

        # Get size decimals from CACHED metadata (instant - no REST call)
        meta = get_cached_meta()
        if not meta:
            meta = info.meta()
        sz_decimals = 0
        for asset in meta['universe']:
            if asset['name'] == symbol:
                sz_decimals = asset['szDecimals']
                break

        close_size = round(abs(size) * (percent / 100), sz_decimals)

        if close_size == 0:
            return {"success": False, "message": f"Calculated close size is 0 (position too small)"}

        # Close position
        result = exchange.market_close(symbol, sz=close_size, slippage=0.05)
        elapsed = time.time() - start

        if result and result.get('status') == 'ok':
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'filled' in statuses[0]:
                fill = statuses[0]['filled']
                fill_price = float(fill.get('avgPx', 0))
                return {
                    "success": True,
                    "message": f"Closed {percent}% {symbol} @ ${fill_price:.4f} ({elapsed:.1f}s)",
                    "elapsed": elapsed
                }

        return {"success": False, "message": f"Close failed: {result}", "elapsed": elapsed}

    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/fast-execute")
async def fast_execute(action: str = "trim", pnl_threshold: float = 10.0):
    """
    FAST position management - no indicator analysis, just P/L-based execution.
    action: "trim" (50%), "close" (100%), or "close-losers"
    pnl_threshold: minimum P/L % for trim/close (default 10%)
    """
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"error": "HyperLiquid not available"}

        # Use persistent connection for speed
        info, exchange, account = get_hl_connection()
        if not account:
            return {"error": "No account configured"}

        from src.nice_funcs_hyperliquid import get_all_positions
        positions = get_all_positions(account)

        if not positions:
            return {"success": True, "message": "No positions", "actions": []}

        # Build list of trades to execute
        from concurrent.futures import ThreadPoolExecutor, as_completed

        trades_to_execute = []
        for pos in positions:
            symbol = pos['symbol']
            pnl_pct = pos['pnl_percent']
            size = pos['size']

            trim_pct = 0
            if action == "trim" and pnl_pct >= pnl_threshold:
                trim_pct = 50
            elif action == "close" and pnl_pct >= pnl_threshold:
                trim_pct = 100
            elif action == "close-losers" and pnl_pct <= -abs(pnl_threshold):
                trim_pct = 100

            if trim_pct > 0:
                trades_to_execute.append({
                    'symbol': symbol,
                    'size': abs(size) * (trim_pct / 100),
                    'pnl_pct': pnl_pct,
                    'trim_pct': trim_pct
                })

        def execute_trade(trade):
            try:
                result = exchange.market_close(trade['symbol'], sz=trade['size'], slippage=0.05)
                if result and result.get('status') == 'ok':
                    label = 'Closed' if trade['trim_pct'] == 100 else 'Trimmed'
                    return f"{label} {trade['trim_pct']}% {trade['symbol']} @ {trade['pnl_pct']:+.1f}%"
                return f"FAILED {trade['symbol']}: no ok status"
            except Exception as e:
                return f"FAILED {trade['symbol']}: {str(e)[:40]}"

        actions = []
        if trades_to_execute:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(execute_trade, t) for t in trades_to_execute]
                for future in as_completed(futures):
                    actions.append(future.result())

        return {"success": True, "actions": actions, "positions_checked": len(positions)}

    except Exception as e:
        return {"error": str(e)}


@app.get("/api/recommendations")
async def get_recommendations(execute: bool = False):
    """
    Enhanced AI-powered trading recommendations with:
    - Funding rates analysis
    - Multi-timeframe confluence (1H, 4H, Daily)
    - Fibonacci retracement levels
    - GOAL-BASED risk management (daily target, max loss, $1M mission)
    """
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"error": "HyperLiquid not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"error": "No HyperLiquid account configured"}

        from src.nice_funcs_hyperliquid import (
            get_all_positions, get_data, ask_bid, get_sz_px_decimals,
            get_account_value, get_position, get_funding_rates
        )
        from hyperliquid.exchange import Exchange
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time as time_module

        # Retry wrapper for API calls that may fail with broken pipe
        def get_data_with_retry(symbol, timeframe, bars, add_indicators=True, max_retries=2):
            for attempt in range(max_retries):
                try:
                    result = get_data(symbol, timeframe=timeframe, bars=bars, add_indicators=add_indicators)
                    return result
                except (BrokenPipeError, ConnectionResetError, OSError) as e:
                    if attempt < max_retries - 1:
                        time_module.sleep(0.3)
                        continue
                    return None
            return None

        # Parallel data fetcher for all symbols/timeframes
        def fetch_all_data_parallel(symbols):
            data_cache = {}
            tasks = []
            for symbol in symbols:
                for tf, bars in [('1h', 50), ('4h', 50), ('1d', 30)]:
                    tasks.append((symbol, tf, bars))

            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    executor.submit(get_data_with_retry, sym, tf, bars): (sym, tf)
                    for sym, tf, bars in tasks
                }
                for future in as_completed(futures):
                    sym, tf = futures[future]
                    try:
                        data_cache[(sym, tf)] = future.result()
                    except:
                        data_cache[(sym, tf)] = None
            return data_cache

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)
        acct_value = float(user_state.get('marginSummary', {}).get('accountValue', 0))
        free_margin = float(user_state.get('withdrawable', 0))

        # === LOAD TRADING GOALS ===
        goals = {"daily_profit_target": 200, "weekly_profit_target": 1000, "max_daily_loss": 50, "target_account_balance": 1000000}
        try:
            goals_file = PROJECT_ROOT / "src" / "data" / "trading_goals.json"
            if goals_file.exists():
                with open(goals_file, 'r') as f:
                    goals = json.load(f)
        except:
            pass

        daily_target = goals.get("daily_profit_target", 200)
        max_daily_loss = goals.get("max_daily_loss", 50)
        ultimate_target = goals.get("target_account_balance", 1000000)

        # === CALCULATE DAILY P/L PROGRESS ===
        pl_stats = get_pl_stats()
        daily_pnl = pl_stats.get("pnl_24h", 0) or 0
        weekly_pnl = pl_stats.get("pnl_7d", 0) or 0

        # Calculate total unrealized P/L from current positions
        positions = get_all_positions(account)
        total_unrealized = sum(
            abs(p['size']) * p['entry_price'] * (p['pnl_percent'] / 100)
            for p in positions
        )

        # Effective daily progress = realized (24h) + unrealized
        effective_daily_pnl = daily_pnl + total_unrealized
        distance_to_target = daily_target - effective_daily_pnl
        target_progress_pct = (effective_daily_pnl / daily_target * 100) if daily_target > 0 else 0

        # Mission progress towards $1M
        mission_progress_pct = (acct_value / ultimate_target * 100)
        distance_to_million = ultimate_target - acct_value

        # === DETERMINE TRADING MODE ===
        # Aggressive: behind on daily goal, need to catch up
        # Normal: on track
        # Conservative: near daily loss limit or already hit goal
        # Protective: exceeded goal, protect gains

        if effective_daily_pnl <= -max_daily_loss * 0.8:
            trading_mode = "PROTECTIVE"  # Near max loss - minimize risk
            mode_multiplier = 0.5  # Lower thresholds to exit sooner
        elif effective_daily_pnl >= daily_target * 1.5:
            trading_mode = "PROTECTIVE"  # Well past goal - protect gains
            mode_multiplier = 0.7
        elif effective_daily_pnl >= daily_target:
            trading_mode = "CONSERVATIVE"  # Hit goal - secure profits
            mode_multiplier = 0.8
        elif effective_daily_pnl >= daily_target * 0.5:
            trading_mode = "NORMAL"  # On track
            mode_multiplier = 1.0
        else:
            trading_mode = "AGGRESSIVE"  # Behind - seek opportunities
            mode_multiplier = 1.3  # Higher thresholds, let winners run

        recommendations = []
        actions_taken = []

        # Fetch all data in parallel (MUCH faster)
        position_symbols = [p['symbol'] for p in positions]
        data_cache = fetch_all_data_parallel(position_symbols)

        for pos in positions:
            symbol = pos['symbol']
            size = pos['size']
            entry = pos['entry_price']
            pnl_pct = pos['pnl_percent']
            is_long = pos['is_long']
            pos_value = abs(size) * entry
            pnl_usd = pos_value * (pnl_pct / 100)

            try:
                # === MULTI-TIMEFRAME ANALYSIS ===
                # Use pre-fetched parallel data
                df_1h = data_cache.get((symbol, '1h'))
                df_4h = data_cache.get((symbol, '4h'))
                df_1d = data_cache.get((symbol, '1d'))

                if df_1h is None or df_1h.empty:
                    continue

                # Get signals from each timeframe
                signal_1h = get_timeframe_signal(df_1h)
                signal_4h = get_timeframe_signal(df_4h)
                signal_1d = get_timeframe_signal(df_1d)

                # Count bullish/bearish confluence
                trends = [signal_1h['trend'], signal_4h['trend'], signal_1d['trend']]
                bullish_count = trends.count('BULLISH')
                bearish_count = trends.count('BEARISH')

                # Timeframe confluence score
                if bullish_count == 3:
                    tf_confluence = "STRONG_BULL"
                    tf_score = 20
                elif bullish_count == 2:
                    tf_confluence = "BULL"
                    tf_score = 10
                elif bearish_count == 3:
                    tf_confluence = "STRONG_BEAR"
                    tf_score = -20
                elif bearish_count == 2:
                    tf_confluence = "BEAR"
                    tf_score = -10
                else:
                    tf_confluence = "MIXED"
                    tf_score = 0

                # === FUNDING RATE ANALYSIS ===
                funding_data = get_funding_rates(symbol)
                funding_rate = 0
                funding_signal = "NEUTRAL"
                funding_score = 0

                if funding_data:
                    funding_rate = funding_data['funding_rate'] * 100  # Convert to %
                    # Annualized rate
                    annual_rate = funding_rate * 24 * 365

                    if annual_rate > 50:  # Very high positive funding
                        funding_signal = "LONGS_CROWDED"
                        funding_score = -15 if is_long else 10
                    elif annual_rate > 20:  # High positive
                        funding_signal = "LONGS_PAYING"
                        funding_score = -5 if is_long else 5
                    elif annual_rate < -50:  # Very negative
                        funding_signal = "SHORTS_CROWDED"
                        funding_score = 10 if is_long else -15
                    elif annual_rate < -20:  # Negative
                        funding_signal = "SHORTS_PAYING"
                        funding_score = 5 if is_long else -5
                    else:
                        funding_signal = "NEUTRAL"
                        funding_score = 0

                # === FIBONACCI LEVELS ===
                fib_levels = calculate_fibonacci_levels(df_1h)
                fib_signal = "NEUTRAL"
                fib_score = 0
                current_price = df_1h.iloc[-1]['close']

                if fib_levels:
                    # Check where current price is relative to Fib levels
                    if current_price >= fib_levels['swing_high'] * 0.98:
                        fib_signal = "AT_RESISTANCE"
                        fib_score = -10 if is_long else 5
                    elif current_price <= fib_levels['swing_low'] * 1.02:
                        fib_signal = "AT_SUPPORT"
                        fib_score = 5 if is_long else -10
                    elif abs(current_price - fib_levels['fib_618']) / current_price < 0.02:
                        fib_signal = "AT_FIB_618"
                        fib_score = 5  # Key level
                    elif abs(current_price - fib_levels['fib_382']) / current_price < 0.02:
                        fib_signal = "AT_FIB_382"
                        fib_score = 3

                # === CORE INDICATORS ===
                latest = df_1h.iloc[-1]
                rsi = signal_1h['rsi']
                adx = signal_1h['adx']
                regime = latest.get('market_regime', 'UNKNOWN')

                # === GENERATE RECOMMENDATION (GOAL-BASED) ===
                action = "HOLD"
                reasons = []
                base_confidence = 50

                # Calculate composite score
                composite_score = tf_score + funding_score + fib_score

                # Adjust thresholds based on trading mode
                # AGGRESSIVE: higher thresholds (let winners run)
                # PROTECTIVE: lower thresholds (secure profits sooner)
                tp_threshold_25 = 25 * mode_multiplier
                tp_threshold_18 = 18 * mode_multiplier
                tp_threshold_15 = 15 * mode_multiplier
                tp_threshold_12 = 12 * mode_multiplier
                sl_threshold = -8 * (2 - mode_multiplier)  # Tighter stops in protective mode

                # Calculate this position's contribution to daily goal
                goal_contribution = (pnl_usd / daily_target * 100) if daily_target > 0 else 0

                # === GOAL-BASED PROFIT TAKING ===
                # If this single position would hit daily goal, take it!
                if pnl_usd >= distance_to_target and distance_to_target > 0 and pnl_pct > 5:
                    action = "TAKE_PROFIT_100"
                    reasons.append(f"🎯 +${pnl_usd:.0f} hits daily ${daily_target} goal!")
                    base_confidence = 95

                # If position is >50% of daily target, secure some
                elif pnl_usd >= daily_target * 0.5 and pnl_pct > 8:
                    action = "TAKE_PROFIT_50"
                    reasons.append(f"💰 +${pnl_usd:.0f} = {goal_contribution:.0f}% of daily goal")
                    base_confidence = 85

                # Standard P&L rules (adjusted by mode)
                elif pnl_pct >= tp_threshold_25:
                    action = "TAKE_PROFIT_50"
                    reasons.append(f"+{pnl_pct:.1f}% - secure gains [{trading_mode}]")
                    base_confidence = 85
                elif pnl_pct >= tp_threshold_18 and (rsi > 70 or tf_confluence in ["BEAR", "STRONG_BEAR"]):
                    action = "TAKE_PROFIT_50"
                    reasons.append(f"+{pnl_pct:.1f}% + overbought [{trading_mode}]")
                    base_confidence = 80
                elif pnl_pct >= tp_threshold_15 and funding_signal == "LONGS_CROWDED" and is_long:
                    action = "TAKE_PROFIT_50"
                    reasons.append(f"+{pnl_pct:.1f}% + crowded longs")
                    base_confidence = 78
                elif pnl_pct >= tp_threshold_12 and rsi > 75 and fib_signal == "AT_RESISTANCE":
                    action = "TAKE_PROFIT_25"
                    reasons.append(f"RSI {rsi:.0f} + resistance [{trading_mode}]")
                    base_confidence = 72

                # Loss cutting rules (tighter in protective mode)
                elif pnl_pct <= sl_threshold:
                    action = "CLOSE"
                    reasons.append(f"{pnl_pct:.1f}% - cut losses [{trading_mode}]")
                    base_confidence = 88
                elif pnl_pct <= -5 and tf_confluence in ["BEAR", "STRONG_BEAR"] and is_long:
                    action = "CLOSE"
                    reasons.append(f"{pnl_pct:.1f}% + bearish confluence")
                    base_confidence = 75
                elif pnl_pct <= -5 and rsi < 25:
                    action = "HOLD"  # Oversold, might bounce
                    reasons.append(f"Oversold RSI {rsi:.0f} - potential bounce")
                    base_confidence = 55
                elif pnl_pct <= -6:
                    action = "CLOSE"
                    reasons.append(f"{pnl_pct:.1f}% - minimize damage")
                    base_confidence = 72

                # Near max daily loss - close everything in red
                elif trading_mode == "PROTECTIVE" and effective_daily_pnl < 0 and pnl_pct < 0:
                    action = "CLOSE"
                    reasons.append(f"⚠️ Near daily loss limit - protect capital")
                    base_confidence = 80

                # Trend following with confluence
                elif tf_confluence == "STRONG_BULL" and is_long and pnl_pct > 0:
                    if trading_mode == "AGGRESSIVE":
                        action = "HOLD"
                        reasons.append(f"🚀 Strong bull - let it run [{trading_mode}]")
                        base_confidence = 75
                    else:
                        action = "HOLD"
                        reasons.append(f"Strong bullish confluence (3/3 TFs)")
                        base_confidence = 70
                elif tf_confluence == "STRONG_BEAR" and not is_long and pnl_pct > 0:
                    action = "HOLD"
                    reasons.append(f"Strong bearish confluence (3/3 TFs)")
                    base_confidence = 70
                elif tf_confluence == "STRONG_BEAR" and is_long and pnl_pct > 5:
                    action = "TAKE_PROFIT_50"
                    reasons.append(f"Bearish confluence - secure {pnl_pct:.1f}%")
                    base_confidence = 68

                # Funding rate warnings
                elif funding_signal == "LONGS_CROWDED" and is_long and pnl_pct > 8:
                    action = "TAKE_PROFIT_25"
                    reasons.append(f"Crowded longs - trim some")
                    base_confidence = 65

                # Default
                else:
                    action = "HOLD"
                    if tf_confluence in ["BULL", "STRONG_BULL"] and is_long:
                        reasons.append(f"Trend intact ({tf_confluence})")
                    elif tf_confluence in ["BEAR", "STRONG_BEAR"] and not is_long:
                        reasons.append(f"Trend intact ({tf_confluence})")
                    else:
                        reasons.append("No strong signal")
                    base_confidence = 50 + max(-10, min(10, composite_score))

                # Build detailed recommendation
                rec = {
                    "symbol": symbol,
                    "action": action,
                    "reason": " | ".join(reasons),
                    "confidence": min(95, max(30, base_confidence)),
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_usd": round(pnl_usd, 2),
                    "pos_value": round(pos_value, 2),
                    # Technical data
                    "rsi_1h": round(signal_1h['rsi'], 1),
                    "rsi_4h": round(signal_4h['rsi'], 1) if signal_4h['rsi'] else None,
                    "adx": round(adx, 1) if adx else None,
                    "regime": regime,
                    # Multi-timeframe
                    "tf_1h": signal_1h['trend'],
                    "tf_4h": signal_4h['trend'],
                    "tf_1d": signal_1d['trend'],
                    "tf_confluence": tf_confluence,
                    # Funding
                    "funding_rate": round(funding_rate, 4) if funding_rate else None,
                    "funding_signal": funding_signal,
                    # Fibonacci
                    "fib_signal": fib_signal,
                    "fib_levels": {
                        "resistance": round(fib_levels['swing_high'], 2) if fib_levels else None,
                        "support": round(fib_levels['swing_low'], 2) if fib_levels else None,
                        "fib_618": round(fib_levels['fib_618'], 2) if fib_levels else None,
                    } if fib_levels else None
                }
                recommendations.append(rec)

                # === EXECUTE IF REQUESTED ===
                if execute and action != "HOLD" and rec['confidence'] >= 70:
                    try:
                        exchange = Exchange(account, constants.MAINNET_API_URL)
                        abs_size = abs(float(size))

                        if action == "CLOSE":
                            ask, bid, _ = ask_bid(symbol)
                            close_price = bid * 0.999 if is_long else ask * 1.001
                            sz_dec, px_dec = get_sz_px_decimals(symbol)
                            close_price = round(close_price, px_dec) if px_dec > 0 else round(close_price)
                            result = exchange.order(symbol, not is_long, abs_size, close_price,
                                                   {'limit': {'tif': 'Ioc'}}, reduce_only=True)
                            actions_taken.append(f"CLOSED {symbol}")

                        elif action == "TAKE_PROFIT_50":
                            half_size = round(abs_size / 2, get_sz_px_decimals(symbol)[0])
                            ask, bid, _ = ask_bid(symbol)
                            close_price = bid * 0.999 if is_long else ask * 1.001
                            sz_dec, px_dec = get_sz_px_decimals(symbol)
                            close_price = round(close_price, px_dec) if px_dec > 0 else round(close_price)
                            result = exchange.order(symbol, not is_long, half_size, close_price,
                                                   {'limit': {'tif': 'Ioc'}}, reduce_only=True)
                            actions_taken.append(f"TRIMMED 50% {symbol}")

                        elif action == "TAKE_PROFIT_25":
                            quarter_size = round(abs_size / 4, get_sz_px_decimals(symbol)[0])
                            ask, bid, _ = ask_bid(symbol)
                            close_price = bid * 0.999 if is_long else ask * 1.001
                            sz_dec, px_dec = get_sz_px_decimals(symbol)
                            close_price = round(close_price, px_dec) if px_dec > 0 else round(close_price)
                            result = exchange.order(symbol, not is_long, quarter_size, close_price,
                                                   {'limit': {'tif': 'Ioc'}}, reduce_only=True)
                            actions_taken.append(f"TRIMMED 25% {symbol}")

                    except Exception as ex:
                        actions_taken.append(f"FAILED {symbol}: {str(ex)}")

            except Exception as e:
                recommendations.append({
                    "symbol": symbol,
                    "action": "ERROR",
                    "reason": str(e),
                    "confidence": 0,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_usd": round(pnl_usd, 2)
                })

        return {
            "timestamp": datetime.now().isoformat(),
            "account_value": round(acct_value, 2),
            "free_margin": round(free_margin, 2),
            "recommendations": recommendations,
            "executed": execute,
            "actions_taken": actions_taken,
            "analysis_version": "3.0-goal-based",
            # Goal progress data
            "goals": {
                "daily_target": daily_target,
                "max_daily_loss": max_daily_loss,
                "ultimate_target": ultimate_target,
                "daily_pnl_realized": round(daily_pnl, 2),
                "daily_pnl_unrealized": round(total_unrealized, 2),
                "daily_pnl_effective": round(effective_daily_pnl, 2),
                "distance_to_daily": round(distance_to_target, 2),
                "daily_progress_pct": round(target_progress_pct, 1),
                "mission_progress_pct": round(mission_progress_pct, 4),
                "distance_to_million": round(distance_to_million, 2),
                "trading_mode": trading_mode,
                "mode_multiplier": mode_multiplier
            }
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


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

    # Pre-initialize HyperLiquid connection for fast trading
    print("⚡ Pre-initializing HyperLiquid connection...")
    try:
        info, exchange, account = get_hl_connection()
        if exchange:
            print("✅ HyperLiquid connection ready (fast trades enabled)")
        else:
            print("⚠️ HyperLiquid connection not configured")
    except Exception as e:
        print(f"⚠️ HyperLiquid init warning: {e}")

    # Auto-start log scanner
    start_log_scanner()

    print("Press Ctrl+C to stop\n")

    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="warning")
