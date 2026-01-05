"""
AI Log Scanner Agent - Comprehensive Trading Bot Analysis

Features:
- Scans Dashboard logs and TradingBot logs
- Cross-references with HyperLiquid to verify positions/orders/P&L
- Detects trading errors, performance issues, and code quality problems
- Saves FULL detailed analysis to JSON file (for reference when fixing)
- Sends SHORT 1-5 word summary to CryptoVerge as todo card
- Priority-based filtering for importance

Run: python src/agents/log_scanner_agent.py
Test: python src/agents/log_scanner_agent.py --once
"""

import os
import sys
import time
import json
import requests
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from termcolor import cprint, colored
from dotenv import load_dotenv
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

SCAN_INTERVAL_MINUTES = 30
CRYPTOVERGE_API = "http://localhost:3000/api/external-todo"
PROJECT_NAME = "Trading_Bot"

# Log files to monitor
LOG_FILES = {
    "dashboard": "/tmp/dashboard.log",
    "trading_bot": "/tmp/bot_output.log",
}

# Data storage
DATA_DIR = Path(__file__).parent.parent / "data" / "log_scanner"
STATE_FILE = DATA_DIR / "scanner_state.json"
ANALYSIS_FILE = DATA_DIR / "analysis_history.json"  # Full analysis for reference

# Priority levels
PRIORITY_CRITICAL = "critical"
PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def ensure_data_dir():
    """Ensure data directory exists"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(filepath: Path, default=None):
    """Load JSON file safely"""
    try:
        if filepath.exists():
            with open(filepath, 'r') as f:
                return json.load(f)
    except:
        pass
    return default if default is not None else {}


def save_json(filepath: Path, data):
    """Save JSON file"""
    ensure_data_dir()
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def get_hyperliquid_state():
    """Get current HyperLiquid account state for verification"""
    try:
        import eth_account
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        private_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
        if not private_key:
            return None

        account = eth_account.Account.from_key(private_key)
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
                    'leverage': p.get('leverage', {}).get('value', 1),
                })

        return {
            'account_value': float(user_state.get('marginSummary', {}).get('accountValue', 0)),
            'margin_used': float(user_state.get('marginSummary', {}).get('totalMarginUsed', 0)),
            'positions': positions,
            'open_orders': [{
                'symbol': o.get('coin'),
                'side': 'sell' if o.get('side') == 'A' else 'buy',  # A=Ask/Sell, B=Bid/Buy
                'size': o.get('sz'),
                'price': o.get('limitPx'),
                'type': 'limit',
                'reduce_only': o.get('reduceOnly', False),  # TP/SL orders are reduceOnly
            } for o in open_orders],
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        cprint(f"Failed to get HyperLiquid state: {e}", "yellow")
        return None


def _create_short_title(line: str, category: str) -> str:
    """Create a meaningful 1-5 word title from error line"""
    import re

    # Clean the line
    clean = re.sub(r'[^\w\s\-:]', '', line).strip()

    # Extract key info based on patterns
    if 'connect' in line.lower() or 'connection' in line.lower():
        if 'ollama' in line.lower():
            return "Ollama not running"
        if 'api' in line.lower():
            return "API connection failed"
        return "Connection error"

    if 'timeout' in line.lower():
        return "Request timeout"

    if 'traceback' in line.lower() or 'exception' in line.lower():
        # Try to extract the exception type
        match = re.search(r'(\w+Error|\w+Exception)', line)
        if match:
            return match.group(1)
        return "Python exception"

    if 'insufficient' in line.lower():
        return "Insufficient funds"

    if 'liquidat' in line.lower():
        return "Liquidation risk"

    # For other errors, take first few meaningful words
    words = clean.split()[:5]
    if words:
        title = ' '.join(words)
        return title[:40] if len(title) > 40 else title

    return category[:30]


def read_log_file(filepath: str, last_position: int = 0) -> tuple[str, int]:
    """Read log file from last position"""
    try:
        if not os.path.exists(filepath):
            return "", 0

        with open(filepath, 'r') as f:
            f.seek(0, 2)
            current_size = f.tell()

            # Handle log rotation
            if current_size < last_position:
                last_position = 0

            f.seek(last_position)
            content = f.read()
            return content, current_size
    except Exception as e:
        return "", last_position


# ============================================================================
# ERROR DETECTION & ANALYSIS
# ============================================================================

def extract_issues(log_content: str, source: str) -> list[dict]:
    """Extract ONLY actual code errors from log content (not normal operations)"""
    issues = []
    lines = log_content.split('\n')

    # Normal operation patterns to ALWAYS ignore
    ignore_patterns = [
        '❌ OFF',           # Agent status indicators
        '✅ ON',            # Agent status indicators
        '• Risk:',          # Status line items
        '• Trading:',
        '• Strategy:',
        '• Copybot:',
        '• Sentiment:',
        'Active Agents:',   # Header for status list
        'Ollama',           # Optional service
        'ollama',
        'Confidence',       # Normal confidence checks
        'confidence',
        'threshold',        # Normal threshold checks
        'Skipping',         # Normal skip behavior
        'skipping',
        'below',            # "below threshold" is normal
        'ready',            # Model ready messages
        'Initialized',      # Initialization messages
        'initialized',
        'thinking',         # AI thinking messages
        'received',         # Response received
        'Scanning',         # Normal scanning
        'scanning',
        'Analyzing',        # Normal analysis
        'analyzing',
    ]

    # ONLY detect actual code errors - not operational messages
    error_patterns = {
        PRIORITY_CRITICAL: [
            ('Traceback', 'Python exception'),
            ('liquidat', 'Liquidation risk'),
            ('insufficient', 'Insufficient funds'),
            ('CRITICAL', 'Critical error'),
        ],
        PRIORITY_HIGH: [
            ('Exception:', 'Unhandled exception'),
            ('Error:', 'Error occurred'),
            ('refused', 'Connection refused'),
            ('timeout', 'Request timeout'),
            ('rejected', 'Order rejected'),
        ],
    }

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Skip false positives (status indicators)
        if any(ignore in line for ignore in ignore_patterns):
            i += 1
            continue

        # Check each priority level
        for priority, patterns in error_patterns.items():
            for pattern, category in patterns:
                if pattern.lower() in line.lower():
                    # Get context (surrounding lines)
                    start = max(0, i - 2)
                    end = min(len(lines), i + 5)
                    context = '\n'.join(lines[start:end])

                    # Avoid duplicates
                    is_dup = any(
                        issue['line'][:50] == line[:50]
                        for issue in issues
                    )

                    if not is_dup:
                        issues.append({
                            'line': line,
                            'context': context,
                            'priority': priority,
                            'category': category,
                            'source': source,
                            'line_num': i,
                        })
                    break
            else:
                continue
            break

        i += 1

    return issues


def cross_reference_with_hyperliquid(issues: list, hl_state: dict) -> list[dict]:
    """Cross-reference log issues with actual HyperLiquid state"""
    cross_ref_issues = []

    if not hl_state:
        return cross_ref_issues

    # Check for position mismatches
    for issue in issues:
        context = issue.get('context', '').lower()

        # Look for position-related issues
        for pos in hl_state.get('positions', []):
            symbol = pos['symbol'].lower()
            if symbol in context:
                issue['hl_verification'] = {
                    'actual_position': pos,
                    'verified': True,
                }

    # Verify P/L accuracy (check if logged P/L matches actual)
    # This is a placeholder - would need more specific log parsing

    return issues


def verify_config_sync() -> list[dict]:
    """Verify dashboard settings match what bot is using"""
    issues = []

    try:
        # Load dashboard settings
        dashboard_settings_file = Path(__file__).parent.parent / "data" / "dashboard_settings.json"
        if dashboard_settings_file.exists():
            with open(dashboard_settings_file, 'r') as f:
                dashboard_settings = json.load(f)

            # Check if settings file is stale (older than 24 hours)
            updated_at = dashboard_settings.get('updated_at', '')
            if updated_at:
                try:
                    last_update = datetime.fromisoformat(updated_at)
                    if datetime.now() - last_update > timedelta(hours=24):
                        issues.append({
                            'line': 'Dashboard settings may be stale',
                            'context': f'Last updated: {updated_at}\nSettings may not reflect current dashboard values.',
                            'priority': PRIORITY_MEDIUM,
                            'category': 'Stale config',
                            'source': 'config_verification',
                        })
                except:
                    pass

            # Compare with trading_agent defaults
            dashboard_confidence = dashboard_settings.get('min_confidence', 70)
            # Check if settings file has the expected structure
            if 'min_confidence' not in dashboard_settings:
                issues.append({
                    'line': 'Dashboard settings missing min_confidence',
                    'context': 'The dashboard settings file is missing expected fields. Bot may use defaults.',
                    'priority': PRIORITY_HIGH,
                    'category': 'Config missing',
                    'source': 'config_verification',
                })
        else:
            issues.append({
                'line': 'Dashboard settings file not found',
                'context': f'Expected at: {dashboard_settings_file}\nBot will use hardcoded defaults.',
                'priority': PRIORITY_MEDIUM,
                'category': 'Config missing',
                'source': 'config_verification',
            })

    except Exception as e:
        issues.append({
            'line': f'Config verification error: {str(e)}',
            'context': traceback.format_exc(),
            'priority': PRIORITY_HIGH,
            'category': 'Config error',
            'source': 'config_verification',
        })

    return issues


def verify_system_state(hl_state: dict) -> list[dict]:
    """Verify system state for ACTUAL issues:
    1. Missing TP/SL on positions
    2. Duplicate orders
    3. Critical margin (>95% only)
    """
    issues = []

    if not hl_state:
        return issues

    orders = hl_state.get('open_orders', [])
    positions = hl_state.get('positions', [])

    # 1. CHECK: Each position should have TP and SL orders
    for pos in positions:
        symbol = pos['symbol']
        size = pos['size']
        entry = pos['entry']
        is_long = size > 0

        # Find reduce_only orders for this position (TP and SL are both reduce_only)
        # For LONG: sell orders - TP is above entry, SL is below entry
        # For SHORT: buy orders - TP is below entry, SL is above entry
        close_side = 'sell' if is_long else 'buy'

        # Get all reduce_only orders for this symbol on the closing side
        close_orders = [o for o in orders
                       if o['symbol'] == symbol
                       and o['side'] == close_side
                       and o.get('reduce_only', False)]

        # Classify as TP or SL based on price relative to entry
        tp_orders = []
        sl_orders = []
        for o in close_orders:
            try:
                price = float(o['price'])
                if is_long:
                    if price > entry:
                        tp_orders.append(o)  # Above entry = TP for long
                    else:
                        sl_orders.append(o)  # Below entry = SL for long
                else:
                    if price < entry:
                        tp_orders.append(o)  # Below entry = TP for short
                    else:
                        sl_orders.append(o)  # Above entry = SL for short
            except (ValueError, TypeError):
                pass

        if not tp_orders:
            issues.append({
                'line': f'{symbol}: Missing Take Profit order',
                'context': f'Position: {abs(size)} {"LONG" if is_long else "SHORT"} @ ${entry:.4f}\nNo TP order found. Risk of missing profit target.',
                'priority': PRIORITY_HIGH,
                'category': 'Missing TP',
                'source': 'hyperliquid_verification',
                'fixed_title': f'{symbol} missing TP',
            })

        if not sl_orders:
            issues.append({
                'line': f'{symbol}: Missing Stop Loss order',
                'context': f'Position: {abs(size)} {"LONG" if is_long else "SHORT"} @ ${entry:.4f}\nNo SL order found. UNPROTECTED POSITION!',
                'priority': PRIORITY_CRITICAL,
                'category': 'Missing SL',
                'source': 'hyperliquid_verification',
                'fixed_title': f'{symbol} missing SL',
            })

    # 2. CHECK: Duplicate orders (same symbol, side, similar price)
    order_groups = {}
    for order in orders:
        key = (order['symbol'], order['side'], order['type'])
        if key not in order_groups:
            order_groups[key] = []
        order_groups[key].append(order)

    for key, group in order_groups.items():
        if len(group) > 1:
            symbol, side, order_type = key
            # Check if prices are similar (within 1%)
            prices = [float(o['price']) for o in group if o.get('price')]
            if prices:
                avg_price = sum(prices) / len(prices)
                similar = all(abs(p - avg_price) / avg_price < 0.01 for p in prices)
                if similar:
                    issues.append({
                        'line': f'{symbol}: Duplicate {side} {order_type} orders',
                        'context': f'Found {len(group)} similar orders:\n' + '\n'.join([f"  - {o['size']} @ ${o['price']}" for o in group]),
                        'priority': PRIORITY_HIGH,
                        'category': 'Duplicate orders',
                        'source': 'hyperliquid_verification',
                        'fixed_title': f'{symbol} duplicate {order_type}',  # Fixed title for deduplication
                    })

    # 3. CHECK: Only critical margin (>95%)
    margin_used = hl_state.get('margin_used', 0)
    account_value = hl_state.get('account_value', 0)

    if account_value > 0:
        margin_pct = (margin_used / account_value) * 100
        if margin_pct > 95:
            issues.append({
                'line': f'CRITICAL: Margin at {margin_pct:.1f}%',
                'context': f'Account: ${account_value:.2f}, Margin: ${margin_used:.2f}\nLiquidation imminent!',
                'priority': PRIORITY_CRITICAL,
                'category': 'Liquidation risk',
                'source': 'hyperliquid_verification',
            })

    return issues


def verify_auto_tpsl(hl_state: dict) -> list[dict]:
    """Verify auto TP/SL is working correctly:
    1. Check if auto TP/SL is enabled but not setting orders
    2. Compare actual TP/SL with analysis recommendations
    3. Check if TP/SL exceeds max SL setting
    """
    issues = []

    if not hl_state:
        return issues

    try:
        # Load auto TP/SL settings
        settings_file = Path(__file__).parent.parent / "data" / "dashboard_settings.json"
        if not settings_file.exists():
            return issues

        with open(settings_file, 'r') as f:
            settings = json.load(f)

        auto_enabled = settings.get("auto_tpsl_enabled", False)
        max_sl_pct = settings.get("auto_tpsl_max_sl", 7)
        tpsl_mode = settings.get("auto_tpsl_mode", "moderate")

        if not auto_enabled:
            return issues  # Auto TP/SL not enabled, skip checks

        # Load analysis reports for recommendations
        analysis_file = Path(__file__).parent.parent / "data" / "analysis_reports.json"
        analysis_reports = {}
        if analysis_file.exists():
            with open(analysis_file, 'r') as f:
                analysis_reports = json.load(f)

        orders = hl_state.get('open_orders', [])
        positions = hl_state.get('positions', [])

        for pos in positions:
            symbol = pos['symbol']
            size = pos['size']
            entry = pos['entry']
            is_long = size > 0

            # Get analysis for this symbol
            analysis = analysis_reports.get(symbol, {})
            action = analysis.get('action', '')
            recommendations = analysis.get('tpsl_recommendations', {})

            # Only check if analysis was bullish (BUY)
            if action != 'BUY':
                continue

            # Get recommended TP/SL for selected mode
            rec = recommendations.get(tpsl_mode, {})
            rec_tp = rec.get('tp')
            rec_sl = rec.get('sl')

            if not rec_tp or not rec_sl:
                issues.append({
                    'line': f'{symbol}: Auto TP/SL enabled but no recommendations',
                    'context': f'Auto TP/SL is ON but analysis for {symbol} has no TP/SL recommendations.\nMode: {tpsl_mode}\nAnalysis action: {action}',
                    'priority': PRIORITY_HIGH,
                    'category': 'Auto TP/SL issue',
                    'source': 'auto_tpsl_verification',
                    'fixed_title': f'{symbol} no TPSL recs',
                })
                continue

            # Find actual TP/SL orders
            close_side = 'sell' if is_long else 'buy'
            close_orders = [o for o in orders
                          if o['symbol'] == symbol
                          and o['side'] == close_side
                          and o.get('reduce_only', False)]

            actual_tp = None
            actual_sl = None
            for o in close_orders:
                try:
                    price = float(o['price'])
                    if is_long:
                        if price > entry:
                            actual_tp = price
                        else:
                            actual_sl = price
                    else:
                        if price < entry:
                            actual_tp = price
                        else:
                            actual_sl = price
                except (ValueError, TypeError):
                    pass

            # Check if actual TP/SL matches recommendations (within 2% tolerance)
            if actual_tp and rec_tp:
                tp_diff_pct = abs(actual_tp - rec_tp) / rec_tp * 100
                if tp_diff_pct > 2:
                    issues.append({
                        'line': f'{symbol}: TP differs from recommendation',
                        'context': f'Actual TP: ${actual_tp:.6f}\nRecommended ({tpsl_mode}): ${rec_tp:.6f}\nDifference: {tp_diff_pct:.1f}%\n\nConsider updating TP to match analysis.',
                        'priority': PRIORITY_MEDIUM,
                        'category': 'TP/SL mismatch',
                        'source': 'auto_tpsl_verification',
                        'fixed_title': f'{symbol} TP mismatch',
                    })

            if actual_sl and rec_sl:
                sl_diff_pct = abs(actual_sl - rec_sl) / rec_sl * 100
                if sl_diff_pct > 2:
                    issues.append({
                        'line': f'{symbol}: SL differs from recommendation',
                        'context': f'Actual SL: ${actual_sl:.6f}\nRecommended ({tpsl_mode}): ${rec_sl:.6f}\nDifference: {sl_diff_pct:.1f}%\n\nConsider updating SL to match analysis.',
                        'priority': PRIORITY_MEDIUM,
                        'category': 'TP/SL mismatch',
                        'source': 'auto_tpsl_verification',
                        'fixed_title': f'{symbol} SL mismatch',
                    })

            # Check if SL exceeds max allowed
            if actual_sl:
                if is_long:
                    actual_sl_pct = ((entry - actual_sl) / entry) * 100
                else:
                    actual_sl_pct = ((actual_sl - entry) / entry) * 100

                if actual_sl_pct > max_sl_pct:
                    issues.append({
                        'line': f'{symbol}: SL exceeds max limit ({actual_sl_pct:.1f}% > {max_sl_pct}%)',
                        'context': f'Entry: ${entry:.6f}\nActual SL: ${actual_sl:.6f} ({actual_sl_pct:.1f}%)\nMax allowed: {max_sl_pct}%\n\nSL should be adjusted to respect max loss setting.',
                        'priority': PRIORITY_HIGH,
                        'category': 'SL exceeds max',
                        'source': 'auto_tpsl_verification',
                        'fixed_title': f'{symbol} SL over max',
                    })

    except Exception as e:
        cprint(f"Error in auto TP/SL verification: {e}", "red")

    return issues


def verify_daily_drawdown() -> list[dict]:
    """Verify daily drawdown status and alert if approaching limit"""
    issues = []

    try:
        # Load drawdown state
        drawdown_state_file = Path(__file__).parent.parent / "data" / "drawdown_state.json"
        settings_file = Path(__file__).parent.parent / "data" / "dashboard_settings.json"

        if not drawdown_state_file.exists():
            return issues

        with open(drawdown_state_file, 'r') as f:
            state = json.load(f)

        # Check if circuit breaker is triggered
        if state.get('circuit_breaker_triggered'):
            issues.append({
                'line': f"Circuit breaker triggered at {state.get('triggered_at', 'unknown')}",
                'context': f"Daily drawdown limit was reached. Trading halted.\nDate: {state.get('date')}\nStarting balance: ${state.get('starting_balance', 0):,.2f}",
                'priority': PRIORITY_CRITICAL,
                'category': 'Circuit breaker active',
                'source': 'drawdown_verification',
                'fixed_title': 'Trading halted - drawdown limit',
            })
            return issues

        # Get current balance to check live status
        hl_state = get_hyperliquid_state()
        if not hl_state:
            return issues

        current_balance = hl_state.get('account_value', 0)
        starting_balance = state.get('starting_balance', current_balance)
        daily_pnl = current_balance - starting_balance
        daily_pnl_pct = (daily_pnl / starting_balance * 100) if starting_balance > 0 else 0

        # Load settings to get limit
        limit_usd = 50  # Default
        warning_pct = 70
        try:
            # Try to import from trading_agent for consistency
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from trading_agent import DAILY_DRAWDOWN_LIMIT_USD, DRAWDOWN_WARNING_PCT, DAILY_DRAWDOWN_ENABLED
            limit_usd = DAILY_DRAWDOWN_LIMIT_USD
            warning_pct = DRAWDOWN_WARNING_PCT
            if not DAILY_DRAWDOWN_ENABLED:
                return issues
        except ImportError:
            pass

        warning_threshold = -limit_usd * (warning_pct / 100)

        # Check if approaching limit (warning zone)
        if daily_pnl <= warning_threshold:
            pct_of_limit = abs(daily_pnl / limit_usd * 100)
            issues.append({
                'line': f"Daily loss ${abs(daily_pnl):,.2f} is {pct_of_limit:.0f}% of limit",
                'context': f"Daily P&L: ${daily_pnl:,.2f} ({daily_pnl_pct:+.2f}%)\nLimit: ${limit_usd:,.2f}\nApproaching circuit breaker threshold.\n\nConsider reducing position sizes or closing losing trades.",
                'priority': PRIORITY_HIGH if pct_of_limit >= 90 else PRIORITY_MEDIUM,
                'category': 'Drawdown warning',
                'source': 'drawdown_verification',
                'fixed_title': f'Daily loss at {pct_of_limit:.0f}% of limit',
            })

    except Exception as e:
        cprint(f"Error in drawdown verification: {e}", "red")

    return issues


# ============================================================================
# AI ANALYSIS
# ============================================================================

def analyze_with_ai(issues: list[dict], hl_state: Optional[dict]) -> list[dict]:
    """Use AI to analyze issues and generate suggestions"""
    if not issues:
        return []

    suggestions = []

    try:
        from models.model_factory import model_factory
        # Try xai first (working), then claude as fallback
        model = model_factory.get_model('xai') or model_factory.get_model('claude')

        if not model:
            raise ImportError("No AI model available")

        # Group issues for batch analysis
        issues_summary = "\n".join([
            f"[{i['priority'].upper()}] {i['category']}: {i['line'][:100]}"
            for i in issues[:10]  # Limit to 10 issues
        ])

        hl_context = ""
        if hl_state:
            hl_context = f"""
Current HyperLiquid State:
- Account Value: ${hl_state.get('account_value', 0):.2f}
- Margin Used: ${hl_state.get('margin_used', 0):.2f}
- Positions: {len(hl_state.get('positions', []))}
- Open Orders: {len(hl_state.get('open_orders', []))}
"""

        prompt = f"""Analyze these trading bot issues and provide suggestions.

ISSUES FOUND:
{issues_summary}

{hl_context}

For EACH issue, provide:
1. SHORT_TITLE: 1-5 word summary (for todo card)
2. FULL_ANALYSIS: Detailed explanation and fix suggestion
3. CODE_FIX: If applicable, specific code changes needed
4. PRIORITY: critical/high/medium/low

Format as JSON array:
[{{"short_title": "...", "full_analysis": "...", "code_fix": "...", "priority": "..."}}]

Focus on actionable fixes. Be specific about file names and line numbers if possible."""

        response = model.generate_response(
            system_prompt="You are an expert trading bot debugger. Analyze issues and provide specific, actionable fixes.",
            user_content=prompt,
            max_tokens=2000,
            temperature=0.3
        )

        # Handle different response formats (text for Claude, content for xAI/OpenAI)
        if hasattr(response, 'text'):
            response_text = response.text
        elif hasattr(response, 'content'):
            response_text = response.content
        else:
            response_text = str(response)

        # Try to parse JSON from response
        try:
            # Find JSON array in response
            start = response_text.find('[')
            end = response_text.rfind(']') + 1
            if start >= 0 and end > start:
                json_str = response_text[start:end]
                suggestions = json.loads(json_str)

                # Merge fixed_titles from original issues (by index)
                for idx, suggestion in enumerate(suggestions):
                    if idx < len(issues) and issues[idx].get('fixed_title'):
                        suggestion['fixed_title'] = issues[idx]['fixed_title']

        except json.JSONDecodeError:
            # Fallback: create basic suggestions
            for issue in issues[:5]:
                short_title = _create_short_title(issue['line'], issue['category'])
                suggestions.append({
                    'short_title': short_title,
                    'full_analysis': f"{issue['category']}: {issue['line']}\n\nContext:\n{issue['context']}",
                    'code_fix': 'Review and fix manually',
                    'priority': issue['priority'],
                    'fixed_title': issue.get('fixed_title'),  # Preserve for deduplication
                })

    except ImportError as e:
        cprint(f"AI model import error: {e}", "yellow")
        for issue in issues[:5]:
            short_title = _create_short_title(issue['line'], issue['category'])
            suggestions.append({
                'short_title': short_title,
                'full_analysis': f"{issue['category']}: {issue['line']}\n\nContext:\n{issue['context']}",
                'code_fix': 'Review manually',
                'priority': issue['priority'],
                'fixed_title': issue.get('fixed_title'),  # Preserve for deduplication
            })
    except Exception as e:
        cprint(f"AI analysis error ({type(e).__name__}): {e}", "red")
        traceback.print_exc()
        # Fallback for any other errors
        for issue in issues[:5]:
            short_title = _create_short_title(issue['line'], issue['category'])
            suggestions.append({
                'short_title': short_title,
                'full_analysis': f"{issue['category']}: {issue['line']}\n\nContext:\n{issue['context']}",
                'code_fix': 'Review manually',
                'priority': issue['priority'],
                'fixed_title': issue.get('fixed_title'),  # Preserve for deduplication
            })

    return suggestions


# ============================================================================
# STORAGE & NOTIFICATION
# ============================================================================

def save_analysis(suggestions: list[dict]):
    """Save full analysis to file for later reference"""
    history = load_json(ANALYSIS_FILE, [])

    timestamp = datetime.now().isoformat()

    for suggestion in suggestions:
        entry = {
            'id': f"issue-{int(time.time())}-{len(history)}",
            'timestamp': timestamp,
            'short_title': suggestion.get('fixed_title') or suggestion.get('short_title', 'Unknown issue'),
            'full_analysis': suggestion.get('full_analysis', ''),
            'code_fix': suggestion.get('code_fix', ''),
            'priority': suggestion.get('priority', PRIORITY_MEDIUM),
            'status': 'open',  # open, in_progress, resolved
            'fixed_title': suggestion.get('fixed_title'),  # Preserve for deduplication
        }
        history.append(entry)

    # Keep last 100 entries
    history = history[-100:]
    save_json(ANALYSIS_FILE, history)

    cprint(f"💾 Saved {len(suggestions)} analysis entries to {ANALYSIS_FILE}", "cyan")


def _normalize_title(title: str) -> str:
    """Normalize title for deduplication comparison"""
    import re
    # Remove numbers, special chars, lowercase, strip whitespace
    normalized = re.sub(r'[^a-z\s]', '', title.lower())
    # Remove common filler words and collapse whitespace
    normalized = ' '.join(normalized.split())
    return normalized


def send_to_cryptoverge(suggestion: dict, sent_titles: set) -> bool:
    """Send short summary to CryptoVerge as todo card (with deduplication)"""
    try:
        # Use fixed_title for verification issues (consistent deduplication)
        # Fall back to AI-generated short_title
        short_title = suggestion.get('fixed_title') or suggestion.get('short_title', 'Check logs')
        short_title = short_title[:50]
        normalized = _normalize_title(short_title)

        # Skip if we've already sent a similar issue
        if normalized in sent_titles:
            cprint(f"  ⏭️  Skipped (duplicate): {short_title}", "white")
            return False

        payload = {
            "projectName": PROJECT_NAME,
            "text": short_title,
            "priority": suggestion.get('priority', PRIORITY_MEDIUM),
            "source": "log_scanner_agent"
        }

        response = requests.post(
            CRYPTOVERGE_API,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            cprint(f"  ✅ Card created: {short_title}", "green")
            sent_titles.add(normalized)  # Track as sent
            return True
        else:
            cprint(f"  ⚠️ API returned {response.status_code}", "yellow")
            return False

    except requests.exceptions.ConnectionError:
        cprint(f"  ⚠️ CryptoVerge not running (localhost:3000)", "yellow")
        return False
    except Exception as e:
        cprint(f"  ❌ Error: {e}", "red")
        return False


def get_analysis_by_title(title: str) -> Optional[dict]:
    """Retrieve full analysis by short title (for when user wants to fix)"""
    history = load_json(ANALYSIS_FILE, [])

    title_lower = title.lower()
    for entry in reversed(history):  # Most recent first
        if title_lower in entry.get('short_title', '').lower():
            return entry

    return None


# ============================================================================
# MAIN SCAN FUNCTION
# ============================================================================

def run_scan():
    """Run comprehensive log scan"""
    cprint(f"\n{'='*70}", "cyan")
    cprint(f"🔍 AI LOG SCANNER - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "cyan")
    cprint(f"{'='*70}", "cyan")

    state = load_json(STATE_FILE, {'last_positions': {}, 'sent_titles': []})
    all_issues = []

    # Load previously sent titles for deduplication
    sent_titles = set(state.get('sent_titles', []))

    # 1. Scan log files
    cprint("\n📋 SCANNING LOGS...", "white")
    for name, filepath in LOG_FILES.items():
        last_pos = state.get('last_positions', {}).get(filepath, 0)
        content, new_pos = read_log_file(filepath, last_pos)

        if content:
            cprint(f"   {name}: {len(content)} new bytes", "white")
            issues = extract_issues(content, name)
            if issues:
                cprint(f"   → Found {len(issues)} potential issues", "yellow")
                all_issues.extend(issues)

        state.setdefault('last_positions', {})[filepath] = new_pos

    # 2. Get HyperLiquid state for verification
    cprint("\n🔗 VERIFYING WITH HYPERLIQUID...", "white")
    hl_state = get_hyperliquid_state()

    if hl_state:
        cprint(f"   Account: ${hl_state['account_value']:.2f}", "white")
        cprint(f"   Positions: {len(hl_state['positions'])}", "white")
        cprint(f"   Open Orders: {len(hl_state['open_orders'])}", "white")

        # Cross-reference issues with HL state
        all_issues = cross_reference_with_hyperliquid(all_issues, hl_state)

        # Check for system-level issues (TP/SL, duplicates)
        system_issues = verify_system_state(hl_state)
        all_issues.extend(system_issues)

        # Check auto TP/SL accuracy
        cprint("\n🎯 VERIFYING AUTO TP/SL...", "white")
        auto_tpsl_issues = verify_auto_tpsl(hl_state)
        if auto_tpsl_issues:
            cprint(f"   → Found {len(auto_tpsl_issues)} auto TP/SL issues", "yellow")
            all_issues.extend(auto_tpsl_issues)
        else:
            cprint("   ✓ Auto TP/SL OK", "green")
    else:
        cprint("   ⚠️ Could not connect to HyperLiquid", "yellow")

    # 2b. Check config sync
    cprint("\n⚙️  VERIFYING CONFIG...", "white")
    config_issues = verify_config_sync()
    if config_issues:
        cprint(f"   → Found {len(config_issues)} config issues", "yellow")
        all_issues.extend(config_issues)
    else:
        cprint("   ✓ Config OK", "green")

    # 2c. Check daily drawdown
    cprint("\n🛑 VERIFYING DAILY DRAWDOWN...", "white")
    drawdown_issues = verify_daily_drawdown()
    if drawdown_issues:
        for issue in drawdown_issues:
            if issue['priority'] == PRIORITY_CRITICAL:
                cprint(f"   ⛔ {issue['line']}", "red")
            else:
                cprint(f"   ⚠️ {issue['line']}", "yellow")
        all_issues.extend(drawdown_issues)
    else:
        cprint("   ✓ Daily drawdown OK", "green")

    # 3. AI Analysis
    if all_issues:
        cprint(f"\n🤖 AI ANALYSIS ({len(all_issues)} issues)...", "cyan")
        suggestions = analyze_with_ai(all_issues, hl_state)

        if suggestions:
            # 4. Save full analysis to file
            save_analysis(suggestions)

            # 5. Send short summaries to CryptoVerge (with deduplication)
            cprint(f"\n📤 CREATING TODO CARDS...", "white")
            cards_created = 0
            cards_skipped = 0
            for suggestion in suggestions:
                if send_to_cryptoverge(suggestion, sent_titles):
                    cards_created += 1
                else:
                    cards_skipped += 1

            # Summary
            cprint(f"\n📊 SUMMARY:", "cyan")
            cprint(f"   Issues found: {len(all_issues)}", "white")
            cprint(f"   New cards created: {cards_created}", "white")
            if cards_skipped > 0:
                cprint(f"   Duplicates skipped: {cards_skipped}", "white")
            cprint(f"   Full analysis saved to: {ANALYSIS_FILE}", "white")
    else:
        cprint("\n✨ No issues found - system healthy!", "green")

    # Save state (including sent titles for deduplication)
    state['last_scan'] = int(time.time())
    state['sent_titles'] = list(sent_titles)  # Convert set back to list for JSON
    save_json(STATE_FILE, state)

    cprint(f"\n{'='*70}\n", "cyan")


def lookup_issue(title: str):
    """Look up full analysis for an issue by title"""
    entry = get_analysis_by_title(title)

    if entry:
        cprint(f"\n{'='*70}", "cyan")
        cprint(f"📋 ISSUE: {entry['short_title']}", "cyan")
        cprint(f"{'='*70}", "cyan")
        cprint(f"\nPriority: {entry['priority'].upper()}", "yellow")
        cprint(f"Timestamp: {entry['timestamp']}", "white")
        cprint(f"\n📝 FULL ANALYSIS:", "white")
        print(entry['full_analysis'])
        cprint(f"\n🔧 CODE FIX:", "green")
        print(entry['code_fix'])
        cprint(f"\n{'='*70}\n", "cyan")
    else:
        cprint(f"❌ No analysis found for '{title}'", "red")
        cprint("Run 'python log_scanner_agent.py --list' to see all issues", "yellow")


def list_issues():
    """List all stored issues"""
    history = load_json(ANALYSIS_FILE, [])

    if not history:
        cprint("No issues in history", "yellow")
        return

    cprint(f"\n{'='*70}", "cyan")
    cprint(f"📋 STORED ISSUES ({len(history)} total)", "cyan")
    cprint(f"{'='*70}", "cyan")

    for entry in reversed(history[-20:]):  # Show last 20
        priority_color = {
            'critical': 'red',
            'high': 'yellow',
            'medium': 'white',
            'low': 'cyan',
        }.get(entry['priority'], 'white')

        status_icon = '✅' if entry['status'] == 'resolved' else '⏳' if entry['status'] == 'in_progress' else '📌'

        cprint(f"{status_icon} [{entry['priority'].upper():8}] {entry['short_title']}", priority_color)

    cprint(f"\n{'='*70}\n", "cyan")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='AI Log Scanner Agent')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--lookup', type=str, help='Look up analysis by title')
    parser.add_argument('--list', action='store_true', help='List all stored issues')
    args = parser.parse_args()

    if args.lookup:
        lookup_issue(args.lookup)
        return

    if args.list:
        list_issues()
        return

    if args.once:
        run_scan()
        return

    # Continuous mode
    cprint("""
╔═══════════════════════════════════════════════════════════════════════╗
║                   🔍 AI LOG SCANNER AGENT                             ║
║                                                                       ║
║  Comprehensive analysis every 30 minutes:                             ║
║  • Dashboard logs + TradingBot logs                                   ║
║  • Cross-reference with HyperLiquid positions/orders                  ║
║  • AI-powered error detection and fix suggestions                     ║
║  • Full analysis saved for reference                                  ║
║  • Short summaries sent to CryptoVerge as todo cards                  ║
║                                                                       ║
║  Commands:                                                            ║
║  --once           Run single scan                                     ║
║  --list           Show all stored issues                              ║
║  --lookup "title" Get full analysis for issue                         ║
╚═══════════════════════════════════════════════════════════════════════╝
    """, "cyan")

    while True:
        try:
            run_scan()

            next_scan = datetime.now() + timedelta(minutes=SCAN_INTERVAL_MINUTES)
            cprint(f"⏳ Next scan at {next_scan.strftime('%H:%M:%S')} ({SCAN_INTERVAL_MINUTES} min)", "white")
            time.sleep(SCAN_INTERVAL_MINUTES * 60)

        except KeyboardInterrupt:
            cprint("\n👋 Log Scanner Agent stopped", "yellow")
            break
        except Exception as e:
            cprint(f"❌ Error: {e}", "red")
            traceback.print_exc()
            time.sleep(60)


if __name__ == "__main__":
    main()
