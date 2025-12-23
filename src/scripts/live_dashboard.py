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
            return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None}

        with open(PL_HISTORY_FILE, 'r') as f:
            history = json.load(f)

        if len(history) < 2:
            return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None}

        now = datetime.now()
        current_value = history[-1]["value"]

        # Find value from 24h ago
        value_24h = None
        value_7d = None

        for entry in reversed(history):
            entry_time = datetime.fromisoformat(entry["timestamp"])
            age_hours = (now - entry_time).total_seconds() / 3600

            if value_24h is None and age_hours >= 24:
                value_24h = entry["value"]
            if value_7d is None and age_hours >= 168:  # 7 days
                value_7d = entry["value"]
                break

        result = {
            "pnl_24h": None,
            "pnl_7d": None,
            "pnl_24h_pct": None,
            "pnl_7d_pct": None
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
        return {"pnl_24h": None, "pnl_7d": None, "pnl_24h_pct": None, "pnl_7d_pct": None}

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
        withdrawable = float(margin_summary.get("withdrawable", 0))

        # Calculate total unrealized P/L from positions
        total_unrealized_pnl = 0
        positions = []
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            size = float(position.get("szi", 0))
            if size != 0:
                unrealized = float(position.get("unrealizedPnl", 0))
                total_unrealized_pnl += unrealized
                positions.append({
                    "symbol": position.get("coin", ""),
                    "size": size,
                    "entry_price": float(position.get("entryPx", 0)),
                    "pnl_percent": float(position.get("returnOnEquity", 0)) * 100,
                    "unrealized_pnl": unrealized,
                    "side": "LONG" if size > 0 else "SHORT",
                    "leverage": position.get("leverage", {}).get("value", "-")
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
            "unrealized_pnl": total_unrealized_pnl,
            "withdrawable": withdrawable,
            "positions": positions,
            "address": account.address[:10] + "..." + account.address[-6:],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pnl_24h": pl_stats.get("pnl_24h"),
            "pnl_24h_pct": pl_stats.get("pnl_24h_pct"),
            "pnl_7d": pl_stats.get("pnl_7d"),
            "pnl_7d_pct": pl_stats.get("pnl_7d_pct")
        }
    except Exception as e:
        return {"error": str(e)}

def get_recent_logs(lines=50):
    """Get recent log entries"""
    try:
        if not os.path.exists(LOG_FILE):
            return ["No log file found. Is the bot running?"]

        with open(LOG_FILE, 'r') as f:
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
    """Parse analysis reports from log file"""
    reports = {}
    try:
        logs = get_recent_logs(500)
        log_text = ''.join(logs)

        # Match the actual log format: 🎯 Token: BTC followed by 🤖 Swarm Signal: ACTION (XX% confidence)
        pattern = r'🎯 Token: (\w+)\n🤖 (?:Swarm |AI )?Signal: (BUY|SELL|NOTHING|DO NOTHING) \((\d+)% confidence\)'
        matches = re.findall(pattern, log_text)

        for symbol, action, confidence in matches:
            # Normalize action
            action = action.replace("DO NOTHING", "NOTHING")
            reports[symbol] = {
                "action": action,
                "confidence": int(confidence),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    except Exception as e:
        print(f"Error parsing reports: {e}")

    return reports

def get_bot_status():
    """Check if bot is running"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*main.py"],
            capture_output=True,
            text=True
        )
        return "RUNNING" if result.returncode == 0 else "STOPPED"
    except:
        return "UNKNOWN"

# HTML Dashboard Template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CryptoVerge Terminal</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Orbitron:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        :root {
            --bg-primary: #05050a;
            --bg-secondary: #0a0a12;
            --bg-card: #0d0d18;
            --bg-card-hover: #12121f;
            --border-color: #1a1a2e;
            --border-glow: #00f5ff15;
            --text-primary: #e8e8ed;
            --text-secondary: #6b6b7b;
            --text-muted: #404050;
            --accent-cyan: #00f5ff;
            --accent-cyan-dim: #00f5ff40;
            --accent-purple: #a855f7;
            --profit: #00ff88;
            --profit-dim: #00ff8830;
            --loss: #ff3366;
            --loss-dim: #ff336630;
            --warning: #ffaa00;
            --warning-dim: #ffaa0030;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'JetBrains Mono', monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* Subtle scanline effect */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px);
            pointer-events: none;
            z-index: 9999;
        }

        .dashboard {
            display: grid;
            grid-template-columns: 300px 1fr 340px;
            grid-template-rows: auto 1fr;
            min-height: 100vh;
            gap: 1px;
            background: var(--border-color);
        }

        /* ===== HEADER ===== */
        .header {
            grid-column: 1 / -1;
            background: var(--bg-secondary);
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-color);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .logo-icon {
            width: 40px; height: 40px;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Orbitron', sans-serif;
            font-weight: 900;
            font-size: 16px;
            color: var(--bg-primary);
            box-shadow: 0 0 25px var(--accent-cyan-dim);
        }

        .logo-text h1 {
            font-family: 'Orbitron', sans-serif;
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 3px;
            background: linear-gradient(90deg, var(--accent-cyan), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .logo-text span {
            font-size: 9px;
            color: var(--text-muted);
            letter-spacing: 4px;
            text-transform: uppercase;
        }

        .header-center {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 6px;
        }

        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
        }

        .status-dot.running {
            background: var(--profit);
            box-shadow: 0 0 8px var(--profit);
            animation: pulse 2s infinite;
        }

        .status-dot.stopped {
            background: var(--loss);
            box-shadow: 0 0 8px var(--loss);
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .status-label {
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        .header-controls {
            display: flex;
            gap: 6px;
        }

        .btn {
            padding: 8px 14px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            background: var(--bg-card);
            color: var(--text-primary);
            font-family: inherit;
            font-size: 11px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .btn:hover {
            background: var(--bg-card-hover);
            border-color: var(--accent-cyan-dim);
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
            border: none;
            color: var(--bg-primary);
            font-weight: 700;
        }

        .btn-primary:hover {
            box-shadow: 0 0 20px var(--accent-cyan-dim);
        }

        .btn-success {
            border-color: var(--profit-dim);
            color: var(--profit);
        }

        .btn-success:hover {
            background: var(--profit-dim);
        }

        .btn-danger {
            border-color: var(--loss-dim);
            color: var(--loss);
        }

        .btn-danger:hover {
            background: var(--loss-dim);
        }

        .header-time {
            font-size: 11px;
            color: var(--text-secondary);
            font-variant-numeric: tabular-nums;
        }

        /* ===== LEFT SIDEBAR ===== */
        .sidebar-left {
            background: var(--bg-secondary);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }

        .panel {
            padding: 16px;
            border-bottom: 1px solid var(--border-color);
        }

        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }

        .panel-title {
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-secondary);
        }

        .panel-badge {
            font-size: 9px;
            padding: 2px 6px;
            background: var(--accent-cyan-dim);
            color: var(--accent-cyan);
            border-radius: 3px;
            font-weight: 600;
        }

        /* Account Stats */
        .stat-grid {
            display: grid;
            gap: 8px;
        }

        .stat-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            background: var(--bg-card);
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }

        .stat-label {
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 14px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }

        .stat-value.positive { color: var(--profit); }
        .stat-value.negative { color: var(--loss); }

        .stat-large {
            flex-direction: column;
            align-items: flex-start;
            gap: 4px;
        }

        .stat-large .stat-value {
            font-size: 22px;
            font-weight: 700;
        }

        /* P/L Cards */
        .pnl-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-top: 8px;
        }

        .pnl-card {
            padding: 10px;
            background: var(--bg-card);
            border-radius: 6px;
            border: 1px solid var(--border-color);
            text-align: center;
        }

        .pnl-label {
            font-size: 9px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 4px;
        }

        .pnl-value {
            font-size: 13px;
            font-weight: 600;
        }

        /* Token Watchlist */
        .token-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .token-item {
            display: grid;
            grid-template-columns: 20px 1fr auto;
            align-items: center;
            gap: 8px;
            padding: 10px 12px;
            background: var(--bg-card);
            border-radius: 6px;
            border: 1px solid var(--border-color);
            transition: all 0.2s;
        }

        .token-item:hover {
            background: var(--bg-card-hover);
            border-color: var(--accent-cyan-dim);
        }

        .token-item.disabled {
            opacity: 0.5;
        }

        .token-item input[type="checkbox"] {
            width: 14px;
            height: 14px;
            accent-color: var(--accent-cyan);
            cursor: pointer;
        }

        .token-info {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .token-icon {
            width: 28px; height: 28px;
            border-radius: 50%;
            background: var(--bg-secondary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: 700;
            color: var(--accent-cyan);
            border: 1px solid var(--border-color);
        }

        .token-name {
            font-size: 12px;
            font-weight: 600;
        }

        .token-signal {
            font-size: 10px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .token-signal.buy {
            background: var(--profit-dim);
            color: var(--profit);
        }

        .token-signal.sell {
            background: var(--loss-dim);
            color: var(--loss);
        }

        .token-signal.nothing {
            background: var(--warning-dim);
            color: var(--warning);
        }

        .token-signal.pending {
            background: var(--bg-secondary);
            color: var(--text-muted);
        }

        .token-signal.disabled {
            background: var(--bg-primary);
            color: var(--text-muted);
            font-style: italic;
        }

        .token-meta {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .token-confidence {
            font-size: 11px;
            font-weight: 600;
            color: var(--accent-cyan);
            font-variant-numeric: tabular-nums;
        }

        /* ===== MAIN CONTENT ===== */
        .main-content {
            background: var(--bg-primary);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Positions Panel */
        /* Equity Chart */
        .chart-panel {
            padding: 16px;
            border-bottom: 1px solid var(--border-color);
            background: var(--bg-secondary);
        }

        .chart-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .chart-timeframes {
            display: flex;
            gap: 4px;
        }

        .timeframe-btn {
            padding: 4px 10px;
            font-size: 10px;
            font-weight: 600;
            font-family: inherit;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s;
        }

        .timeframe-btn:hover {
            border-color: var(--accent-cyan-dim);
            color: var(--text-primary);
        }

        .timeframe-btn.active {
            background: var(--accent-cyan);
            border-color: var(--accent-cyan);
            color: var(--bg-primary);
        }

        .chart-container {
            position: relative;
            height: 200px;
            background: var(--bg-card);
            border-radius: 8px;
            padding: 12px;
            border: 1px solid var(--border-color);
        }

        .positions-panel {
            padding: 16px;
            border-bottom: 1px solid var(--border-color);
            background: var(--bg-secondary);
        }

        .positions-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 12px;
        }

        .position-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px;
            position: relative;
            overflow: hidden;
        }

        .position-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 3px; height: 100%;
        }

        .position-card.long::before { background: var(--profit); }
        .position-card.short::before { background: var(--loss); }

        .position-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .position-symbol {
            font-size: 14px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .position-side {
            font-size: 9px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            text-transform: uppercase;
        }

        .position-side.long {
            background: var(--profit-dim);
            color: var(--profit);
        }

        .position-side.short {
            background: var(--loss-dim);
            color: var(--loss);
        }

        .position-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 12px;
        }

        .position-stat {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .position-stat-label {
            font-size: 9px;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .position-stat-value {
            font-size: 12px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }

        .position-pnl {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 10px;
            border-top: 1px solid var(--border-color);
        }

        .position-pnl-value {
            font-size: 16px;
            font-weight: 700;
        }

        .position-pnl-value.positive { color: var(--profit); }
        .position-pnl-value.negative { color: var(--loss); }

        .btn-close-position {
            padding: 6px 12px;
            font-size: 10px;
        }

        .no-positions {
            text-align: center;
            padding: 30px;
            color: var(--text-muted);
            font-size: 12px;
        }

        /* Logs Panel */
        .logs-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            background: var(--bg-secondary);
        }

        .logs-header {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logs-content {
            flex: 1;
            overflow-y: auto;
            padding: 12px 16px;
            font-size: 11px;
            line-height: 1.6;
            color: var(--text-secondary);
            background: var(--bg-card);
            margin: 8px;
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }

        .logs-content pre {
            white-space: pre-wrap;
            word-break: break-all;
        }

        /* ===== RIGHT SIDEBAR ===== */
        .sidebar-right {
            background: var(--bg-secondary);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }

        /* Settings */
        .settings-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .setting-item {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .setting-item.full-width {
            grid-column: 1 / -1;
        }

        .setting-label {
            font-size: 9px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .setting-input {
            padding: 8px 10px;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 5px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 12px;
            transition: all 0.2s;
        }

        .setting-input:focus {
            outline: none;
            border-color: var(--accent-cyan);
            box-shadow: 0 0 0 2px var(--accent-cyan-dim);
        }

        /* Indicators */
        .indicators-grid {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .indicator-item {
            display: grid;
            grid-template-columns: 18px 24px 1fr;
            grid-template-rows: auto auto;
            gap: 2px 8px;
            padding: 10px 12px;
            background: var(--bg-card);
            border-radius: 6px;
            border: 1px solid var(--border-color);
            cursor: pointer;
            transition: all 0.2s;
        }

        .indicator-item:hover {
            background: var(--bg-card-hover);
            border-color: var(--accent-cyan-dim);
        }

        .indicator-item input {
            grid-row: span 2;
            width: 14px; height: 14px;
            accent-color: var(--accent-cyan);
            cursor: pointer;
            align-self: center;
        }

        .indicator-impact {
            grid-row: span 2;
            font-size: 9px;
            font-weight: 700;
            padding: 3px 6px;
            border-radius: 3px;
            align-self: center;
            text-align: center;
        }

        .indicator-impact.high {
            background: var(--loss-dim);
            color: var(--loss);
        }

        .indicator-impact.medium {
            background: var(--warning-dim);
            color: var(--warning);
        }

        .indicator-impact.low {
            background: var(--profit-dim);
            color: var(--profit);
        }

        .indicator-name {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-primary);
        }

        .indicator-desc {
            font-size: 10px;
            color: var(--text-secondary);
            line-height: 1.3;
        }

        .impact-legend {
            display: flex;
            gap: 12px;
            margin-bottom: 10px;
            font-size: 9px;
        }

        .impact-legend span {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        /* Command Status */
        .command-status {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 10px 20px;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            font-size: 11px;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s;
        }

        .command-status.visible {
            opacity: 1;
        }

        .command-status.success {
            border-color: var(--profit);
            color: var(--profit);
        }

        .command-status.error {
            border-color: var(--loss);
            color: var(--loss);
        }

        /* Backtest Results */
        .backtest-results {
            display: grid;
            gap: 16px;
        }

        .backtest-section {
            background: var(--bg-card);
            border-radius: 8px;
            padding: 16px;
            border: 1px solid var(--border-color);
        }

        .backtest-section h3 {
            font-size: 11px;
            font-weight: 600;
            color: var(--accent-cyan);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
        }

        .backtest-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .backtest-stat {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
        }

        .backtest-stat-label {
            font-size: 11px;
            color: var(--text-secondary);
        }

        .backtest-stat-value {
            font-size: 12px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }

        .backtest-stat-value.positive { color: var(--profit); }
        .backtest-stat-value.negative { color: var(--loss); }

        .backtest-big-stat {
            text-align: center;
            padding: 16px;
            background: var(--bg-secondary);
            border-radius: 6px;
        }

        .backtest-big-value {
            font-size: 24px;
            font-weight: 700;
            font-family: 'Orbitron', sans-serif;
        }

        .backtest-big-label {
            font-size: 10px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 4px;
        }

        .backtest-reasons {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .backtest-reason {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            background: var(--bg-secondary);
            border-radius: 4px;
            font-size: 11px;
        }

        .backtest-reason-count {
            font-weight: 700;
            color: var(--accent-cyan);
        }

        .backtest-loading {
            text-align: center;
            padding: 40px;
            color: var(--text-secondary);
        }

        .backtest-loading .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--border-color);
            border-top: 3px solid var(--accent-cyan);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* Modal */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            backdrop-filter: blur(4px);
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            width: 90%;
            max-width: 600px;
            max-height: 80vh;
            overflow: hidden;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }

        .modal-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 14px;
            font-weight: 600;
            color: var(--accent-cyan);
        }

        .modal-close {
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 20px;
            cursor: pointer;
            padding: 4px;
        }

        .modal-close:hover {
            color: var(--text-primary);
        }

        .modal-body {
            padding: 20px;
            max-height: 60vh;
            overflow-y: auto;
            font-size: 12px;
            line-height: 1.7;
            white-space: pre-wrap;
            color: var(--text-secondary);
        }

        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }

        ::-webkit-scrollbar-track {
            background: var(--bg-primary);
        }

        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 3px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-muted);
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <!-- Header -->
        <header class="header">
            <div class="logo">
                <div class="logo-icon">CV</div>
                <div class="logo-text">
                    <h1>CryptoVerge</h1>
                    <span>HyperLiquid Terminal</span>
                </div>
            </div>

            <div class="header-center">
                <div class="status-badge">
                    <div class="status-dot stopped" id="status-dot"></div>
                    <span class="status-label" id="status-text">Offline</span>
                </div>
                <div class="header-controls">
                    <button class="btn btn-success" onclick="sendCommand('start')">Start</button>
                    <button class="btn btn-danger" onclick="sendCommand('stop')">Stop</button>
                    <button class="btn" onclick="sendCommand('restart')">Restart</button>
                    <button class="btn btn-primary" onclick="sendCommand('run-analysis')">Analyze</button>
                    <button class="btn" onclick="runBacktest()" style="border-color: var(--accent-purple); color: var(--accent-purple);">Backtest</button>
                </div>
            </div>

            <div class="header-time" id="current-time">--:--:--</div>
        </header>

        <!-- Left Sidebar -->
        <aside class="sidebar-left">
            <!-- Account Panel -->
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">Account</span>
                    <span class="panel-badge">Live</span>
                </div>
                <div class="stat-grid">
                    <div class="stat-item stat-large">
                        <span class="stat-label">Equity</span>
                        <span class="stat-value" id="equity">$0.00</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Balance</span>
                        <span class="stat-value" id="balance">$0.00</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Unrealized P/L</span>
                        <span class="stat-value" id="unrealized-pnl">$0.00</span>
                    </div>
                </div>
                <div class="pnl-row">
                    <div class="pnl-card">
                        <div class="pnl-label">24h P/L</div>
                        <div class="pnl-value" id="pnl-24h">--</div>
                    </div>
                    <div class="pnl-card">
                        <div class="pnl-label">7d P/L</div>
                        <div class="pnl-value" id="pnl-7d">--</div>
                    </div>
                </div>
            </div>

            <!-- Watchlist Panel -->
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">Watchlist</span>
                </div>
                <div class="token-list" id="token-list">
                    <div class="token-item">
                        <div class="token-info">
                            <div class="token-icon">BTC</div>
                            <span class="token-name">Bitcoin</span>
                        </div>
                        <span class="token-signal pending">Pending</span>
                    </div>
                </div>
            </div>
        </aside>

        <!-- Main Content -->
        <main class="main-content">
            <!-- Equity Chart -->
            <div class="chart-panel">
                <div class="chart-header">
                    <span class="panel-title">Equity Curve</span>
                    <div class="chart-timeframes">
                        <button class="timeframe-btn" data-hours="1" onclick="setChartTimeframe(1)">1H</button>
                        <button class="timeframe-btn" data-hours="24" onclick="setChartTimeframe(24)">1D</button>
                        <button class="timeframe-btn active" data-hours="168" onclick="setChartTimeframe(168)">7D</button>
                        <button class="timeframe-btn" data-hours="720" onclick="setChartTimeframe(720)">1M</button>
                        <button class="timeframe-btn" data-hours="8760" onclick="setChartTimeframe(8760)">1Y</button>
                    </div>
                </div>
                <div class="chart-container">
                    <canvas id="equity-chart"></canvas>
                </div>
            </div>

            <!-- Positions -->
            <div class="positions-panel">
                <div class="panel-header">
                    <span class="panel-title">Open Positions</span>
                    <button class="btn" onclick="setAllTpSl()">Set All TP/SL</button>
                </div>
                <div class="positions-grid" id="positions-container">
                    <div class="no-positions">No open positions</div>
                </div>
            </div>

            <!-- Logs -->
            <div class="logs-panel">
                <div class="logs-header">
                    <span class="panel-title">System Logs</span>
                    <button class="btn" onclick="sendCommand('clear-logs')">Clear</button>
                </div>
                <div class="logs-content">
                    <pre id="log-content">Waiting for logs...</pre>
                </div>
            </div>
        </main>

        <!-- Right Sidebar -->
        <aside class="sidebar-right">
            <!-- Settings Panel -->
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">Trading Settings</span>
                </div>
                <div class="settings-grid">
                    <div class="setting-item">
                        <label class="setting-label">Leverage</label>
                        <input type="number" class="setting-input" id="setting-leverage" value="5">
                    </div>
                    <div class="setting-item">
                        <label class="setting-label">Position %</label>
                        <input type="number" class="setting-input" id="setting-max_position_pct" value="25">
                    </div>
                    <div class="setting-item">
                        <label class="setting-label">Stop Loss %</label>
                        <input type="number" class="setting-input" id="setting-stop_loss" value="3">
                    </div>
                    <div class="setting-item">
                        <label class="setting-label">Take Profit %</label>
                        <input type="number" class="setting-input" id="setting-take_profit" value="5">
                    </div>
                    <div class="setting-item full-width">
                        <label class="setting-label">Cycle (minutes)</label>
                        <input type="number" class="setting-input" id="setting-sleep_minutes" value="15">
                    </div>
                </div>
                <button class="btn btn-primary" style="width:100%;margin-top:12px;" onclick="saveSettings()">Save Settings</button>
            </div>

            <!-- Indicators Panel -->
            <div class="panel" style="flex:1;overflow-y:auto;">
                <div class="panel-header">
                    <span class="panel-title">AI Indicators</span>
                </div>
                <div class="impact-legend">
                    <span><span class="indicator-impact high">H</span> High</span>
                    <span><span class="indicator-impact medium">M</span> Medium</span>
                    <span><span class="indicator-impact low">L</span> Low</span>
                </div>
                <div class="indicators-grid" id="indicators-container">
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-rsi" onchange="toggleIndicator('rsi', this.checked)">
                        <span class="indicator-impact high">H</span>
                        <span class="indicator-name">RSI (14)</span>
                        <span class="indicator-desc">Momentum 0-100. Above 70 = overbought, below 30 = oversold</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-sma_200" onchange="toggleIndicator('sma_200', this.checked)">
                        <span class="indicator-impact high">H</span>
                        <span class="indicator-name">SMA 200</span>
                        <span class="indicator-desc">Long-term trend. Price above = bullish, below = bearish</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-macd" onchange="toggleIndicator('macd', this.checked)">
                        <span class="indicator-impact high">H</span>
                        <span class="indicator-name">MACD</span>
                        <span class="indicator-desc">Trend momentum & reversals. Signal line crossovers</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-bollinger" onchange="toggleIndicator('bollinger', this.checked)">
                        <span class="indicator-impact high">H</span>
                        <span class="indicator-name">Bollinger Bands</span>
                        <span class="indicator-desc">Volatility bands. Price at upper = overbought, lower = oversold</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-volume" onchange="toggleIndicator('volume', this.checked)">
                        <span class="indicator-impact high">H</span>
                        <span class="indicator-name">Volume</span>
                        <span class="indicator-desc">Confirms price moves. High volume = strong signal validity</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-golden_cross" onchange="toggleIndicator('golden_cross', this.checked)">
                        <span class="indicator-impact high">H</span>
                        <span class="indicator-name">Golden Cross</span>
                        <span class="indicator-desc">MA20 crosses MA200. Golden = buy, Death Cross = sell</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-sma_20" onchange="toggleIndicator('sma_20', this.checked)">
                        <span class="indicator-impact medium">M</span>
                        <span class="indicator-name">SMA 20</span>
                        <span class="indicator-desc">Short-term trend direction. Dynamic support/resistance</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-sma_50" onchange="toggleIndicator('sma_50', this.checked)">
                        <span class="indicator-impact medium">M</span>
                        <span class="indicator-name">SMA 50</span>
                        <span class="indicator-desc">Medium-term trend. Institutional traders watch this level</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-atr" onchange="toggleIndicator('atr', this.checked)">
                        <span class="indicator-impact medium">M</span>
                        <span class="indicator-name">ATR (14)</span>
                        <span class="indicator-desc">Average True Range. Used for stop-loss & position sizing</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-adx" onchange="toggleIndicator('adx', this.checked)">
                        <span class="indicator-impact medium">M</span>
                        <span class="indicator-name">ADX</span>
                        <span class="indicator-desc">Trend strength 0-100. Above 25 = trending, below = ranging</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-fibonacci" onchange="toggleIndicator('fibonacci', this.checked)">
                        <span class="indicator-impact medium">M</span>
                        <span class="indicator-name">Fibonacci</span>
                        <span class="indicator-desc">Key levels: 23.6%, 38.2%, 50%, 61.8%. Support & resistance</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-stochastic" onchange="toggleIndicator('stochastic', this.checked)">
                        <span class="indicator-impact low">L</span>
                        <span class="indicator-name">Stochastic</span>
                        <span class="indicator-desc">Similar to RSI. Above 80 = overbought, below 20 = oversold</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-cci" onchange="toggleIndicator('cci', this.checked)">
                        <span class="indicator-impact low">L</span>
                        <span class="indicator-name">CCI</span>
                        <span class="indicator-desc">Commodity Channel Index. Identifies cyclical price patterns</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-williams_r" onchange="toggleIndicator('williams_r', this.checked)">
                        <span class="indicator-impact low">L</span>
                        <span class="indicator-name">Williams %R</span>
                        <span class="indicator-desc">Momentum oscillator. -20 to 0 = overbought, -100 to -80 = oversold</span>
                    </label>
                    <label class="indicator-item">
                        <input type="checkbox" id="ind-obv" onchange="toggleIndicator('obv', this.checked)">
                        <span class="indicator-impact low">L</span>
                        <span class="indicator-name">OBV</span>
                        <span class="indicator-desc">On-Balance Volume. Rising OBV = accumulation, falling = distribution</span>
                    </label>
                </div>
            </div>
        </aside>
    </div>

    <!-- Modal -->
    <div class="modal-overlay" id="modal-overlay" onclick="closeModal(event)">
        <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-header">
                <span class="modal-title" id="modal-title">Analysis Report</span>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>

    <!-- Command Status -->
    <div class="command-status" id="command-status"></div>

    <script>
        let currentSettings = {};
        let analysisReports = {};

        // Update time
        function updateTime() {
            const now = new Date();
            document.getElementById('current-time').textContent = now.toLocaleTimeString('en-US', { hour12: false });
        }
        setInterval(updateTime, 1000);
        updateTime();

        async function fetchData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();

                // Update status
                const isRunning = data.bot_status === 'RUNNING';
                const statusDot = document.getElementById('status-dot');
                const statusText = document.getElementById('status-text');

                statusDot.className = 'status-dot ' + (isRunning ? 'running' : 'stopped');
                statusText.textContent = isRunning ? 'Online' : 'Offline';

                // Update account
                if (data.account) {
                    document.getElementById('equity').textContent = '$' + (data.account.equity || 0).toFixed(2);
                    document.getElementById('balance').textContent = '$' + (data.account.balance || 0).toFixed(2);

                    const pnl = data.account.unrealized_pnl || 0;
                    const pnlEl = document.getElementById('unrealized-pnl');
                    pnlEl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
                    pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');

                    // 24h P/L
                    const pnl24h = data.account.pnl_24h;
                    const pnl24hEl = document.getElementById('pnl-24h');
                    if (pnl24h !== null && pnl24h !== undefined) {
                        const pct = data.account.pnl_24h_pct || 0;
                        pnl24hEl.textContent = (pnl24h >= 0 ? '+' : '') + '$' + pnl24h.toFixed(2) + ' (' + (pnl24h >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
                        pnl24hEl.style.color = pnl24h >= 0 ? 'var(--profit)' : 'var(--loss)';
                    } else {
                        pnl24hEl.textContent = 'Collecting...';
                        pnl24hEl.style.color = 'var(--text-muted)';
                    }

                    // 7d P/L
                    const pnl7d = data.account.pnl_7d;
                    const pnl7dEl = document.getElementById('pnl-7d');
                    if (pnl7d !== null && pnl7d !== undefined) {
                        const pct = data.account.pnl_7d_pct || 0;
                        pnl7dEl.textContent = (pnl7d >= 0 ? '+' : '') + '$' + pnl7d.toFixed(2) + ' (' + (pnl7d >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
                        pnl7dEl.style.color = pnl7d >= 0 ? 'var(--profit)' : 'var(--loss)';
                    } else {
                        pnl7dEl.textContent = 'Collecting...';
                        pnl7dEl.style.color = 'var(--text-muted)';
                    }

                    // Positions
                    const posContainer = document.getElementById('positions-container');
                    if (data.account.positions && data.account.positions.length > 0) {
                        posContainer.innerHTML = data.account.positions.map(pos => {
                            const isLong = pos.side.toLowerCase() === 'long';
                            const pnlClass = pos.pnl_percent >= 0 ? 'positive' : 'negative';
                            return `
                                <div class="position-card ${isLong ? 'long' : 'short'}">
                                    <div class="position-header">
                                        <span class="position-symbol">
                                            ${pos.symbol}
                                            <span class="position-side ${isLong ? 'long' : 'short'}">${pos.side}</span>
                                        </span>
                                    </div>
                                    <div class="position-stats">
                                        <div class="position-stat">
                                            <span class="position-stat-label">Entry</span>
                                            <span class="position-stat-value">$${pos.entry_price.toFixed(2)}</span>
                                        </div>
                                        <div class="position-stat">
                                            <span class="position-stat-label">Size</span>
                                            <span class="position-stat-value">${Math.abs(pos.size).toFixed(4)}</span>
                                        </div>
                                        <div class="position-stat">
                                            <span class="position-stat-label">Value</span>
                                            <span class="position-stat-value">$${(Math.abs(pos.size) * pos.entry_price).toFixed(2)}</span>
                                        </div>
                                        <div class="position-stat">
                                            <span class="position-stat-label">Leverage</span>
                                            <span class="position-stat-value">${pos.leverage || '-'}x</span>
                                        </div>
                                    </div>
                                    <div class="position-pnl">
                                        <span class="position-pnl-value ${pnlClass}">
                                            ${pos.pnl_percent >= 0 ? '+' : ''}${pos.pnl_percent.toFixed(2)}% ($${pos.unrealized_pnl.toFixed(2)})
                                        </span>
                                        <button class="btn btn-danger btn-close-position" onclick="closePosition('${pos.symbol}')">Close</button>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    } else {
                        posContainer.innerHTML = '<div class="no-positions">No open positions</div>';
                    }
                }

                // Update settings
                if (data.settings && !document.activeElement.className.includes('setting-input')) {
                    currentSettings = data.settings;
                    ['leverage', 'max_position_pct', 'stop_loss', 'take_profit', 'sleep_minutes'].forEach(key => {
                        const input = document.getElementById('setting-' + key);
                        if (input) input.value = data.settings[key] || '';
                    });
                }

                // Update watchlist with all symbols (enabled and disabled)
                if (data.settings && data.settings.all_symbols) {
                    analysisReports = data.analysis_reports || {};
                    const tokenList = document.getElementById('token-list');
                    const allSymbols = data.settings.all_symbols;
                    tokenList.innerHTML = Object.entries(allSymbols).map(([symbol, enabled]) => {
                        const report = analysisReports[symbol] || {};
                        const action = enabled ? (report.action || 'PENDING').toLowerCase() : 'disabled';
                        const confidence = report.confidence || '-';
                        return `
                            <div class="token-item ${enabled ? '' : 'disabled'}">
                                <input type="checkbox" ${enabled ? 'checked' : ''} onchange="toggleSymbol('${symbol}', this.checked)" onclick="event.stopPropagation()">
                                <div class="token-info" onclick="showAnalysis('${symbol}')" style="cursor:pointer;">
                                    <div class="token-icon">${symbol.substring(0, 3)}</div>
                                    <span class="token-name">${symbol}</span>
                                </div>
                                <div class="token-meta" onclick="showAnalysis('${symbol}')" style="cursor:pointer;">
                                    <span class="token-confidence">${enabled ? confidence + '%' : 'OFF'}</span>
                                    <span class="token-signal ${action}">${enabled ? (report.action || 'Pending') : 'Disabled'}</span>
                                </div>
                            </div>
                        `;
                    }).join('');
                }

                // Update logs
                document.getElementById('log-content').textContent = data.logs.join('');
                const logEl = document.querySelector('.logs-content');
                logEl.scrollTop = logEl.scrollHeight;

            } catch (error) {
                console.error('Fetch error:', error);
            }
        }

        async function sendCommand(command) {
            showStatus('Processing...', '');
            try {
                const response = await fetch('/api/' + command, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 1000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function saveSettings() {
            showStatus('Saving...', '');
            try {
                const settings = ['leverage', 'max_position_pct', 'stop_loss', 'take_profit', 'sleep_minutes'];
                for (const s of settings) {
                    const value = document.getElementById('setting-' + s).value;
                    await fetch('/api/setting/' + s + '/' + value, { method: 'POST' });
                }
                showStatus('Settings saved!', 'success');
                await fetch('/api/restart', { method: 'POST' });
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function toggleIndicator(name, enabled) {
            try {
                const response = await fetch('/api/indicator/' + name + '/' + enabled, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function toggleSymbol(symbol, enabled) {
            try {
                const response = await fetch('/api/symbol/' + symbol + '/' + enabled, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 500);  // Refresh to show updated state
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function loadIndicators() {
            try {
                const response = await fetch('/api/indicators');
                const data = await response.json();
                if (data.indicators) {
                    for (const [name, enabled] of Object.entries(data.indicators)) {
                        const checkbox = document.getElementById('ind-' + name);
                        if (checkbox) checkbox.checked = enabled;
                    }
                }
            } catch (error) {
                console.error('Error loading indicators:', error);
            }
        }

        async function closePosition(symbol) {
            if (!confirm('Close ' + symbol + ' position?')) return;
            showStatus('Closing ' + symbol + '...', '');
            try {
                const response = await fetch('/api/close-position/' + symbol, { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
                setTimeout(fetchData, 2000);
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        async function setAllTpSl() {
            showStatus('Setting TP/SL for all positions...', '');
            try {
                const response = await fetch('/api/set-all-tpsl', { method: 'POST' });
                const data = await response.json();
                showStatus(data.message, data.success ? 'success' : 'error');
            } catch (error) {
                showStatus('Error: ' + error.message, 'error');
            }
        }

        function showAnalysis(symbol) {
            const modal = document.getElementById('modal-overlay');
            document.getElementById('modal-title').textContent = symbol + ' Analysis';
            const report = analysisReports[symbol];
            document.getElementById('modal-body').textContent = report && report.analysis
                ? report.analysis
                : 'No analysis available. Run analysis to generate report.';
            modal.classList.add('active');
        }

        function closeModal(event) {
            if (!event || event.target.id === 'modal-overlay') {
                document.getElementById('modal-overlay').classList.remove('active');
            }
        }

        function showStatus(message, type) {
            const el = document.getElementById('command-status');
            el.textContent = message;
            el.className = 'command-status visible ' + type;
            setTimeout(() => el.classList.remove('visible'), 3000);
        }

        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

        // Backtest function
        async function runBacktest() {
            const modal = document.getElementById('modal-overlay');
            document.getElementById('modal-title').textContent = 'Backtest Results';
            document.getElementById('modal-body').innerHTML = `
                <div class="backtest-loading">
                    <div class="spinner"></div>
                    <div>Running backtest simulation...</div>
                    <div style="font-size: 10px; margin-top: 8px; color: var(--text-muted);">This may take 30-60 seconds</div>
                </div>
            `;
            modal.classList.add('active');

            try {
                const response = await fetch('/api/run-backtest', { method: 'POST' });
                const data = await response.json();

                if (data.error) {
                    document.getElementById('modal-body').innerHTML = `
                        <div style="color: var(--loss); text-align: center; padding: 20px;">
                            <div style="font-size: 24px; margin-bottom: 12px;">Error</div>
                            <div>${data.error}</div>
                        </div>
                    `;
                    return;
                }

                const summary = data.summary || {};
                const reasons = data.close_reasons || {};
                const roiClass = summary.roi_pct >= 0 ? 'positive' : 'negative';
                const pnlClass = summary.total_pnl >= 0 ? 'positive' : 'negative';

                document.getElementById('modal-body').innerHTML = `
                    <div class="backtest-results">
                        <div class="backtest-grid">
                            <div class="backtest-big-stat">
                                <div class="backtest-big-value ${roiClass}">${summary.roi_pct >= 0 ? '+' : ''}${(summary.roi_pct || 0).toFixed(2)}%</div>
                                <div class="backtest-big-label">Return on Investment</div>
                            </div>
                            <div class="backtest-big-stat">
                                <div class="backtest-big-value ${pnlClass}">${summary.total_pnl >= 0 ? '+' : ''}$${(summary.total_pnl || 0).toFixed(2)}</div>
                                <div class="backtest-big-label">Total P/L</div>
                            </div>
                        </div>

                        <div class="backtest-section">
                            <h3>Performance Summary</h3>
                            <div class="backtest-grid">
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Initial Balance</span>
                                    <span class="backtest-stat-value">$${(summary.initial_balance || 0).toFixed(2)}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Final Balance</span>
                                    <span class="backtest-stat-value ${pnlClass}">$${(summary.final_balance || 0).toFixed(2)}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Max Drawdown</span>
                                    <span class="backtest-stat-value negative">${(summary.max_drawdown_pct || 0).toFixed(2)}%</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Profit Factor</span>
                                    <span class="backtest-stat-value">${(summary.profit_factor || 0).toFixed(2)}</span>
                                </div>
                            </div>
                        </div>

                        <div class="backtest-section">
                            <h3>Trade Statistics</h3>
                            <div class="backtest-grid">
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Total Trades</span>
                                    <span class="backtest-stat-value">${summary.total_trades || 0}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Win Rate</span>
                                    <span class="backtest-stat-value">${(summary.win_rate || 0).toFixed(1)}%</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Winning Trades</span>
                                    <span class="backtest-stat-value positive">${summary.winning_trades || 0}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Losing Trades</span>
                                    <span class="backtest-stat-value negative">${summary.losing_trades || 0}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Avg Win</span>
                                    <span class="backtest-stat-value positive">$${(summary.avg_win || 0).toFixed(2)}</span>
                                </div>
                                <div class="backtest-stat">
                                    <span class="backtest-stat-label">Avg Loss</span>
                                    <span class="backtest-stat-value negative">$${(summary.avg_loss || 0).toFixed(2)}</span>
                                </div>
                            </div>
                        </div>

                        <div class="backtest-section">
                            <h3>Close Reasons</h3>
                            <div class="backtest-reasons">
                                ${Object.entries(reasons).map(([reason, count]) => `
                                    <div class="backtest-reason">
                                        <span>${reason.replace(/_/g, ' ')}</span>
                                        <span class="backtest-reason-count">${count}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>

                        <div style="text-align: center; font-size: 10px; color: var(--text-muted); margin-top: 8px;">
                            Backtest uses simplified signal simulation (RSI/MACD/SMA). Live trading uses Grok AI analysis.
                        </div>
                    </div>
                `;
            } catch (error) {
                document.getElementById('modal-body').innerHTML = `
                    <div style="color: var(--loss); text-align: center; padding: 20px;">
                        <div style="font-size: 24px; margin-bottom: 12px;">Error</div>
                        <div>${error.message}</div>
                    </div>
                `;
            }
        }

        // Equity Chart
        let equityChart = null;
        let selectedTimeframeHours = 168; // Default 7 days
        let allEquityData = []; // Store all data

        function setChartTimeframe(hours) {
            selectedTimeframeHours = hours;

            // Update active button
            document.querySelectorAll('.timeframe-btn').forEach(btn => {
                btn.classList.remove('active');
                if (parseInt(btn.dataset.hours) === hours) {
                    btn.classList.add('active');
                }
            });

            // Reload chart with new timeframe
            renderEquityChart();
        }

        function renderEquityChart() {
            if (!allEquityData || allEquityData.length === 0) {
                return;
            }

            const ctx = document.getElementById('equity-chart').getContext('2d');
            const now = new Date();
            const cutoffTime = new Date(now.getTime() - (selectedTimeframeHours * 60 * 60 * 1000));

            // Filter data by selected timeframe
            const filteredData = allEquityData.filter(point => new Date(point.x) >= cutoffTime);

            if (filteredData.length === 0) {
                // If no data in range, show all data
                filteredData.push(...allEquityData);
            }

            // Calculate chart colors based on performance
            const firstValue = filteredData[0].y;
            const lastValue = filteredData[filteredData.length - 1].y;
            const isProfit = lastValue >= firstValue;
            const lineColor = isProfit ? '#00ff88' : '#ff3366';
            const fillColor = isProfit ? 'rgba(0, 255, 136, 0.1)' : 'rgba(255, 51, 102, 0.1)';

            // Format data for Chart.js
            const chartData = filteredData.map(point => ({
                x: new Date(point.x),
                y: point.y
            }));

            // Determine time unit based on range
            let timeUnit = 'hour';
            let displayFormat = 'MMM d, HH:mm';
            if (selectedTimeframeHours <= 1) {
                timeUnit = 'minute';
                displayFormat = 'HH:mm';
            } else if (selectedTimeframeHours <= 24) {
                timeUnit = 'hour';
                displayFormat = 'HH:mm';
            } else if (selectedTimeframeHours <= 168) {
                timeUnit = 'hour';
                displayFormat = 'MMM d, HH:mm';
            } else if (selectedTimeframeHours <= 720) {
                timeUnit = 'day';
                displayFormat = 'MMM d';
            } else {
                timeUnit = 'week';
                displayFormat = 'MMM d';
            }

            // Destroy existing chart
            if (equityChart) {
                equityChart.destroy();
            }

            equityChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Equity',
                        data: chartData,
                        borderColor: lineColor,
                        backgroundColor: fillColor,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointHoverBackgroundColor: lineColor
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: '#0d0d18',
                            borderColor: '#1a1a2e',
                            borderWidth: 1,
                            titleColor: '#e8e8ed',
                            bodyColor: '#00f5ff',
                            titleFont: { family: 'JetBrains Mono' },
                            bodyFont: { family: 'JetBrains Mono' },
                            callbacks: {
                                label: function(context) {
                                    return '$' + context.parsed.y.toFixed(2);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: timeUnit,
                                displayFormats: {
                                    minute: 'HH:mm',
                                    hour: displayFormat,
                                    day: 'MMM d',
                                    week: 'MMM d'
                                }
                            },
                            grid: {
                                color: '#1a1a2e',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#6b6b7b',
                                font: { family: 'JetBrains Mono', size: 10 },
                                maxTicksLimit: 6
                            }
                        },
                        y: {
                            grid: {
                                color: '#1a1a2e',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#6b6b7b',
                                font: { family: 'JetBrains Mono', size: 10 },
                                callback: function(value) {
                                    return '$' + value.toFixed(0);
                                }
                            }
                        }
                    }
                }
            });
        }

        async function loadEquityChart() {
            try {
                const response = await fetch('/api/equity-history');
                const data = await response.json();

                if (!data.history || data.history.length === 0) {
                    return;
                }

                // Store all data
                allEquityData = data.history;

                // Render with current timeframe
                renderEquityChart();
            } catch (error) {
                console.error('Error loading equity chart:', error);
            }
        }

        // Init
        fetchData();
        loadIndicators();
        loadEquityChart();
        setInterval(fetchData, 5000);
        setInterval(loadEquityChart, 60000);  // Refresh chart every minute
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML

@app.get("/api/data")
async def get_data():
    return {
        "bot_status": get_bot_status(),
        "account": get_account_info(),
        "settings": get_current_settings(),
        "analysis_reports": parse_analysis_reports(),
        "logs": get_recent_logs(50)
    }

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
        # Stop current bot
        subprocess.run(["pkill", "-f", "python.*main.py"], capture_output=True)
        await asyncio.sleep(1)

        # Clear logs for fresh output
        with open(LOG_FILE, 'w') as f:
            f.write("Starting fresh analysis...\n")

        # Start bot (will immediately begin analysis)
        bot_dir = str(PROJECT_ROOT)
        subprocess.Popen(
            [f"{bot_dir}/venv/bin/python", "src/main.py"],
            cwd=bot_dir,
            stdout=open(LOG_FILE, 'w'),
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

@app.post("/api/close-position/{symbol}")
async def close_position(symbol: str):
    """Close a position for a given symbol"""
    try:
        if not HYPERLIQUID_AVAILABLE:
            return {"success": False, "message": "HyperLiquid SDK not available"}

        account = get_hyperliquid_account()
        if not account:
            return {"success": False, "message": "No account configured"}

        # Import HyperLiquid exchange
        from hyperliquid.exchange import Exchange

        # Get current position
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(account.address)

        position_size = 0
        for pos in user_state.get("assetPositions", []):
            position = pos.get("position", {})
            if position.get("coin") == symbol:
                position_size = float(position.get("szi", 0))
                break

        if position_size == 0:
            return {"success": False, "message": f"No open position for {symbol}"}

        # Close the position
        exchange = Exchange(account, constants.MAINNET_API_URL)

        # Market close - if long, sell; if short, buy
        is_long = position_size > 0
        close_size = abs(position_size)

        result = exchange.market_close(symbol)

        return {"success": True, "message": f"Closed {symbol} position ({close_size:.6f})"}
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

if __name__ == "__main__":
    print("\n" + "="*60)
    print("CryptoVerge Bot Dashboard")
    print("="*60)
    print("\nStarting dashboard at: http://localhost:8081")
    print("Press Ctrl+C to stop\n")

    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="warning")
