"""
🌙 Moon Dev's LLM Trading Agent 🌙

DUAL-MODE AI TRADING SYSTEM:

🤖 SINGLE MODEL MODE (Fast - ~10 seconds per token):
   - Uses one AI model for quick trading decisions
   - Best for: Fast execution, high-frequency strategies
   - Configure model in config.py: AI_MODEL_TYPE and AI_MODEL_NAME

🌊 SWARM MODE (Consensus - ~45-60 seconds per token):
   - Queries 6 AI models simultaneously for consensus voting
   - Models vote: "Buy", "Sell", or "Do Nothing"
   - Majority decision wins with confidence percentage
   - Best for: Higher confidence trades, 15-minute+ timeframes

   Active Swarm Models:
   1. Claude Sonnet 4.5 - Anthropic's latest reasoning model
   2. GPT-5 - OpenAI's most advanced model
   3. Qwen3 8B (Ollama) - Fast local reasoning via Ollama (free!)
   4. Grok-4 Fast Reasoning - xAI's 2M context model
   5. DeepSeek Chat - DeepSeek API reasoning model
   6. DeepSeek-R1 Local - Local reasoning model (free!)

   Trading Actions:
   - "Buy" = Open/maintain position at target size ($25)
   - "Sell" = Close entire position (exit to cash)
   - "Do Nothing" = Hold current position unchanged (no action)

CONFIGURATION:
   ⚙️ ALL settings are configured at the top of THIS file (lines 66-120)

   🏦 Exchange Selection (line 75):
   - EXCHANGE: "ASTER", "HYPERLIQUID", or "SOLANA"
   - Aster = Futures DEX (long/short capable)
   - HyperLiquid = Perpetuals (long/short capable)
   - Solana = On-chain DEX (long only)

   🌊 AI Mode (line 81):
   - USE_SWARM_MODE: True = 6-model consensus, False = single model

   📈 Trading Mode (line 85):
   - LONG_ONLY: True = Long positions only (all exchanges)
   - LONG_ONLY: False = Long & Short (Aster/HyperLiquid only)
   - When LONG_ONLY: SELL closes position, can't open shorts
   - When LONG/SHORT: SELL can close long OR open short

   💰 Position Sizing (lines 113-120):
   - usd_size: $25 target NOTIONAL position (total exposure)
     * On Aster/HyperLiquid with 5x leverage: $25 position = $5 margin
     * Leverage configured in nice_funcs_aster.py (DEFAULT_LEVERAGE)
   - max_usd_order_size: $3 order chunks
   - MAX_POSITION_PERCENTAGE: 30% max per position
   - CASH_PERCENTAGE: 20% min cash buffer

   📊 Market Data (lines 122-126):
   - DAYSBACK_4_DATA: 3 days history
   - DATA_TIMEFRAME: '1H' bars (~72 bars)
     Change to '15m' for 15-minute bars (~288 bars)
     Options: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 8H, 12H, 1D, 3D, 1W, 1M

   🎯 Tokens (lines 140-143):
   - MONITORED_TOKENS: List of tokens to analyze and trade
   - ⚠️ ALL tokens in this list will be analyzed (one at a time)
   - Comment out tokens you don't want with # to disable them

   Portfolio Allocation:
   - Automatically runs if swarm recommends BUY signals
   - Skipped if all signals are SELL or DO NOTHING

   Each swarm query receives:
   - Full OHLCV dataframe (Open, High, Low, Close, Volume)
   - Strategy signals (if available)
   - Token metadata

Built with love by Moon Dev 🚀
"""

# ============================================================================
# 🔧 TRADING AGENT CONFIGURATION - ALL SETTINGS IN ONE PLACE
# ============================================================================

# 🏦 EXCHANGE SELECTION
EXCHANGE = "HYPERLIQUID"  # Options: "ASTER", "HYPERLIQUID", "SOLANA"
                     # - "ASTER" = Aster DEX futures (supports long/short)
                     # - "HYPERLIQUID" = HyperLiquid perpetuals (supports long/short)
                     # - "SOLANA" = Solana on-chain DEX (long only)

# 🌊 AI MODE SELECTION
USE_SWARM_MODE = False  # True = multi-model swarm consensus, False = single model (faster)
                        # False = Single model fast execution (~10s per token)

# 📈 TRADING MODE SETTINGS
LONG_ONLY = False  # False = Allow both Long & Short positions (HyperLiquid)
                  # False = Long & Short positions (works on Aster/HyperLiquid)
                  #
                  # When LONG_ONLY = True:
                  #   - "Buy" = Opens/maintains long position
                  #   - "Sell" = Closes long position (exit to cash)
                  #   - Can NOT open short positions
                  #
                  # When LONG_ONLY = False (Aster/HyperLiquid only):
                  #   - "Buy" = Opens/maintains long position
                  #   - "Sell" = Closes long OR opens short position
                  #   - Full long/short capability
                  #
                  # Note: Solana is always LONG_ONLY (exchange limitation)

# 🤖 SINGLE MODEL SETTINGS (only used when USE_SWARM_MODE = False)
AI_MODEL_TYPE = 'xai'  # Options: 'groq', 'openai', 'claude', 'deepseek', 'xai', 'ollama', 'gemini'
AI_MODEL_NAME = 'grok-4-fast-reasoning'   # xAI Grok 4 - 2M context, no rate limits
AI_TEMPERATURE = 0.7   # Creativity vs precision (0-1)
AI_MAX_TOKENS = 4096   # Max tokens for AI response (increased for Claude)

# 💰 POSITION SIZING & RISK MANAGEMENT
USE_PORTFOLIO_ALLOCATION = False # True = Use AI for portfolio allocation across multiple tokens
                                 # False = Simple mode - trade single token at MAX_POSITION_PERCENTAGE

MAX_POSITION_PERCENTAGE = 40     # % of account balance to use as MARGIN per position (0-100)
                                 # How it works per exchange:
                                 # - ASTER/HYPERLIQUID: % of balance used as MARGIN (then multiplied by leverage)
                                 #   Example: $100 balance, 90% = $90 margin
                                 #            At 90x leverage = $90 × 90 = $8,100 notional position
                                 # - SOLANA: Uses % of USDC balance directly (no leverage)
                                 #   Example: 100 USDC, 90% = 90 USDC position

LEVERAGE = 20                    # Leverage multiplier (1-50x on HyperLiquid)
                                 # Higher leverage = bigger position with same margin, higher liquidation risk
                                 # Examples with $100 margin:
                                 #           5x = $100 margin → $500 notional position
                                 #          10x = $100 margin → $1,000 notional position
                                 #          90x = $100 margin → $9,000 notional position
                                 # Note: Only applies to Aster and HyperLiquid (ignored on Solana)

# Stop Loss & Take Profit
STOP_LOSS_PERCENTAGE = 3.0       # % loss to trigger stop loss exit (e.g., 5.0 = -5%)
TAKE_PROFIT_PERCENTAGE = 10.0    # % gain to trigger take profit exit (e.g., 12.0 = +12%)
PNL_CHECK_INTERVAL = 5           # Seconds between P&L checks when position is open

# Trailing Stop Loss
USE_TRAILING_STOP = True         # Enable trailing stop loss
TRAILING_STOP_ACTIVATION = 3.0   # Activate trailing stop after this % profit
TRAILING_STOP_DISTANCE = 2.0     # Trail this % behind highest price

# 📊 ATR-BASED DYNAMIC STOPS (volatility-adjusted)
USE_ATR_STOPS = True             # True = Use ATR-based stops, False = use fixed percentage
ATR_PERIOD = 14                  # ATR calculation period (14 is standard)
ATR_SL_MULTIPLIER = 2.0          # Stop Loss = Entry ± (ATR × multiplier)
                                 # Higher = wider stops (less likely to be stopped out by noise)
                                 # Lower = tighter stops (more risk of premature exit)
                                 # Common values: 1.5 (tight), 2.0 (standard), 3.0 (wide)
ATR_TP_MULTIPLIER = 3.0          # Take Profit = Entry ± (ATR × multiplier)
                                 # Usually 1.5x-2x the SL multiplier for good risk:reward
ATR_MIN_SL_PCT = 1.0             # Minimum SL percentage (floor) - prevents too tight stops
ATR_MAX_SL_PCT = 7.0             # Maximum SL percentage (ceiling) - prevents too wide stops
ATR_TRAILING_MULTIPLIER = 1.5    # Trailing stop distance = ATR × multiplier

# 🛑 DAILY DRAWDOWN CIRCUIT BREAKER
DAILY_DRAWDOWN_ENABLED = True    # Enable daily drawdown protection
DAILY_DRAWDOWN_LIMIT_USD = 50    # Max daily loss in USD before stopping (e.g., 50 = stop after -$50)
DAILY_DRAWDOWN_LIMIT_PCT = 10    # Max daily loss as % of starting balance (e.g., 10 = stop after -10%)
USE_DAILY_DRAWDOWN_PCT = False   # True = use percentage limit, False = use USD limit
CLOSE_ON_DRAWDOWN = False        # True = close all positions when limit hit, False = just stop new trades
DRAWDOWN_WARNING_PCT = 70        # Warn when this % of drawdown limit is reached (e.g., 70 = warn at 70% of limit)

# Confidence Threshold
MIN_CONFIDENCE_TO_TRADE = 70     # Only trade when AI confidence >= this % (0-100)
                                 # Higher = fewer but higher quality trades

# 🔄 REVERSAL PROTECTION (prevent costly flip-flopping)
REVERSAL_CONFIRMATIONS_REQUIRED = 2  # Number of consecutive signals needed to reverse
                                      # 2 = need 2 SELL signals in a row to reverse LONG to SHORT
REVERSAL_MIN_CONFIDENCE = 75          # Minimum confidence required for reversals (higher than normal)
                                      # Reversals are expensive (2x fees), so require stronger signal

# 🎯 DYNAMIC POSITION SIZING (based on AI confidence)
USE_DYNAMIC_SIZING = True        # True = Scale position size by confidence
                                 # False = Use fixed MAX_POSITION_PERCENTAGE
DYNAMIC_SIZE_MIN_PCT = 10        # Minimum position % at MIN_CONFIDENCE_TO_TRADE
DYNAMIC_SIZE_MAX_PCT = 30        # Maximum position % at 100% confidence
                                 # Example: 70% conf = 10%, 85% conf = 20%, 100% conf = 30%

# Legacy settings (kept for compatibility, not used in new logic)
usd_size = 25                    # [DEPRECATED] Use MAX_POSITION_PERCENTAGE instead
max_usd_order_size = 3           # Maximum order chunk size in USD (for Solana chunking)

# 📊 MARKET DATA COLLECTION
DAYSBACK_4_DATA = 60             # Days of historical data to fetch (60 days = 360 bars for 4H, enough for SMA 200)
DATA_TIMEFRAME = '4H'            # Primary bar timeframe for main analysis (4H = less noise, stronger signals)
SAVE_OHLCV_DATA = False          # True = save data permanently, False = temp data only

# Multi-Timeframe Analysis
USE_MULTI_TIMEFRAME = False      # Set True to analyze multiple timeframes
MTF_TIMEFRAMES = ['1H', '4H']    # 1H = Entry timing, 4H = Main trend analysis
                                 # HyperLiquid supports: 1m, 5m, 15m, 1h, 4h, 1d

# 📊 INDICATOR TOGGLES - Enable/Disable indicators for AI analysis
INDICATORS = {
    # Core Indicators
    "rsi": True,              # RSI (14) - Overbought/Oversold
    "sma_20": True,           # SMA 20 - Short-term trend
    "sma_50": True,           # SMA 50 - Medium-term trend
    "sma_200": True,          # SMA 200 - Long-term trend
    "macd": True,             # MACD - Momentum
    "bollinger": True,        # Bollinger Bands - Volatility
    "volume": True,           # Volume
    # Additional Indicators
    "atr": True,              # ATR - Volatility/Stop placement
    "stochastic": True,       # Stochastic - Overbought/Oversold
    "adx": True,              # ADX - Trend strength
    "cci": True,              # CCI - Trend/Reversals
    "williams_r": True,       # Williams %R - Momentum
    "obv": True,              # OBV - Volume confirmation (calculated but not shown)
    "fibonacci": True,        # Fibonacci Retracement - Support/Resistance
    # Pattern Analysis
    "golden_cross": True,     # Golden Cross / Death Cross (MA20 vs MA200)
}

# ⚡ TRADING EXECUTION SETTINGS
slippage = 199                   # Slippage tolerance (199 = ~2%)
SLEEP_BETWEEN_RUNS_MINUTES = 30  # Minutes between trading cycles

# 🔄 REVERSAL SIGNAL TRACKING (tracks consecutive reversal signals per token)
# Format: {"BTC": {"direction": "SHORT", "count": 2, "last_confidence": 75}, ...}
reversal_signals = {}

# 🔄 SCAN INTERVAL PRESETS
# Each preset has: (scan_minutes, timeframe, description)
SCAN_PRESETS = {
    "scalp": (5, "15m", "Scalping - High volatility, quick entries/exits"),
    "active": (15, "1H", "Active Trading - Moderate volatility, intraday moves"),
    "standard": (30, "1H", "Standard - Normal conditions, balanced approach"),
    "swing": (60, "4H", "Swing Trading - Lower volatility, bigger moves"),
    "patient": (120, "4H", "Patient - Calm markets, wait for clear setups"),
}
CURRENT_SCAN_PRESET = "standard"  # Default preset

# 🤖 AUTO-ADJUST SCAN INTERVAL
AUTO_ADJUST_INTERVAL = True      # Auto-switch based on volatility
VOLATILITY_THRESHOLDS = {
    "high": 3.0,    # ATR% > 3.0 = high volatility → faster scans (scalp/active)
    "medium": 1.5,  # ATR% 1.5-3.0 = medium → standard scans
    "low": 1.5,     # ATR% < 1.5 = low volatility → slower scans (swing/patient)
}

# 🎯 TOKEN CONFIGURATION

# For SOLANA exchange: Use contract addresses
USDC_ADDRESS = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # Never trade
SOL_ADDRESS = "So11111111111111111111111111111111111111111"   # Never trade
EXCLUDED_TOKENS = [USDC_ADDRESS, SOL_ADDRESS]

# ⚠️ IMPORTANT: The swarm will analyze ALL tokens in this list (one at a time)
# Each token takes ~45-60 seconds in swarm mode
# Comment out tokens you don't want to trade (add # at start of line)
MONITORED_TOKENS = [
    '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump',    # 🌬️ FART (DISABLED)
    #'DitHyRMQiSDhn5cnKMJV2CDDt6sVct96YrECiM49pump',   # 🏠 housecoin (ACTIVE)
]

# For ASTER/HYPERLIQUID exchanges: Use trading symbols
# ⚠️ IMPORTANT: Only used when EXCHANGE = "ASTER" or "HYPERLIQUID"
# Toggle coins on/off for analysis - True = enabled, False = disabled
SYMBOLS_CONFIG = {
    # Active coins only
    'BTC': True,       # Bitcoin
    'DOGE': True,      # Dogecoin
    'XRP': True,       # Ripple
    'kPEPE': True,     # Pepe (1000 PEPE on HyperLiquid)
}

# Active symbols list (auto-generated from SYMBOLS_CONFIG)
SYMBOLS = [sym for sym, enabled in SYMBOLS_CONFIG.items() if enabled]

# Example: To trade multiple tokens, uncomment the ones you want:
# MONITORED_TOKENS = [
#     '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump',    # FART
#     'DitHyRMQiSDhn5cnKMJV2CDDt6sVct96YrECiM49pump',   # housecoin
#     'YourTokenAddressHere',                              # Your token
# ]

# ============================================================================
# END CONFIGURATION - CODE BELOW
# ============================================================================

# 🎛️ DYNAMIC SETTINGS LOADER
import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "dashboard_settings.json"

def get_min_confidence():
    """Read min confidence from dashboard settings file (allows live updates)"""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                return settings.get('min_confidence', MIN_CONFIDENCE_TO_TRADE)
    except Exception as e:
        print(f"⚠️ Could not read settings file: {e}")
    return MIN_CONFIDENCE_TO_TRADE

TRADE_ANALYSIS_FILE = Path(__file__).parent.parent / "data" / "trade_analysis.json"

def save_trade_analysis(symbol, action, confidence, entry_price, reasoning):
    """Save trade analysis to file for dashboard display"""
    try:
        from datetime import datetime

        # Load existing trades
        trades = []
        if TRADE_ANALYSIS_FILE.exists():
            with open(TRADE_ANALYSIS_FILE, 'r') as f:
                data = json.load(f)
                trades = data.get('trades', [])

        # Add new trade (limit to last 10)
        trades.insert(0, {
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "entry_price": round(entry_price, 2) if entry_price else 0,
            "reasoning": reasoning[:500] if reasoning else "No analysis available",  # Truncate long analysis
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        trades = trades[:10]  # Keep only last 10 trades

        # Save
        with open(TRADE_ANALYSIS_FILE, 'w') as f:
            json.dump({"trades": trades}, f, indent=4)

        print(f"📝 Trade analysis saved for {symbol}")
    except Exception as e:
        print(f"⚠️ Could not save trade analysis: {e}")

# Analysis reports file for dashboard watchlist
ANALYSIS_REPORTS_FILE = Path(__file__).parent.parent / "data" / "analysis_reports.json"

# Trading goals file
TRADING_GOALS_FILE = Path(__file__).parent.parent / "data" / "trading_goals.json"

def load_trading_goals():
    """Load trading goals from JSON file"""
    try:
        if TRADING_GOALS_FILE.exists():
            with open(TRADING_GOALS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not load trading goals: {e}")
    return {}

def get_goals_context():
    """Format trading goals for AI prompt context"""
    goals = load_trading_goals()
    if not goals:
        return ""

    context = "\n\nTRADING GOALS (User-defined objectives to consider):\n"
    if goals.get('daily_profit_target'):
        context += f"- Daily profit target: ${goals['daily_profit_target']}\n"
    if goals.get('weekly_profit_target'):
        context += f"- Weekly profit target: ${goals['weekly_profit_target']}\n"
    if goals.get('max_daily_loss'):
        context += f"- Maximum daily loss limit: ${goals['max_daily_loss']}\n"
    if goals.get('target_account_balance'):
        context += f"- Target account balance: ${goals['target_account_balance']}\n"
    if goals.get('risk_per_trade_percent'):
        context += f"- Risk per trade: {goals['risk_per_trade_percent']}%\n"
    if goals.get('preferred_strategy'):
        strategy = goals['preferred_strategy']
        if strategy == 'conservative':
            context += "- Strategy: CONSERVATIVE (prioritize capital preservation, fewer trades, higher confidence required)\n"
        elif strategy == 'moderate':
            context += "- Strategy: MODERATE (balanced approach between risk and reward)\n"
        elif strategy == 'aggressive':
            context += "- Strategy: AGGRESSIVE (accept higher risk for higher potential gains)\n"
    if goals.get('custom_goal'):
        context += f"- Custom goal: {goals['custom_goal']}\n"

    return context

# ============================================================================
# 🛑 DAILY DRAWDOWN CIRCUIT BREAKER
# ============================================================================

DRAWDOWN_STATE_FILE = Path(__file__).parent.parent / "data" / "drawdown_state.json"

def load_drawdown_state():
    """Load daily drawdown state from file"""
    try:
        if DRAWDOWN_STATE_FILE.exists():
            with open(DRAWDOWN_STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not load drawdown state: {e}")
    return {}

def save_drawdown_state(state):
    """Save daily drawdown state to file"""
    try:
        with open(DRAWDOWN_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save drawdown state: {e}")

def get_current_balance():
    """Get current account balance for drawdown calculation"""
    try:
        if EXCHANGE == "HYPERLIQUID":
            import eth_account
            from hyperliquid.info import Info
            from hyperliquid.utils import constants
            import os

            secret_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
            if not secret_key:
                return None

            account = eth_account.Account.from_key(secret_key)
            info = Info(constants.MAINNET_API_URL, skip_ws=True)
            user_state = info.user_state(account.address)
            return float(user_state.get('marginSummary', {}).get('accountValue', 0))
        else:
            # For other exchanges, implement as needed
            return None
    except Exception as e:
        print(f"⚠️ Could not get balance for drawdown check: {e}")
        return None

def check_daily_drawdown():
    """
    Check if daily drawdown limit has been reached.

    Returns:
        dict: {
            'trading_allowed': bool,
            'daily_pnl': float,
            'daily_pnl_pct': float,
            'limit': float,
            'limit_pct': float,
            'warning': bool,
            'circuit_breaker_triggered': bool,
            'starting_balance': float,
            'current_balance': float,
            'message': str
        }
    """
    from datetime import datetime, date

    result = {
        'trading_allowed': True,
        'daily_pnl': 0,
        'daily_pnl_pct': 0,
        'limit': DAILY_DRAWDOWN_LIMIT_USD,
        'limit_pct': DAILY_DRAWDOWN_LIMIT_PCT,
        'warning': False,
        'circuit_breaker_triggered': False,
        'starting_balance': 0,
        'current_balance': 0,
        'message': ''
    }

    if not DAILY_DRAWDOWN_ENABLED:
        result['message'] = 'Daily drawdown protection disabled'
        return result

    # Get current balance
    current_balance = get_current_balance()
    if current_balance is None:
        result['message'] = 'Could not get current balance'
        return result

    result['current_balance'] = current_balance

    # Load state
    state = load_drawdown_state()
    today = date.today().isoformat()

    # Check if we need to reset for new day
    if state.get('date') != today:
        # New day - record starting balance
        state = {
            'date': today,
            'starting_balance': current_balance,
            'circuit_breaker_triggered': False,
            'triggered_at': None
        }
        save_drawdown_state(state)
        cprint(f"📅 New trading day - Starting balance: ${current_balance:,.2f}", "cyan")

    starting_balance = state.get('starting_balance', current_balance)
    result['starting_balance'] = starting_balance

    # Check if circuit breaker was already triggered today
    if state.get('circuit_breaker_triggered'):
        result['trading_allowed'] = False
        result['circuit_breaker_triggered'] = True
        result['message'] = f"🛑 Circuit breaker triggered at {state.get('triggered_at', 'unknown time')}"
        return result

    # Calculate daily P&L
    daily_pnl = current_balance - starting_balance
    daily_pnl_pct = (daily_pnl / starting_balance * 100) if starting_balance > 0 else 0

    result['daily_pnl'] = daily_pnl
    result['daily_pnl_pct'] = daily_pnl_pct

    # Determine limit based on setting
    if USE_DAILY_DRAWDOWN_PCT:
        limit_value = starting_balance * (DAILY_DRAWDOWN_LIMIT_PCT / 100)
        limit_reached = daily_pnl <= -limit_value
        warning_threshold = -limit_value * (DRAWDOWN_WARNING_PCT / 100)
    else:
        limit_value = DAILY_DRAWDOWN_LIMIT_USD
        limit_reached = daily_pnl <= -limit_value
        warning_threshold = -limit_value * (DRAWDOWN_WARNING_PCT / 100)

    # Check warning threshold
    if daily_pnl <= warning_threshold and daily_pnl > -limit_value:
        result['warning'] = True
        pct_of_limit = abs(daily_pnl / limit_value * 100)
        result['message'] = f"⚠️ WARNING: Daily loss ${abs(daily_pnl):,.2f} is {pct_of_limit:.0f}% of limit"

        # 🔔 Send warning alert (only once per threshold crossing)
        if ALERTS_AVAILABLE and pct_of_limit >= DRAWDOWN_WARNING_PCT:
            try:
                alert_drawdown_warning(daily_pnl, daily_pnl_pct, limit_value, pct_of_limit)
            except Exception as e:
                cprint(f"⚠️ Could not send drawdown warning alert: {e}", "yellow")

    # Check if limit reached
    if limit_reached:
        result['trading_allowed'] = False
        result['circuit_breaker_triggered'] = True
        result['message'] = f"🛑 CIRCUIT BREAKER: Daily loss ${abs(daily_pnl):,.2f} exceeded limit ${limit_value:,.2f}"

        # Update state
        state['circuit_breaker_triggered'] = True
        state['triggered_at'] = datetime.now().strftime("%H:%M:%S")
        save_drawdown_state(state)

        # 🔔 Send circuit breaker alert
        if ALERTS_AVAILABLE:
            try:
                alert_circuit_breaker(daily_pnl, daily_pnl_pct, limit_value, starting_balance, current_balance)
            except Exception as e:
                cprint(f"⚠️ Could not send circuit breaker alert: {e}", "yellow")

        cprint(f"\n{'='*60}", "red")
        cprint(f"🛑 DAILY DRAWDOWN CIRCUIT BREAKER TRIGGERED!", "red", attrs=['bold'])
        cprint(f"{'='*60}", "red")
        cprint(f"   Starting Balance: ${starting_balance:,.2f}", "white")
        cprint(f"   Current Balance:  ${current_balance:,.2f}", "white")
        cprint(f"   Daily P&L:        ${daily_pnl:,.2f} ({daily_pnl_pct:+.2f}%)", "red")
        cprint(f"   Limit:            ${limit_value:,.2f}", "white")
        cprint(f"\n   ⛔ NO NEW TRADES ALLOWED TODAY", "red", attrs=['bold'])
        if CLOSE_ON_DRAWDOWN:
            cprint(f"   📤 Closing all positions...", "yellow")
        cprint(f"{'='*60}\n", "red")

    return result

def reset_daily_drawdown():
    """Manually reset the daily drawdown circuit breaker (use with caution)"""
    from datetime import date

    current_balance = get_current_balance()
    if current_balance is None:
        cprint("❌ Could not get current balance to reset", "red")
        return False

    state = {
        'date': date.today().isoformat(),
        'starting_balance': current_balance,
        'circuit_breaker_triggered': False,
        'triggered_at': None
    }
    save_drawdown_state(state)
    cprint(f"✅ Daily drawdown reset - New starting balance: ${current_balance:,.2f}", "green")
    return True

def get_drawdown_status():
    """Get current drawdown status for dashboard display"""
    result = check_daily_drawdown()
    return {
        'enabled': DAILY_DRAWDOWN_ENABLED,
        'trading_allowed': result['trading_allowed'],
        'daily_pnl': result['daily_pnl'],
        'daily_pnl_pct': result['daily_pnl_pct'],
        'limit_usd': DAILY_DRAWDOWN_LIMIT_USD,
        'limit_pct': DAILY_DRAWDOWN_LIMIT_PCT,
        'use_pct': USE_DAILY_DRAWDOWN_PCT,
        'warning': result['warning'],
        'circuit_breaker_triggered': result['circuit_breaker_triggered'],
        'starting_balance': result['starting_balance'],
        'current_balance': result['current_balance'],
        'message': result['message']
    }

# ============================================================================
# 📊 ATR-BASED DYNAMIC STOPS
# ============================================================================

def calculate_atr(ohlcv_data, period=ATR_PERIOD):
    """
    Calculate Average True Range (ATR) from OHLCV data.

    Args:
        ohlcv_data: DataFrame with 'high', 'low', 'close' columns
        period: ATR period (default 14)

    Returns:
        float: Current ATR value, or None if calculation fails
    """
    try:
        import pandas as pd

        if ohlcv_data is None or len(ohlcv_data) < period + 1:
            return None

        df = ohlcv_data.copy()

        # Calculate True Range components
        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']  # Current high - current low
        df['tr2'] = abs(df['high'] - df['prev_close'])  # Current high - previous close
        df['tr3'] = abs(df['low'] - df['prev_close'])   # Current low - previous close

        # True Range is max of all three
        df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

        # ATR is the moving average of True Range
        df['atr'] = df['true_range'].rolling(window=period).mean()

        # Return the most recent ATR value
        atr_value = df['atr'].iloc[-1]

        if pd.isna(atr_value):
            return None

        return float(atr_value)

    except Exception as e:
        cprint(f"⚠️ Error calculating ATR: {e}", "yellow")
        return None


def calculate_atr_percentage(ohlcv_data, period=ATR_PERIOD):
    """
    Calculate ATR as a percentage of current price.

    Returns:
        float: ATR as percentage (e.g., 2.5 = 2.5%)
    """
    try:
        atr = calculate_atr(ohlcv_data, period)
        if atr is None:
            return None

        current_price = float(ohlcv_data['close'].iloc[-1])
        if current_price <= 0:
            return None

        atr_pct = (atr / current_price) * 100
        return atr_pct

    except Exception as e:
        cprint(f"⚠️ Error calculating ATR percentage: {e}", "yellow")
        return None


def get_atr_stop_levels(entry_price, atr_value, is_long=True, current_price=None):
    """
    Calculate ATR-based stop loss and take profit levels.

    Args:
        entry_price: Position entry price
        atr_value: Current ATR value (in price units)
        is_long: True for long positions, False for shorts
        current_price: Current market price (optional, for percentage calculation)

    Returns:
        dict: {
            'stop_loss': float,      # Stop loss price
            'take_profit': float,    # Take profit price
            'sl_distance': float,    # Distance in price units
            'tp_distance': float,    # Distance in price units
            'sl_pct': float,         # Stop loss as percentage
            'tp_pct': float,         # Take profit as percentage
            'atr': float,            # ATR value used
            'atr_pct': float,        # ATR as percentage of price
        }
    """
    if atr_value is None or atr_value <= 0:
        return None

    price_ref = current_price if current_price else entry_price

    # Calculate distances
    sl_distance = atr_value * ATR_SL_MULTIPLIER
    tp_distance = atr_value * ATR_TP_MULTIPLIER

    # Calculate percentages
    sl_pct = (sl_distance / price_ref) * 100
    tp_pct = (tp_distance / price_ref) * 100
    atr_pct = (atr_value / price_ref) * 100

    # Apply min/max constraints to stop loss percentage
    sl_pct_constrained = max(ATR_MIN_SL_PCT, min(ATR_MAX_SL_PCT, sl_pct))

    # Recalculate SL distance if constrained
    if sl_pct != sl_pct_constrained:
        sl_distance = price_ref * (sl_pct_constrained / 100)
        cprint(f"   📊 ATR SL adjusted: {sl_pct:.2f}% → {sl_pct_constrained:.2f}% (within {ATR_MIN_SL_PCT}-{ATR_MAX_SL_PCT}% bounds)", "yellow")
        sl_pct = sl_pct_constrained

    # Calculate stop/target prices based on direction
    if is_long:
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return {
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'sl_distance': sl_distance,
        'tp_distance': tp_distance,
        'sl_pct': sl_pct,
        'tp_pct': tp_pct,
        'atr': atr_value,
        'atr_pct': atr_pct,
    }


def get_atr_trailing_distance(atr_value, current_price):
    """
    Calculate ATR-based trailing stop distance.

    Args:
        atr_value: Current ATR value
        current_price: Current market price

    Returns:
        tuple: (distance_pct, distance_price) or (None, None) if calculation fails
    """
    if atr_value is None or current_price <= 0:
        return None, None

    trail_distance = atr_value * ATR_TRAILING_MULTIPLIER
    trail_pct = (trail_distance / current_price) * 100

    return trail_pct, trail_distance


def get_dynamic_stop_levels(symbol, entry_price, is_long=True, ohlcv_data=None):
    """
    Get stop loss and take profit levels - either ATR-based or fixed percentage.

    This is the main function to call for getting stop levels.

    Args:
        symbol: Trading symbol (for fetching data if needed)
        entry_price: Position entry price
        is_long: True for long positions, False for shorts
        ohlcv_data: Optional OHLCV DataFrame. If None, will try to fetch.

    Returns:
        dict: Stop levels with 'stop_loss', 'take_profit', 'sl_pct', 'tp_pct', 'method'
    """
    result = {
        'stop_loss': None,
        'take_profit': None,
        'sl_pct': STOP_LOSS_PERCENTAGE,
        'tp_pct': TAKE_PROFIT_PERCENTAGE,
        'method': 'fixed',
        'atr': None,
        'atr_pct': None,
    }

    # Calculate fixed percentage stops as fallback
    if is_long:
        result['stop_loss'] = entry_price * (1 - STOP_LOSS_PERCENTAGE / 100)
        result['take_profit'] = entry_price * (1 + TAKE_PROFIT_PERCENTAGE / 100)
    else:
        result['stop_loss'] = entry_price * (1 + STOP_LOSS_PERCENTAGE / 100)
        result['take_profit'] = entry_price * (1 - TAKE_PROFIT_PERCENTAGE / 100)

    # If ATR stops disabled, return fixed percentage
    if not USE_ATR_STOPS:
        cprint(f"   📊 Using fixed stops: SL={STOP_LOSS_PERCENTAGE}%, TP={TAKE_PROFIT_PERCENTAGE}%", "cyan")
        return result

    # Try to get OHLCV data if not provided
    if ohlcv_data is None:
        try:
            if EXCHANGE == "HYPERLIQUID":
                # get_data returns OHLCV with indicators, we need at least ATR_PERIOD + 1 bars
                ohlcv_data = n.get_data(symbol, timeframe=DATA_TIMEFRAME, bars=ATR_PERIOD + 10, add_indicators=False)
        except Exception as e:
            cprint(f"⚠️ Could not fetch OHLCV for ATR calculation: {e}", "yellow")

    if ohlcv_data is None or len(ohlcv_data) < ATR_PERIOD + 1:
        cprint(f"⚠️ Insufficient data for ATR ({len(ohlcv_data) if ohlcv_data is not None else 0} bars), using fixed stops", "yellow")
        return result

    # Calculate ATR
    atr = calculate_atr(ohlcv_data, ATR_PERIOD)
    if atr is None:
        cprint(f"⚠️ ATR calculation failed, using fixed stops", "yellow")
        return result

    # Get ATR-based levels
    atr_levels = get_atr_stop_levels(entry_price, atr, is_long, entry_price)
    if atr_levels is None:
        return result

    # Update result with ATR-based values
    result.update({
        'stop_loss': atr_levels['stop_loss'],
        'take_profit': atr_levels['take_profit'],
        'sl_pct': atr_levels['sl_pct'],
        'tp_pct': atr_levels['tp_pct'],
        'method': 'atr',
        'atr': atr_levels['atr'],
        'atr_pct': atr_levels['atr_pct'],
    })

    cprint(f"\n   📊 ATR-BASED DYNAMIC STOPS:", "cyan", attrs=['bold'])
    cprint(f"      ATR({ATR_PERIOD}): ${atr:.4f} ({atr_levels['atr_pct']:.2f}% of price)", "white")
    cprint(f"      Stop Loss: ${atr_levels['stop_loss']:.4f} (-{atr_levels['sl_pct']:.2f}%) [ATR × {ATR_SL_MULTIPLIER}]", "yellow")
    cprint(f"      Take Profit: ${atr_levels['take_profit']:.4f} (+{atr_levels['tp_pct']:.2f}%) [ATR × {ATR_TP_MULTIPLIER}]", "green")
    cprint(f"      Risk:Reward = 1:{ATR_TP_MULTIPLIER/ATR_SL_MULTIPLIER:.1f}", "white")

    return result


def parse_tpsl_recommendations(reasoning):
    """Parse TP/SL recommendations from AI analysis text"""
    import re
    recommendations = {}

    if not reasoning:
        return recommendations

    # Look for TP_SL_RECOMMENDATIONS section
    # Pattern: CONSERVATIVE: TP=$X.XX (+X%), SL=$X.XX (-X%)
    patterns = {
        'conservative': r'CONSERVATIVE[:\s]+TP=\$?([\d.]+)[^,]*,\s*SL=\$?([\d.]+)',
        'moderate': r'MODERATE[:\s]+TP=\$?([\d.]+)[^,]*,\s*SL=\$?([\d.]+)',
        'aggressive': r'AGGRESSIVE[:\s]+TP=\$?([\d.]+)[^,]*,\s*SL=\$?([\d.]+)',
    }

    for level, pattern in patterns.items():
        match = re.search(pattern, reasoning, re.IGNORECASE)
        if match:
            try:
                recommendations[level] = {
                    'tp': float(match.group(1)),
                    'sl': float(match.group(2))
                }
            except (ValueError, IndexError):
                pass

    return recommendations


def save_analysis_report(symbol, action, confidence, reasoning):
    """Save analysis report for dashboard watchlist display"""
    try:
        from datetime import datetime

        # Load existing reports
        reports = {}
        if ANALYSIS_REPORTS_FILE.exists():
            with open(ANALYSIS_REPORTS_FILE, 'r') as f:
                reports = json.load(f)

        # Parse TP/SL recommendations from reasoning
        tpsl_recommendations = parse_tpsl_recommendations(reasoning)

        # Update/add report for this symbol
        reports[symbol] = {
            "action": action,
            "confidence": confidence,
            "analysis": reasoning[:1500] if reasoning else "No analysis available",
            "tpsl_recommendations": tpsl_recommendations,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Save
        with open(ANALYSIS_REPORTS_FILE, 'w') as f:
            json.dump(reports, f, indent=4)

        # Auto TP/SL if enabled
        if tpsl_recommendations and action == "BUY":
            auto_set_tpsl_from_analysis(symbol, tpsl_recommendations)

    except Exception as e:
        print(f"⚠️ Could not save analysis report: {e}")


def auto_set_tpsl_from_analysis(symbol, recommendations, ohlcv_data=None):
    """Automatically set TP/SL based on AI analysis recommendations or ATR."""
    try:
        # Load auto TP/SL settings
        settings_file = Path(__file__).parent.parent / "data" / "dashboard_settings.json"
        if not settings_file.exists():
            return

        with open(settings_file, 'r') as f:
            settings = json.load(f)

        if not settings.get("auto_tpsl_enabled", False):
            return

        mode = settings.get("auto_tpsl_mode", "moderate")
        max_sl_pct = settings.get("auto_tpsl_max_sl", 7)
        use_atr = settings.get("auto_tpsl_use_atr", USE_ATR_STOPS)  # Use ATR if enabled

        # Check if we have a position first
        import eth_account
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
        from dotenv import load_dotenv
        import os

        load_dotenv()
        secret_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
        if not secret_key:
            return

        account = eth_account.Account.from_key(secret_key)
        info = Info(constants.MAINNET_API_URL, skip_ws=True)

        # Get position
        user_state = info.user_state(account.address)
        position = None
        for pos in user_state.get('assetPositions', []):
            p = pos.get('position', {})
            if p.get('coin') == symbol and float(p.get('szi', 0)) != 0:
                position = p
                break

        if not position:
            cprint(f"   ℹ️ No position for {symbol}, skipping auto TP/SL", "white")
            return

        entry_price = float(position.get('entryPx', 0))
        size = float(position.get('szi', 0))
        is_long = size > 0

        # Determine TP/SL prices - use ATR if enabled, otherwise use AI recommendations
        if use_atr and USE_ATR_STOPS:
            # Use ATR-based dynamic stops
            cprint(f"\n   📊 Using ATR-based dynamic stops for {symbol}...", "cyan")
            stop_levels = get_dynamic_stop_levels(symbol, entry_price, is_long, ohlcv_data)

            if stop_levels['method'] == 'atr':
                tp_price = stop_levels['take_profit']
                sl_price = stop_levels['stop_loss']
                sl_pct_from_entry = stop_levels['sl_pct']
                cprint(f"      ATR Method: SL={sl_pct_from_entry:.2f}%, TP={stop_levels['tp_pct']:.2f}%", "white")
            else:
                # ATR calculation failed, fall back to AI recommendations
                cprint(f"   ⚠️ ATR calculation failed, using AI recommendations", "yellow")
                use_atr = False

        if not use_atr:
            # Use AI recommendations
            if mode not in recommendations:
                mode = next(iter(recommendations.keys()), None)
                if not mode:
                    cprint(f"   ⚠️ No TP/SL recommendations available for {symbol}", "yellow")
                    return

            rec = recommendations[mode]
            tp_price = rec.get('tp')
            sl_price = rec.get('sl')

            if not tp_price or not sl_price:
                return

            # Calculate SL percentage from entry
            if is_long:
                sl_pct_from_entry = ((entry_price - sl_price) / entry_price) * 100
            else:
                sl_pct_from_entry = ((sl_price - entry_price) / entry_price) * 100

        # Enforce max SL limit
        if sl_pct_from_entry > max_sl_pct:
            cprint(f"   ⚠️ Recommended SL ({sl_pct_from_entry:.1f}%) exceeds max ({max_sl_pct}%), adjusting...", "yellow")
            if is_long:
                sl_price = entry_price * (1 - max_sl_pct / 100)
            else:
                sl_price = entry_price * (1 + max_sl_pct / 100)

        # Set TP/SL (n is already imported at module level)
        method_display = "ATR-based" if (use_atr and USE_ATR_STOPS) else f"{mode} mode"
        cprint(f"\n🎯 Auto TP/SL for {symbol} ({method_display})", "cyan", attrs=['bold'])

        # Calculate percentages for display
        if is_long:
            tp_pct = ((tp_price - entry_price) / entry_price) * 100
            sl_pct = ((entry_price - sl_price) / entry_price) * 100
        else:
            tp_pct = ((entry_price - tp_price) / entry_price) * 100
            sl_pct = ((sl_price - entry_price) / entry_price) * 100

        result = n.place_tp_sl_orders(symbol, entry_price, abs(size), is_long, tp_pct, sl_pct, account)
        cprint(f"   ✅ Auto TP/SL set: TP=${tp_price:.6f} (+{tp_pct:.1f}%), SL=${sl_price:.6f} (-{sl_pct:.1f}%)", "green")

    except Exception as e:
        cprint(f"   ❌ Auto TP/SL error: {e}", "red")


def play_trade_sound(sound_type="open", pnl=None):
    """Play audible notification for trade events"""
    try:
        import subprocess
        import platform

        if platform.system() == "Darwin":  # macOS
            if sound_type == "open":
                # Play a pleasant chime for position opened
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.Popen(["say", "-v", "Samantha", "Position opened"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sound_type == "close_profit":
                # Winning trade - happy sound!
                subprocess.Popen(["afplay", "/System/Library/Sounds/Hero.aiff"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if pnl:
                    subprocess.Popen(["say", "-v", "Samantha", f"Winner! Made {abs(pnl):.0f} dollars"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["say", "-v", "Samantha", "Position closed with profit"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sound_type == "close_loss":
                # Losing trade - somber sound
                subprocess.Popen(["afplay", "/System/Library/Sounds/Basso.aiff"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if pnl:
                    subprocess.Popen(["say", "-v", "Samantha", f"Loss of {abs(pnl):.0f} dollars"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["say", "-v", "Samantha", "Position closed with loss"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sound_type == "alert":
                subprocess.Popen(["afplay", "/System/Library/Sounds/Ping.aiff"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif platform.system() == "Linux":  # Raspberry Pi / Linux
            try:
                subprocess.Popen(["aplay", "-q", "/usr/share/sounds/alsa/Front_Center.wav"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass
    except Exception as e:
        pass  # Silently fail if sound can't play

# Keep only these prompts
TRADING_PROMPT = """
You are Moon Dev's AI Trading Assistant 🌙

Analyze the provided market data and strategy signals (if available) to make a trading decision.

Market Data Criteria:
1. Price action relative to MA20 and MA40
2. RSI levels and trend
3. Volume patterns
4. Recent price movements

{strategy_context}

Respond in this exact format:
1. First line must be one of: BUY, SELL, or NOTHING (in caps)
2. Then explain your reasoning, including:
   - Technical analysis
   - Strategy signals analysis (if available)
   - Risk factors
   - Market conditions
   - Confidence level (as a percentage, e.g. 75%)

3. REQUIRED: Provide TP/SL recommendations based on technical levels:
   TP_SL_RECOMMENDATIONS:
   CONSERVATIVE: TP=$X.XX (+X%), SL=$X.XX (-X%)
   MODERATE: TP=$X.XX (+X%), SL=$X.XX (-X%)
   AGGRESSIVE: TP=$X.XX (+X%), SL=$X.XX (-X%)

   Base these on:
   - Support levels (SMA20, SMA50, SMA200, Fibonacci retracements)
   - Resistance levels (recent highs, Bollinger upper band)
   - ATR for volatility-adjusted stops (recommended: SL = 2×ATR, TP = 3×ATR)
   - Recent swing highs/lows

4. ATR-BASED STOP GUIDANCE:
   - If ATR is HIGH (>3% of price): Use WIDER stops to avoid noise
   - If ATR is LOW (<1.5% of price): Use TIGHTER stops for protection
   - Minimum SL: 1% | Maximum SL: 7% (regardless of ATR)
   - Risk:Reward should be at least 1:1.5

Remember:
- Moon Dev always prioritizes risk management! 🛡️
- Never trade USDC or SOL directly
- Consider both technical and strategy signals
"""

ALLOCATION_PROMPT = """
You are Moon Dev's Portfolio Allocation Assistant 🌙

Given the total portfolio size and trading recommendations, allocate capital efficiently.
Consider:
1. Position sizing based on confidence levels
2. Risk distribution
3. Keep cash buffer as specified
4. Maximum allocation per position

Format your response as a Python dictionary:
{
    "token_address": allocated_amount,  # In USD
    ...
    "USDC_ADDRESS": remaining_cash  # Always use USDC_ADDRESS for cash
}

Remember:
- Total allocations must not exceed total_size
- Higher confidence should get larger allocations
- Never allocate more than {MAX_POSITION_PERCENTAGE}% to a single position
- Keep at least {CASH_PERCENTAGE}% in USDC as safety buffer
- Only allocate to BUY recommendations
- Cash must be stored as USDC using USDC_ADDRESS: {USDC_ADDRESS}
"""

SWARM_TRADING_PROMPT = """You are an expert cryptocurrency trading AI analyzing market data.

CRITICAL RULES:
1. Your response MUST be EXACTLY one of these three words: Buy, Sell, or Do Nothing
2. Do NOT provide any explanation, reasoning, or additional text
3. Respond with ONLY the action word
4. Do NOT show your thinking process or internal reasoning

Analyze the market data below and decide:

- "Buy" = Strong bullish signals, recommend opening/holding position
- "Sell" = Bearish signals or major weakness, recommend closing position entirely
- "Do Nothing" = Unclear/neutral signals, recommend holding current state unchanged

IMPORTANT: "Do Nothing" means maintain current position (if we have one, keep it; if we don't, stay out)

RESPOND WITH ONLY ONE WORD: Buy, Sell, or Do Nothing"""

import os
import sys
import pandas as pd
import json
from termcolor import cprint

# Add project root to path for imports
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Import alerts module
try:
    from src.alerts import (
        alert_position_opened, alert_position_closed,
        alert_stop_loss_hit, alert_take_profit_hit,
        alert_trailing_stop_hit, alert_drawdown_warning,
        alert_circuit_breaker, alert_critical_error
    )
    ALERTS_AVAILABLE = True
except ImportError:
    ALERTS_AVAILABLE = False
    cprint("⚠️ Alerts module not available", "yellow")
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time
from pathlib import Path

# Add project root to path for imports
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Local imports - trading_agent.py is now fully self-contained!
# No config.py imports needed - all settings are at the top of this file (lines 55-111)

# Dynamic exchange imports based on EXCHANGE selection
if EXCHANGE == "ASTER":
    from src import nice_funcs_aster as n
    cprint("🏦 Exchange: Aster DEX (Futures)", "cyan", attrs=['bold'])
elif EXCHANGE == "HYPERLIQUID":
    from src import nice_funcs_hyperliquid as n
    cprint("🏦 Exchange: HyperLiquid (Perpetuals)", "cyan", attrs=['bold'])
elif EXCHANGE == "SOLANA":
    from src import nice_funcs as n
    cprint("🏦 Exchange: Solana (On-chain DEX)", "cyan", attrs=['bold'])
else:
    cprint(f"❌ Unknown exchange: {EXCHANGE}", "red")
    cprint("Available exchanges: ASTER, HYPERLIQUID, SOLANA", "yellow")
    sys.exit(1)

from src.data.ohlcv_collector import collect_all_tokens
from src.models.model_factory import model_factory
from src.agents.swarm_agent import SwarmAgent

# Load environment variables
load_dotenv()

# Initialize HyperLiquid account globally (for functions that need it)
HL_ACCOUNT = None
if EXCHANGE == "HYPERLIQUID":
    try:
        HL_ACCOUNT = n._get_account_from_env()
        cprint("✅ HyperLiquid account initialized", "green")
    except Exception as e:
        cprint(f"❌ Failed to initialize HyperLiquid account: {e}", "red")

# ============================================================================
# TRADE FILL TRACKING
# ============================================================================

TRADE_FILLS_FILE = Path(__file__).parent.parent / "data" / "trade_fills.json"

def save_trade_fill(symbol, qty, price, side="BUY"):
    """Save individual trade fill to history (shared with dashboard)"""
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
        cprint(f"📝 Trade fill saved: {qty} {symbol} @ ${price:,.2f}", "cyan")
    except Exception as e:
        cprint(f"⚠️ Error saving trade fill: {e}", "yellow")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def monitor_position_pnl(token, check_interval=PNL_CHECK_INTERVAL):
    """Monitor position P&L and exit if stop loss or take profit hit

    Args:
        token: Token symbol to monitor
        check_interval: Seconds between P&L checks

    Returns:
        bool: True if position closed, False if still open
    """
    try:
        cprint(f"\n👁️  Monitoring {token} position for P&L targets...", "cyan", attrs=['bold'])
        cprint(f"   Stop Loss: -{STOP_LOSS_PERCENTAGE}% | Take Profit: +{TAKE_PROFIT_PERCENTAGE}%", "white")
        if USE_TRAILING_STOP:
            cprint(f"   Trailing Stop: Activates at +{TRAILING_STOP_ACTIVATION}%, trails {TRAILING_STOP_DISTANCE}% behind peak", "white")

        # Trailing stop tracking
        highest_pnl = 0
        trailing_stop_active = False
        trailing_stop_level = -STOP_LOSS_PERCENTAGE  # Start at regular stop loss

        while True:
            # Get current position
            if EXCHANGE == "HYPERLIQUID":
                positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)
                if not im_in_pos:
                    cprint(f"✅ No position found for {token}", "green")
                    return True
                mid_price = n.get_current_price(token)
                position_size = abs(float(pos_size)) * mid_price
                pnl_usd = (mid_price - entry_px) * float(pos_size)  # Approximate P&L in USD
                position = {'position_amount': float(pos_size), 'mark_price': mid_price}
            elif EXCHANGE == "ASTER":
                position = n.get_position(token)
                if not position or position.get('position_amount', 0) == 0:
                    cprint(f"✅ No position found for {token}", "green")
                    return True
                pnl_pct = position.get('pnl_percentage', 0)
                pnl_usd = position.get('pnl', 0)
                position_size = abs(position.get('position_amount', 0)) * position.get('mark_price', 0)
            else:
                position_usd = n.get_token_balance_usd(token)
                if position_usd == 0:
                    cprint(f"✅ Position closed for {token}", "green")
                    return True
                position = {"position_amount": position_usd}
                pnl_pct = 0
                pnl_usd = 0
                position_size = position_usd

            # For Aster/HyperLiquid, check P&L percentage
            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:

                # Update trailing stop if enabled
                if USE_TRAILING_STOP:
                    if pnl_pct > highest_pnl:
                        highest_pnl = pnl_pct
                        # Activate trailing stop once we hit activation threshold
                        if highest_pnl >= TRAILING_STOP_ACTIVATION and not trailing_stop_active:
                            trailing_stop_active = True
                            cprint(f"🎯 TRAILING STOP ACTIVATED at {highest_pnl:.2f}% profit!", "green", attrs=['bold'])
                        # Update trailing stop level
                        if trailing_stop_active:
                            trailing_stop_level = highest_pnl - TRAILING_STOP_DISTANCE
                            cprint(f"📊 Position: ${position_size:,.2f} | P&L: {pnl_pct:+.2f}% | Peak: {highest_pnl:.2f}% | Trail Stop: {trailing_stop_level:+.2f}%", "cyan")
                        else:
                            cprint(f"📊 Position: ${position_size:,.2f} | P&L: {pnl_pct:+.2f}% | Peak: {highest_pnl:.2f}%", "cyan")
                    else:
                        if trailing_stop_active:
                            cprint(f"📊 Position: ${position_size:,.2f} | P&L: {pnl_pct:+.2f}% | Peak: {highest_pnl:.2f}% | Trail Stop: {trailing_stop_level:+.2f}%", "cyan")
                        else:
                            cprint(f"📊 Position: ${position_size:,.2f} | P&L: {pnl_pct:+.2f}%", "cyan")

                    # Check trailing stop
                    if trailing_stop_active and pnl_pct <= trailing_stop_level:
                        cprint(f"📉 TRAILING STOP HIT! P&L: {pnl_pct:.2f}% (trail stop: {trailing_stop_level:+.2f}%)", "yellow", attrs=['bold'])
                        cprint(f"💰 Locked in profit from peak of {highest_pnl:.2f}%!", "green")
                        cprint(f"🔄 Closing position...", "yellow")

                        # 🔔 Send alert
                        if ALERTS_AVAILABLE:
                            alert_trailing_stop_hit(token, pnl_usd, pnl_pct, highest_pnl)

                        # Close position
                        if position['position_amount'] > 0:
                            n.limit_sell(token, position_size, slippage=0, leverage=LEVERAGE)
                        else:
                            n.limit_buy(token, position_size, slippage=0, leverage=LEVERAGE)
                        return True
                else:
                    cprint(f"📊 Position: ${position_size:,.2f} | P&L: ${pnl_usd:,.2f} ({pnl_pct:+.2f}%)", "cyan")

                # Check stop loss
                if pnl_pct <= -STOP_LOSS_PERCENTAGE:
                    cprint(f"🛑 STOP LOSS HIT! P&L: {pnl_pct:.2f}% (target: -{STOP_LOSS_PERCENTAGE}%)", "red", attrs=['bold'])
                    cprint(f"🔄 Closing position with limit orders...", "yellow")

                    # 🔔 Send alert
                    if ALERTS_AVAILABLE:
                        mid_price = position.get('mark_price', entry_px)
                        alert_stop_loss_hit(token, pnl_usd, pnl_pct, entry_px, mid_price)

                    # Close position using limit sell (for longs) or limit buy (for shorts)
                    if position['position_amount'] > 0:
                        n.limit_sell(token, position_size, slippage=0, leverage=LEVERAGE)
                    else:
                        n.limit_buy(token, position_size, slippage=0, leverage=LEVERAGE)

                    play_trade_sound("close_loss", pnl_usd)  # 🔊 Stop loss sound
                    return True

                # Check take profit
                if pnl_pct >= TAKE_PROFIT_PERCENTAGE:
                    cprint(f"🎯 TAKE PROFIT HIT! P&L: {pnl_pct:.2f}% (target: +{TAKE_PROFIT_PERCENTAGE}%)", "green", attrs=['bold'])
                    cprint(f"🔄 Closing position with limit orders...", "yellow")

                    # 🔔 Send alert
                    if ALERTS_AVAILABLE:
                        mid_price = position.get('mark_price', entry_px)
                        alert_take_profit_hit(token, pnl_usd, pnl_pct, entry_px, mid_price)

                    # Close position using limit sell (for longs) or limit buy (for shorts)
                    if position['position_amount'] > 0:
                        n.limit_sell(token, position_size, slippage=0, leverage=LEVERAGE)
                    else:
                        n.limit_buy(token, position_size, slippage=0, leverage=LEVERAGE)

                    play_trade_sound("close_profit", pnl_usd)  # 🔊 Take profit sound
                    return True

            # Sleep before next check
            time.sleep(check_interval)

    except KeyboardInterrupt:
        cprint(f"\n⚠️  Position monitoring interrupted", "yellow")
        raise
    except Exception as e:
        cprint(f"❌ Error monitoring position: {e}", "red")
        return False


def get_account_balance():
    """Get account balance in USD based on exchange type

    Returns:
        float: Account balance in USD
    """
    try:
        if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
            # Get USD balance from futures exchange
            if EXCHANGE == "ASTER":
                balance_dict = n.get_account_balance()  # Aster returns dict
                balance = balance_dict.get('total_equity', 0)  # Use total equity for trading
                cprint(f"💰 {EXCHANGE} Total Equity: ${balance:,.2f} USD", "cyan")
                cprint(f"   Available: ${balance_dict.get('available', 0):,.2f} | Unrealized PnL: ${balance_dict.get('unrealized_pnl', 0):,.2f}", "white")
            else:  # HYPERLIQUID
                account = n._get_account_from_env()
                balance = n.get_account_value(account)  # HyperLiquid USD balance
                cprint(f"💰 {EXCHANGE} Account Balance: ${balance:,.2f} USD", "cyan")

            return balance
        else:
            # SOLANA - get USDC balance
            balance = n.get_token_balance_usd(USDC_ADDRESS)
            cprint(f"💰 SOLANA USDC Balance: ${balance:,.2f}", "cyan")
            return balance
    except Exception as e:
        cprint(f"❌ Error getting account balance: {e}", "red")
        import traceback
        traceback.print_exc()
        return 0

def calculate_position_size(account_balance, confidence=None):
    """Calculate position size based on account balance and confidence level

    Args:
        account_balance: Current account balance in USD
        confidence: AI confidence percentage (0-100). If None, uses MAX_POSITION_PERCENTAGE

    Returns:
        float: Position size in USD (notional value)
    """
    # Determine position percentage based on confidence (dynamic sizing)
    if USE_DYNAMIC_SIZING and confidence is not None:
        # Scale position size linearly between MIN and MAX based on confidence
        # At MIN_CONFIDENCE_TO_TRADE -> DYNAMIC_SIZE_MIN_PCT
        # At 100% confidence -> DYNAMIC_SIZE_MAX_PCT
        min_conf = get_min_confidence()
        confidence_range = 100 - min_conf  # e.g., 100 - 70 = 30
        confidence_above_min = confidence - min_conf  # e.g., 85 - 70 = 15
        confidence_ratio = max(0, min(1, confidence_above_min / confidence_range))  # 0 to 1

        position_pct = DYNAMIC_SIZE_MIN_PCT + (DYNAMIC_SIZE_MAX_PCT - DYNAMIC_SIZE_MIN_PCT) * confidence_ratio
        sizing_mode = "DYNAMIC"
    else:
        position_pct = MAX_POSITION_PERCENTAGE
        sizing_mode = "FIXED"

    if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
        # For leveraged exchanges: position_pct is the MARGIN to use
        # Notional position = margin × leverage
        margin_to_use = account_balance * (position_pct / 100)
        notional_position = margin_to_use * LEVERAGE

        cprint(f"\n📊 Position Calculation ({EXCHANGE} - {sizing_mode}):", "yellow", attrs=['bold'])
        cprint(f"   💵 Account Balance: ${account_balance:,.2f}", "white")
        if USE_DYNAMIC_SIZING and confidence is not None:
            cprint(f"   🎯 AI Confidence: {confidence}%", "magenta", attrs=['bold'])
            cprint(f"   📈 Dynamic Size: {position_pct:.1f}% (range: {DYNAMIC_SIZE_MIN_PCT}-{DYNAMIC_SIZE_MAX_PCT}%)", "magenta")
        else:
            cprint(f"   📈 Position %: {position_pct}%", "white")
        cprint(f"   💰 Margin to Use: ${margin_to_use:,.2f}", "green", attrs=['bold'])
        cprint(f"   ⚡ Leverage: {LEVERAGE}x", "white")
        cprint(f"   💎 Notional Position: ${notional_position:,.2f}", "cyan", attrs=['bold'])

        return notional_position
    else:
        # For Solana: No leverage, direct position size
        position_size = account_balance * (position_pct / 100)

        cprint(f"\n📊 Position Calculation (SOLANA - {sizing_mode}):", "yellow", attrs=['bold'])
        cprint(f"   💵 USDC Balance: ${account_balance:,.2f}", "white")
        if USE_DYNAMIC_SIZING and confidence is not None:
            cprint(f"   🎯 AI Confidence: {confidence}%", "magenta", attrs=['bold'])
            cprint(f"   📈 Dynamic Size: {position_pct:.1f}%", "magenta")
        else:
            cprint(f"   📈 Position %: {position_pct}%", "white")
        cprint(f"   💎 Position Size: ${position_size:,.2f}", "cyan", attrs=['bold'])

        return position_size

# ============================================================================
# TRADING AGENT CLASS
# ============================================================================

class TradingAgent:
    def __init__(self):
        # Check if using swarm mode or single model
        if USE_SWARM_MODE:
            cprint(f"\n🌊 Initializing Trading Agent in SWARM MODE (6 AI consensus)...", "cyan", attrs=['bold'])
            self.swarm = SwarmAgent()
            cprint("✅ Swarm mode initialized with 6 AI models!", "green")

            # Still need a lightweight model for portfolio allocation (not trading decisions)
            cprint("💼 Initializing fast model for portfolio calculations...", "cyan")
            self.model = model_factory.get_model(AI_MODEL_TYPE, AI_MODEL_NAME)
            if self.model:
                cprint(f"✅ Allocation model ready: {self.model.model_name}", "green")
        else:
            # Initialize AI model via model factory (original behavior)
            cprint(f"\n🤖 Initializing Trading Agent with {AI_MODEL_TYPE} model...", "cyan")
            self.model = model_factory.get_model(AI_MODEL_TYPE, AI_MODEL_NAME)
            self.swarm = None  # Not used in single model mode

            if not self.model:
                cprint(f"❌ Failed to initialize {AI_MODEL_TYPE} model!", "red")
                cprint("Available models:", "yellow")
                for model_type in model_factory._models.keys():
                    cprint(f"  - {model_type}", "yellow")
                sys.exit(1)

            cprint(f"✅ Using model: {self.model.model_name}", "green")

        self.recommendations_df = pd.DataFrame(columns=['token', 'action', 'confidence', 'reasoning'])

        # Show which tokens will be analyzed based on exchange
        cprint("\n🎯 Active Tokens for Trading:", "yellow", attrs=['bold'])
        if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
            tokens_to_show = SYMBOLS
            cprint(f"🏦 Exchange: {EXCHANGE} (using symbols)", "cyan")
        else:
            tokens_to_show = MONITORED_TOKENS
            cprint(f"🏦 Exchange: SOLANA (using contract addresses)", "cyan")

        for i, token in enumerate(tokens_to_show, 1):
            token_display = token[:8] + "..." if len(token) > 8 else token
            cprint(f"   {i}. {token_display}", "cyan")
        cprint(f"\n⏱️  Estimated swarm analysis time: ~{len(tokens_to_show) * 60} seconds ({len(tokens_to_show)} tokens × 60s)\n", "yellow")

        # Show exchange and trading mode
        cprint(f"\n🏦 Active Exchange: {EXCHANGE}", "yellow", attrs=['bold'])

        cprint("📈 Trading Mode:", "yellow", attrs=['bold'])
        if LONG_ONLY:
            cprint("   📊 LONG ONLY - No shorting enabled", "cyan")
            cprint("   💡 SELL signals close positions, can't open shorts", "white")
        else:
            cprint("   ⚡ LONG/SHORT - Full directional trading", "green")
            cprint("   💡 SELL signals can close longs OR open shorts", "white")

        cprint("\n🤖 Moon Dev's LLM Trading Agent initialized!", "green")

    def chat_with_ai(self, system_prompt, user_content):
        """Send prompt to AI model via model factory"""
        try:
            response = self.model.generate_response(
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=AI_TEMPERATURE,
                max_tokens=AI_MAX_TOKENS
            )

            # Handle response format
            if hasattr(response, 'content'):
                return response.content
            return str(response)

        except Exception as e:
            cprint(f"❌ AI model error: {e}", "red")
            return None

    def _format_market_data_for_swarm(self, token, market_data):
        """Format market data into a clean, readable format for swarm analysis"""
        try:
            # Print market data visibility for confirmation
            cprint(f"\n📊 MARKET DATA RECEIVED FOR {token[:8]}...", "cyan", attrs=['bold'])

            # Check if market_data is a DataFrame
            if isinstance(market_data, pd.DataFrame):
                cprint(f"✅ DataFrame received: {len(market_data)} bars", "green")
                cprint(f"📅 Date range: {market_data.index[0]} to {market_data.index[-1]}", "yellow")
                cprint(f"🕐 Timeframe: {DATA_TIMEFRAME}", "yellow")
                cprint(f"📊 Columns: {list(market_data.columns)}", "yellow")

                # Show the first 5 bars
                cprint("\n📈 First 5 Bars (OHLCV):", "cyan")
                print(market_data.head().to_string())

                # Show the last 3 bars
                cprint("\n📉 Last 3 Bars (Most Recent):", "cyan")
                print(market_data.tail(3).to_string())

                # Select key columns for AI analysis (prevent truncation)
                key_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                indicator_cols = ['sma_20', 'sma_50', 'sma_200', 'rsi', 'MACD_12_26_9', 'MACDs_12_26_9', 'BBL_5_2.0', 'BBM_5_2.0', 'BBU_5_2.0']

                # Get available columns
                available_cols = [c for c in key_cols + indicator_cols if c in market_data.columns]
                data_subset = market_data[available_cols].copy()

                # Get latest values for summary
                latest = market_data.iloc[-1]
                rsi_val = latest.get('rsi', None)
                sma20_val = latest.get('sma_20', None)
                sma50_val = latest.get('sma_50', None)
                sma200_val = latest.get('sma_200', None)
                close_val = latest.get('close', None)

                # Detect Golden Cross / Death Cross (MA20 crossing MA200)
                def detect_ma_crossover(df):
                    """Detect if MA20 recently crossed MA200"""
                    if 'sma_20' not in df.columns or 'sma_200' not in df.columns:
                        return "N/A - MA200 not available"

                    # Get last 5 bars to detect recent crossover
                    recent = df.tail(5).copy()
                    recent = recent.dropna(subset=['sma_20', 'sma_200'])

                    if len(recent) < 2:
                        return "N/A - Not enough data"

                    # Check current position
                    current_above = recent['sma_20'].iloc[-1] > recent['sma_200'].iloc[-1]

                    # Check for crossover in last 5 bars
                    for i in range(len(recent) - 1):
                        prev_above = recent['sma_20'].iloc[i] > recent['sma_200'].iloc[i]
                        next_above = recent['sma_20'].iloc[i + 1] > recent['sma_200'].iloc[i + 1]

                        if not prev_above and next_above:
                            return "🟢 GOLDEN CROSS DETECTED (MA20 crossed ABOVE MA200) - STRONG BUY SIGNAL"
                        elif prev_above and not next_above:
                            return "🔴 DEATH CROSS DETECTED (MA20 crossed BELOW MA200) - STRONG SELL SIGNAL"

                    # No crossover, report current position
                    if current_above:
                        return "MA20 ABOVE MA200 (Bullish trend)"
                    else:
                        return "MA20 BELOW MA200 (Bearish trend)"

                crossover_signal = detect_ma_crossover(market_data)

                # Format values safely
                def fmt_price(v):
                    return f"${v:,.2f}" if isinstance(v, (int, float)) and not pd.isna(v) else "N/A"
                def fmt_rsi(v):
                    if isinstance(v, (int, float)) and not pd.isna(v):
                        label = " (OVERSOLD)" if v < 30 else " (OVERBOUGHT)" if v > 70 else ""
                        return f"{v:.1f}{label}"
                    return "N/A"
                def fmt_sma(sma, price):
                    if isinstance(sma, (int, float)) and isinstance(price, (int, float)) and not pd.isna(sma) and not pd.isna(price):
                        label = " (Price ABOVE)" if price > sma else " (Price BELOW)"
                        return f"${sma:,.2f}{label}"
                    return "N/A"

                # Get MACD and BB values
                macd_val = latest.get('MACD_12_26_9', None)
                macd_signal = latest.get('MACDs_12_26_9', None)
                bb_upper = latest.get('BBU_5_2.0', latest.get('BBU_5_2.0_2.0', None))
                bb_lower = latest.get('BBL_5_2.0', latest.get('BBL_5_2.0_2.0', None))

                def fmt_macd(m, s):
                    if isinstance(m, (int, float)) and isinstance(s, (int, float)) and not pd.isna(m) and not pd.isna(s):
                        signal = "BULLISH" if m > s else "BEARISH"
                        return f"{m:.6f} (Signal: {s:.6f}) - {signal}"
                    return "N/A"

                def fmt_bb(upper, lower, price):
                    if all(isinstance(x, (int, float)) and not pd.isna(x) for x in [upper, lower, price]):
                        if price > upper:
                            return f"${upper:,.2f} / ${lower:,.2f} - Price ABOVE upper band (OVERBOUGHT)"
                        elif price < lower:
                            return f"${upper:,.2f} / ${lower:,.2f} - Price BELOW lower band (OVERSOLD)"
                        else:
                            return f"${upper:,.2f} / ${lower:,.2f} - Price within bands"
                    return "N/A"

                # Format for AI with explicit indicator summary (compact version)
                # Build column list for recent price action (include sma_200 if available)
                price_action_cols = ['timestamp', 'close', 'volume', 'rsi', 'sma_20', 'sma_50']
                if 'sma_200' in data_subset.columns:
                    price_action_cols.append('sma_200')

                # Get additional indicators
                atr_val = latest.get('atr', None)
                stoch_k = latest.get('STOCHk_14_3_3', None)
                stoch_d = latest.get('STOCHd_14_3_3', None)
                adx_val = latest.get('ADX_14', None)
                cci_val = latest.get('cci', None)
                willr_val = latest.get('willr', None)

                # Get Fibonacci levels
                fib_high = latest.get('fib_high', None)
                fib_low = latest.get('fib_low', None)
                fib_236 = latest.get('fib_236', None)
                fib_382 = latest.get('fib_382', None)
                fib_500 = latest.get('fib_500', None)
                fib_618 = latest.get('fib_618', None)
                fib_786 = latest.get('fib_786', None)

                def fmt_stoch(k, d):
                    if isinstance(k, (int, float)) and isinstance(d, (int, float)) and not pd.isna(k) and not pd.isna(d):
                        signal = "OVERBOUGHT" if k > 80 else "OVERSOLD" if k < 20 else "NEUTRAL"
                        return f"K:{k:.1f} D:{d:.1f} - {signal}"
                    return "N/A"

                def fmt_adx(v):
                    if isinstance(v, (int, float)) and not pd.isna(v):
                        strength = "STRONG TREND" if v > 25 else "WEAK/NO TREND"
                        return f"{v:.1f} - {strength}"
                    return "N/A"

                # Multi-timeframe summary
                mtf_summary = ""
                if USE_MULTI_TIMEFRAME:
                    mtf_summary = "\n=== MULTI-TIMEFRAME ANALYSIS ===\n"
                    for tf in MTF_TIMEFRAMES:
                        if tf != DATA_TIMEFRAME:
                            try:
                                tf_data = n.get_data(token, timeframe=tf, bars=50, add_indicators=True)
                                if not tf_data.empty:
                                    tf_latest = tf_data.iloc[-1]
                                    tf_rsi = tf_latest.get('rsi', None)
                                    tf_trend = "BULLISH" if tf_latest.get('close', 0) > tf_latest.get('sma_50', 0) else "BEARISH"
                                    tf_macd = tf_latest.get('MACD_12_26_9', 0)
                                    tf_signal = tf_latest.get('MACDs_12_26_9', 0)
                                    tf_macd_bias = "BULLISH" if tf_macd > tf_signal else "BEARISH"
                                    rsi_str = f"{tf_rsi:.1f}" if tf_rsi else "N/A"
                                    mtf_summary += f"{tf}: RSI={rsi_str} | Trend={tf_trend} | MACD={tf_macd_bias}\n"
                            except Exception as mtf_err:
                                cprint(f"⚠️ Multi-timeframe {tf} error: {mtf_err}", "yellow")
                                mtf_summary += f"{tf}: Data unavailable\n"

                # Build dynamic indicator sections based on toggles
                core_indicators = f"Close Price: {fmt_price(close_val)}\n"
                if INDICATORS.get("rsi", True):
                    core_indicators += f"RSI (14): {fmt_rsi(rsi_val)}\n"
                if INDICATORS.get("sma_20", True):
                    core_indicators += f"SMA 20: {fmt_sma(sma20_val, close_val)}\n"
                if INDICATORS.get("sma_50", True):
                    core_indicators += f"SMA 50: {fmt_sma(sma50_val, close_val)}\n"
                if INDICATORS.get("sma_200", True):
                    core_indicators += f"SMA 200 (Long-term trend): {fmt_sma(sma200_val, close_val)}\n"
                if INDICATORS.get("macd", True):
                    core_indicators += f"MACD: {fmt_macd(macd_val, macd_signal)}\n"
                if INDICATORS.get("bollinger", True):
                    core_indicators += f"Bollinger Bands: {fmt_bb(bb_upper, bb_lower, close_val)}\n"
                if INDICATORS.get("volume", True):
                    core_indicators += f"Volume: {latest.get('volume', 'N/A'):,.0f}\n"

                additional_indicators = ""
                if INDICATORS.get("atr", True):
                    additional_indicators += f"ATR (Volatility): {f'${atr_val:.2f}' if atr_val and not pd.isna(atr_val) else 'N/A'}\n"
                if INDICATORS.get("stochastic", True):
                    additional_indicators += f"Stochastic: {fmt_stoch(stoch_k, stoch_d)}\n"
                if INDICATORS.get("adx", True):
                    additional_indicators += f"ADX (Trend Strength): {fmt_adx(adx_val)}\n"
                if INDICATORS.get("cci", True):
                    additional_indicators += f"CCI: {f'{cci_val:.1f}' if cci_val and not pd.isna(cci_val) else 'N/A'}\n"
                if INDICATORS.get("williams_r", True):
                    additional_indicators += f"Williams %R: {f'{willr_val:.1f}' if willr_val and not pd.isna(willr_val) else 'N/A'}\n"

                fib_section = ""
                if INDICATORS.get("fibonacci", True):
                    fib_section = f"""
=== FIBONACCI RETRACEMENT LEVELS (50-bar range) ===
Swing High: {f'${fib_high:.4f}' if fib_high and not pd.isna(fib_high) else 'N/A'}
23.6% Level: {f'${fib_236:.4f}' if fib_236 and not pd.isna(fib_236) else 'N/A'}
38.2% Level: {f'${fib_382:.4f}' if fib_382 and not pd.isna(fib_382) else 'N/A'}
50.0% Level: {f'${fib_500:.4f}' if fib_500 and not pd.isna(fib_500) else 'N/A'}
61.8% Level (Golden): {f'${fib_618:.4f}' if fib_618 and not pd.isna(fib_618) else 'N/A'}
78.6% Level: {f'${fib_786:.4f}' if fib_786 and not pd.isna(fib_786) else 'N/A'}
Swing Low: {f'${fib_low:.4f}' if fib_low and not pd.isna(fib_low) else 'N/A'}
Price vs Fib: {f'Near {fib_618:.4f} (61.8% - KEY LEVEL)' if fib_618 and close_val and abs(close_val - fib_618) / fib_618 < 0.01 else f'Near {fib_500:.4f} (50%)' if fib_500 and close_val and abs(close_val - fib_500) / fib_500 < 0.01 else f'Near {fib_382:.4f} (38.2%)' if fib_382 and close_val and abs(close_val - fib_382) / fib_382 < 0.01 else 'Between levels'}
"""

                crossover_section = ""
                if INDICATORS.get("golden_cross", True):
                    crossover_section = f"""
=== MA CROSSOVER ANALYSIS (Golden Cross / Death Cross) ===
{crossover_signal}
"""

                formatted = f"""
TOKEN: {token}
TIMEFRAME: {DATA_TIMEFRAME}
ANALYSIS TIMESTAMP: {market_data.iloc[-1].get('timestamp', 'N/A')}

=== CURRENT INDICATOR VALUES (MOST IMPORTANT) ===
{core_indicators}
=== ADDITIONAL INDICATORS ===
{additional_indicators}
{fib_section}
{crossover_section}
{mtf_summary}
=== RECENT PRICE ACTION (Last 50 bars) ===
{data_subset[[c for c in price_action_cols if c in data_subset.columns]].tail(50).to_string()}
"""
            else:
                # If it's not a DataFrame, show what we got
                cprint(f"⚠️ Market data is not a DataFrame: {type(market_data)}", "yellow")
                formatted = f"TOKEN: {token}\nMARKET DATA:\n{str(market_data)}"

            # Add strategy signals if available
            if isinstance(market_data, dict) and 'strategy_signals' in market_data:
                formatted += f"\n\nSTRATEGY SIGNALS:\n{json.dumps(market_data['strategy_signals'], indent=2)}"

            cprint("\n✅ Market data formatted and ready for swarm!\n", "green")
            return formatted

        except Exception as e:
            cprint(f"❌ Error formatting market data: {e}", "red")
            return str(market_data)

    def _calculate_swarm_consensus(self, swarm_result):
        """
        Calculate consensus from individual swarm responses

        Args:
            swarm_result: Result dict from swarm.query() containing individual responses

        Returns:
            tuple: (action, confidence, reasoning_summary)
                - action: "BUY", "SELL", or "NOTHING"
                - confidence: percentage based on vote distribution
                - reasoning_summary: Summary of all model votes
        """
        try:
            votes = {"BUY": 0, "SELL": 0, "NOTHING": 0}
            model_votes = []

            # Count votes from each model's response
            for provider, data in swarm_result["responses"].items():
                if not data["success"]:
                    continue

                response_text = data["response"].strip().upper()

                # Parse the response - look for Buy, Sell, or Do Nothing
                if "BUY" in response_text:
                    votes["BUY"] += 1
                    model_votes.append(f"{provider}: Buy")
                elif "SELL" in response_text:
                    votes["SELL"] += 1
                    model_votes.append(f"{provider}: Sell")
                else:
                    votes["NOTHING"] += 1
                    model_votes.append(f"{provider}: Do Nothing")

            # Calculate total votes
            total_votes = sum(votes.values())
            if total_votes == 0:
                return "NOTHING", 0, "No valid responses from swarm"

            # Find majority vote
            majority_action = max(votes, key=votes.get)
            majority_count = votes[majority_action]

            # Calculate confidence as percentage of votes for majority action
            confidence = int((majority_count / total_votes) * 100)

            # Create reasoning summary
            reasoning = f"Swarm Consensus ({total_votes} models voted):\n"
            reasoning += f"  Buy: {votes['BUY']} votes\n"
            reasoning += f"  Sell: {votes['SELL']} votes\n"
            reasoning += f"  Do Nothing: {votes['NOTHING']} votes\n\n"
            reasoning += "Individual votes:\n"
            reasoning += "\n".join(f"  - {vote}" for vote in model_votes)
            reasoning += f"\n\nMajority decision: {majority_action} ({confidence}% consensus)"

            cprint(f"\n🌊 Swarm Consensus: {majority_action} with {confidence}% agreement", "cyan", attrs=['bold'])

            return majority_action, confidence, reasoning

        except Exception as e:
            cprint(f"❌ Error calculating swarm consensus: {e}", "red")
            return "NOTHING", 0, f"Error calculating consensus: {str(e)}"

    def analyze_market_data(self, token, market_data):
        """Analyze market data using AI model (single or swarm mode)"""
        try:
            # Skip analysis for excluded tokens
            if token in EXCLUDED_TOKENS:
                print(f"⚠️ Skipping analysis for excluded token: {token}")
                return None

            # ============= SWARM MODE =============
            if USE_SWARM_MODE:
                cprint(f"\n🌊 Analyzing {token[:8]}... with SWARM (6 AI models voting)", "cyan", attrs=['bold'])

                # Format market data for swarm
                formatted_data = self._format_market_data_for_swarm(token, market_data)

                # Add trading goals context
                goals_context = get_goals_context()
                if goals_context:
                    formatted_data += goals_context
                    cprint("📋 Trading goals included in analysis", "cyan")

                # Query the swarm (takes ~45-60 seconds)
                swarm_result = self.swarm.query(
                    prompt=formatted_data,
                    system_prompt=SWARM_TRADING_PROMPT
                )

                if not swarm_result:
                    cprint(f"❌ No response from swarm for {token}", "red")
                    return None

                # Calculate consensus from individual model votes
                action, confidence, reasoning = self._calculate_swarm_consensus(swarm_result)

                # Add to recommendations DataFrame
                self.recommendations_df = pd.concat([
                    self.recommendations_df,
                    pd.DataFrame([{
                        'token': token,
                        'action': action,
                        'confidence': confidence,
                        'reasoning': reasoning
                    }])
                ], ignore_index=True)

                # Save analysis report for dashboard watchlist
                save_analysis_report(token, action, confidence, reasoning)

                cprint(f"✅ Swarm analysis complete for {token[:8]}!", "green")
                return swarm_result

            # ============= SINGLE MODEL MODE (Original) =============
            else:
                # Prepare strategy context
                strategy_context = ""
                if isinstance(market_data, dict) and 'strategy_signals' in market_data:
                    strategy_context = f"""
Strategy Signals Available:
{json.dumps(market_data['strategy_signals'], indent=2)}
                    """
                else:
                    strategy_context = "No strategy signals available."

                # Format market data with indicator summary (same as swarm mode)
                formatted_data = self._format_market_data_for_swarm(token, market_data)

                # Add trading goals context
                goals_context = get_goals_context()
                if goals_context:
                    formatted_data += goals_context
                    cprint("📋 Trading goals included in analysis", "cyan")

                # Call AI model via model factory
                response = self.chat_with_ai(
                    TRADING_PROMPT.format(strategy_context=strategy_context),
                    f"Market Data to Analyze:\n{formatted_data}"
                )

                if not response:
                    cprint(f"❌ No response from AI for {token}", "red")
                    return None

                # Parse the response
                lines = response.split('\n')
                action = lines[0].strip() if lines else "NOTHING"

                # Extract confidence from the response (assuming it's mentioned as a percentage)
                confidence = 50  # Default
                for line in lines:
                    if 'confidence' in line.lower():
                        # Extract number from string like "Confidence: 75%" or "75% confidence"
                        try:
                            import re
                            # Look for patterns like "65%", "65 %", or just a number near "confidence"
                            match = re.search(r'(\d{1,3})\s*%', line)
                            if match:
                                confidence = min(int(match.group(1)), 100)  # Cap at 100%
                            break  # Stop after first confidence found
                        except:
                            confidence = 50  # Default if not found

                # Add to recommendations DataFrame with proper reasoning
                reasoning = '\n'.join(lines[1:]) if len(lines) > 1 else "No detailed reasoning provided"
                self.recommendations_df = pd.concat([
                    self.recommendations_df,
                    pd.DataFrame([{
                        'token': token,
                        'action': action,
                        'confidence': confidence,
                        'reasoning': reasoning
                    }])
                ], ignore_index=True)

                # Save analysis report for dashboard watchlist
                save_analysis_report(token, action, confidence, reasoning)

                print(f"🎯 Moon Dev's AI Analysis Complete for {token[:4]}!")
                return response

        except Exception as e:
            print(f"❌ Error in AI analysis: {str(e)}")
            # Still add to DataFrame even on error, but mark as NOTHING with 0 confidence
            self.recommendations_df = pd.concat([
                self.recommendations_df,
                pd.DataFrame([{
                    'token': token,
                    'action': "NOTHING",
                    'confidence': 0,
                    'reasoning': f"Error during analysis: {str(e)}"
                }])
            ], ignore_index=True)
            return None
    
    def allocate_portfolio(self):
        """Get AI-recommended portfolio allocation"""
        try:
            cprint("\n💰 Calculating optimal portfolio allocation...", "cyan")
            max_position_size = usd_size * (MAX_POSITION_PERCENTAGE / 100)
            cprint(f"🎯 Maximum position size: ${max_position_size:.2f} ({MAX_POSITION_PERCENTAGE}% of ${usd_size:.2f})", "cyan")

            # Get allocation from AI via model factory
            # Use appropriate token list based on exchange
            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                available_tokens = SYMBOLS
            else:
                available_tokens = MONITORED_TOKENS

            allocation_prompt = f"""You are Moon Dev's Portfolio Allocation AI 🌙

Given:
- Total portfolio size: ${usd_size}
- Maximum position size: ${max_position_size} ({MAX_POSITION_PERCENTAGE}% of total)
- Minimum cash (USDC) buffer: {CASH_PERCENTAGE}%
- Available tokens: {available_tokens}
- USDC Address: {USDC_ADDRESS}

Provide a portfolio allocation that:
1. Never exceeds max position size per token
2. Maintains minimum cash buffer
3. Returns allocation as a JSON object with token addresses as keys and USD amounts as values
4. Uses exact USDC address: {USDC_ADDRESS} for cash allocation

Example format:
{{
    "token_address": amount_in_usd,
    "{USDC_ADDRESS}": remaining_cash_amount  # Use exact USDC address
}}"""

            response = self.chat_with_ai("", allocation_prompt)

            if not response:
                cprint("❌ No response from AI for portfolio allocation", "red")
                return None

            # Parse the response
            allocations = self.parse_allocation_response(response)
            if not allocations:
                return None
                
            # Fix USDC address if needed
            if "USDC_ADDRESS" in allocations:
                amount = allocations.pop("USDC_ADDRESS")
                allocations[USDC_ADDRESS] = amount
                
            # Validate allocation totals
            total_allocated = sum(allocations.values())
            if total_allocated > usd_size:
                cprint(f"❌ Total allocation ${total_allocated:.2f} exceeds portfolio size ${usd_size:.2f}", "red")
                return None
                
            # Print allocations
            cprint("\n📊 Portfolio Allocation:", "green")
            for token, amount in allocations.items():
                token_display = "USDC" if token == USDC_ADDRESS else token
                cprint(f"  • {token_display}: ${amount:.2f}", "green")
                
            return allocations
            
        except Exception as e:
            cprint(f"❌ Error in portfolio allocation: {str(e)}", "red")
            return None

    def execute_allocations(self, allocation_dict):
        """Execute the allocations using AI entry for each position"""
        try:
            print("\n🚀 Moon Dev executing portfolio allocations...")
            
            for token, amount in allocation_dict.items():
                # Skip USDC and other excluded tokens
                if token in EXCLUDED_TOKENS:
                    print(f"💵 Keeping ${amount:.2f} in {token}")
                    continue
                    
                print(f"\n🎯 Processing allocation for {token}...")

                try:
                    # Get current position value
                    if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                        if EXCHANGE == "HYPERLIQUID":
                            positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, is_long = n.get_position(token, HL_ACCOUNT)
                            if im_in_pos:
                                mid_price = n.get_current_price(token)
                                current_position = abs(float(pos_size)) * mid_price
                            else:
                                current_position = 0
                        else:
                            position = n.get_position(token)
                            if position and position.get('position_amount', 0) != 0:
                                current_position = abs(position.get('position_amount', 0)) * position.get('mark_price', 0)
                            else:
                                current_position = 0
                    else:
                        current_position = n.get_token_balance_usd(token)
                    target_allocation = amount
                    
                    print(f"🎯 Target allocation: ${target_allocation:.2f} USD")
                    print(f"📊 Current position: ${current_position:.2f} USD")
                    
                    if current_position < target_allocation:
                        print(f"✨ Executing entry for {token}")
                        # Pass leverage for Aster/HyperLiquid, skip for Solana
                        if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                            n.ai_entry(token, amount, leverage=LEVERAGE)
                        else:
                            n.ai_entry(token, amount)
                        print(f"✅ Entry complete for {token}")
                    else:
                        print(f"⏸️ Position already at target size for {token}")
                    
                except Exception as e:
                    print(f"❌ Error executing entry for {token}: {str(e)}")
                
                time.sleep(2)  # Small delay between entries
                
        except Exception as e:
            print(f"❌ Error executing allocations: {str(e)}")
            print("🔧 Moon Dev suggests checking the logs and trying again!")

    def handle_exits(self):
        """Check and exit positions based on SELL recommendations"""
        cprint("\n🔄 Checking for positions to exit...", "white", "on_blue")

        for _, row in self.recommendations_df.iterrows():
            token = row['token']
            token_short = token[:8] + "..." if len(token) > 8 else token

            # Skip excluded tokens (USDC and SOL)
            if token in EXCLUDED_TOKENS:
                continue

            action = row['action']

            # Check if we have a position
            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                if EXCHANGE == "HYPERLIQUID":
                    positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, is_long = n.get_position(token, HL_ACCOUNT)
                    if im_in_pos:
                        mid_price = n.get_current_price(token)
                        current_position = abs(float(pos_size)) * mid_price
                    else:
                        current_position = 0
                else:
                    position = n.get_position(token)
                    if position and position.get('position_amount', 0) != 0:
                        current_position = abs(position.get('position_amount', 0)) * position.get('mark_price', 0)
                    else:
                        current_position = 0
            else:
                current_position = n.get_token_balance_usd(token)

            cprint(f"\n{'='*60}", "cyan")
            cprint(f"🎯 Token: {token_short}", "cyan", attrs=['bold'])
            cprint(f"🤖 Swarm Signal: {action} ({row['confidence']}% confidence)", "yellow", attrs=['bold'])
            cprint(f"💼 Current Position: ${current_position:.2f}", "white")
            cprint(f"{'='*60}", "cyan")

            # Check confidence threshold for ALL trades (new positions AND adding to positions)
            confidence = row['confidence']
            min_conf = get_min_confidence()
            if action in ["BUY", "SELL"] and confidence < min_conf:
                cprint(f"⚠️  Confidence {confidence}% < {min_conf}% threshold - SKIPPING TRADE", "yellow", attrs=['bold'])
                cprint(f"📊 Waiting for higher confidence signal...", "cyan")
                continue

            if current_position > 0:
                # We have a position - check if we need to REVERSE
                # Get current position direction for HyperLiquid
                current_is_long = True  # Default for non-HL exchanges
                if EXCHANGE == "HYPERLIQUID":
                    positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, current_is_long = n.get_position(token, HL_ACCOUNT)

                # Check for REVERSAL conditions:
                # - We're SHORT and get BUY signal → reverse to LONG
                # - We're LONG and get SELL signal → reverse to SHORT (if not LONG_ONLY)
                # IMPORTANT: Require multiple confirmations to prevent costly flip-flopping
                need_reverse = False
                reverse_to_long = False
                potential_reversal_direction = None

                if not current_is_long and action == "BUY":
                    potential_reversal_direction = "LONG"
                elif current_is_long and action == "SELL" and not LONG_ONLY:
                    potential_reversal_direction = "SHORT"

                # Track reversal signals and require confirmations
                if potential_reversal_direction:
                    global reversal_signals

                    # Initialize tracking for this token if not exists
                    if token not in reversal_signals:
                        reversal_signals[token] = {"direction": None, "count": 0, "confidences": []}

                    # Check if this continues the same reversal direction or resets
                    if reversal_signals[token]["direction"] == potential_reversal_direction:
                        # Same direction - increment count
                        reversal_signals[token]["count"] += 1
                        reversal_signals[token]["confidences"].append(confidence)
                    else:
                        # Different direction - reset counter
                        reversal_signals[token] = {
                            "direction": potential_reversal_direction,
                            "count": 1,
                            "confidences": [confidence]
                        }

                    signal_count = reversal_signals[token]["count"]
                    avg_confidence = sum(reversal_signals[token]["confidences"]) / len(reversal_signals[token]["confidences"])

                    cprint(f"🔄 REVERSAL SIGNAL {signal_count}/{REVERSAL_CONFIRMATIONS_REQUIRED}: {potential_reversal_direction}", "yellow", attrs=['bold'])
                    cprint(f"   Avg Confidence: {avg_confidence:.1f}% (need {REVERSAL_MIN_CONFIDENCE}%)", "cyan")

                    # Check if we have enough confirmations AND confidence
                    if signal_count >= REVERSAL_CONFIRMATIONS_REQUIRED and avg_confidence >= REVERSAL_MIN_CONFIDENCE:
                        need_reverse = True
                        reverse_to_long = (potential_reversal_direction == "LONG")
                        cprint(f"✅ REVERSAL CONFIRMED! {signal_count} signals, {avg_confidence:.1f}% avg confidence", "white", "on_magenta", attrs=['bold'])
                        # Reset the counter after executing
                        reversal_signals[token] = {"direction": None, "count": 0, "confidences": []}
                    elif signal_count < REVERSAL_CONFIRMATIONS_REQUIRED:
                        cprint(f"⏳ Waiting for {REVERSAL_CONFIRMATIONS_REQUIRED - signal_count} more confirmation(s)...", "yellow")
                    else:
                        cprint(f"⚠️ Confidence too low ({avg_confidence:.1f}% < {REVERSAL_MIN_CONFIDENCE}%) - waiting for stronger signal", "yellow")
                else:
                    # Not a reversal signal - reset the counter for this token
                    if token in reversal_signals:
                        reversal_signals[token] = {"direction": None, "count": 0, "confidences": []}

                if need_reverse and EXCHANGE == "HYPERLIQUID":
                    try:
                        # Step 1: Close current position
                        close_pnl = float(positions[0].get('position', {}).get('unrealizedPnl', 0)) if positions else 0
                        cprint(f"📉 Step 1: Closing {'SHORT' if not current_is_long else 'LONG'} position...", "yellow")
                        n.kill_switch(token, HL_ACCOUNT)

                        # Play close sound
                        if close_pnl >= 0:
                            play_trade_sound("close_profit", close_pnl)
                        else:
                            play_trade_sound("close_loss", close_pnl)

                        # Clear old fills for this symbol
                        from pathlib import Path
                        fills_file = Path(__file__).parent.parent / "data" / "trade_fills.json"
                        if fills_file.exists():
                            import json
                            with open(fills_file, 'r') as f:
                                data = json.load(f)
                            data["fills"] = [f for f in data.get("fills", []) if f.get("symbol") != token]
                            with open(fills_file, 'w') as f:
                                json.dump(data, f, indent=4)

                        cprint(f"✅ Position closed!", "green")
                        time.sleep(2)  # Wait for position to settle

                        # Step 2: Open opposite position
                        account_balance = get_account_balance()
                        position_size = calculate_position_size(account_balance, confidence)

                        if reverse_to_long:
                            cprint(f"📈 Step 2: Opening LONG position (${position_size:.2f})...", "green")
                            n.ai_entry(token, position_size, leverage=LEVERAGE)
                        else:
                            cprint(f"📉 Step 2: Opening SHORT position (${position_size:.2f})...", "red")
                            if hasattr(n, 'open_short'):
                                n.open_short(token, position_size, slippage, leverage=LEVERAGE)
                            else:
                                n.market_sell(token, position_size, slippage, leverage=LEVERAGE)

                        # CRITICAL: Verify the position actually opened in the correct direction
                        time.sleep(2)  # Wait for position to settle
                        positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)

                        # Verify position exists AND is in the expected direction
                        position_verified = False
                        if im_in_pos:
                            expected_direction = reverse_to_long  # True = LONG, False = SHORT
                            if is_long == expected_direction:
                                position_verified = True
                                cprint(f"✅ REVERSAL COMPLETE! Now {'LONG' if reverse_to_long else 'SHORT'}", "white", "on_green", attrs=['bold'])
                            else:
                                cprint(f"⚠️ Position direction mismatch! Expected {'LONG' if reverse_to_long else 'SHORT'}, got {'LONG' if is_long else 'SHORT'}", "white", "on_red")
                        else:
                            cprint(f"❌ REVERSAL FAILED! Position did not open (IOC order may have been cancelled)", "white", "on_red")
                            cprint(f"💡 Price may have moved too fast for IOC order to fill", "yellow")

                        if position_verified:
                            play_trade_sound("open")

                            # Set TP/SL for new position (position already verified above)
                            if entry_px:
                                # Save trade fill
                                mid_price = n.get_current_price(token)
                                fill_qty = abs(float(pos_size))
                                save_trade_fill(token, fill_qty, mid_price, "BUY" if reverse_to_long else "SELL")
                                n.place_tp_sl_orders(token, float(entry_px), abs(float(pos_size)), is_long, TAKE_PROFIT_PERCENTAGE, STOP_LOSS_PERCENTAGE, HL_ACCOUNT)

                                # Save detailed auto-reversal analysis
                                original_reasoning = row.get('reasoning', 'No analysis available')
                                pnl_str = f"+${close_pnl:.2f}" if close_pnl >= 0 else f"-${abs(close_pnl):.2f}"
                                reversal_reasoning = (
                                    f"🔄 AUTO-REVERSAL EXECUTED\n\n"
                                    f"Previous Position: {'SHORT' if reverse_to_long else 'LONG'}\n"
                                    f"Received Signal: {action} at {confidence}% confidence\n"
                                    f"Closed PnL: {pnl_str}\n"
                                    f"New Position: {'LONG' if reverse_to_long else 'SHORT'} @ ${entry_px:.2f}\n\n"
                                    f"Why Reversal: Signal direction ({action}) conflicted with position direction "
                                    f"({'SHORT' if reverse_to_long else 'LONG'}). Auto-reversal closed the existing "
                                    f"position and opened opposite direction.\n\n"
                                    f"Original Analysis:\n{original_reasoning[:300]}"
                                )
                                save_trade_analysis(token, f"REVERSE TO {'LONG' if reverse_to_long else 'SHORT'}", confidence, float(entry_px), reversal_reasoning)
                    except Exception as e:
                        cprint(f"❌ Error during reversal: {str(e)}", "white", "on_red")
                    continue  # Move to next token after reversal

                # Normal position handling (no reversal needed)
                if action == "SELL":
                    if current_is_long:
                        cprint(f"🚨 SELL signal with LONG position - CLOSING POSITION", "white", "on_red")
                    else:
                        cprint(f"✅ SELL signal with SHORT position - HOLDING SHORT", "white", "on_green")
                        cprint(f"💎 Maintaining ${current_position:.2f} short position", "cyan")
                        continue
                    try:
                        # Get PnL before closing for sound notification
                        close_pnl = 0
                        if EXCHANGE == "HYPERLIQUID":
                            positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)
                            if im_in_pos:
                                close_pnl = float(positions[0].get('position', {}).get('unrealizedPnl', 0)) if positions else 0
                            cprint(f"📉 Executing kill_switch for {token}...", "yellow")
                            n.kill_switch(token, HL_ACCOUNT)
                        else:
                            cprint(f"📉 Executing chunk_kill (${max_usd_order_size} chunks)...", "yellow")
                            n.chunk_kill(token, max_usd_order_size, slippage)
                        cprint(f"✅ Position closed successfully!", "white", "on_green")
                        # Play sound based on profit/loss
                        if close_pnl >= 0:
                            play_trade_sound("close_profit", close_pnl)
                        else:
                            play_trade_sound("close_loss", close_pnl)
                    except Exception as e:
                        cprint(f"❌ Error closing position: {str(e)}", "white", "on_red")
                elif action == "NOTHING":
                    cprint(f"⏸️  DO NOTHING signal - HOLDING POSITION", "white", "on_blue")
                    cprint(f"💎 Maintaining ${current_position:.2f} position", "cyan")
                else:  # BUY
                    # Check if we can add to position
                    account_balance = get_account_balance()
                    target_position = calculate_position_size(account_balance, confidence)
                    max_position = account_balance * (MAX_POSITION_PERCENTAGE / 100)

                    if current_position < max_position * 0.9:  # Allow adding if below 90% of max
                        add_amount = min(target_position, max_position - current_position)
                        if add_amount >= 10:  # Minimum $10 to add
                            cprint(f"📈 BUY signal - ADDING TO POSITION", "white", "on_green")
                            cprint(f"💰 Current: ${current_position:.2f} | Adding: ${add_amount:.2f}", "cyan")
                            try:
                                if EXCHANGE == "HYPERLIQUID":
                                    success = n.ai_entry(token, add_amount, leverage=LEVERAGE)
                                    if success:
                                        cprint(f"✅ Added ${add_amount:.2f} to position!", "white", "on_green")
                                        play_trade_sound("open")
                                        # Update TP/SL for new position size
                                        time.sleep(2)
                                        positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)
                                        if im_in_pos and entry_px:
                                            # Save trade fill for dashboard tracking
                                            mid_price = n.get_current_price(token)
                                            fill_qty = add_amount / mid_price if mid_price else 0
                                            save_trade_fill(token, fill_qty, mid_price, "BUY")
                                            # Save trade analysis with reasoning
                                            reasoning = row.get('reasoning', 'No analysis available')
                                            add_reasoning = f"📈 ADDING TO POSITION\n\nAdded: ${add_amount:.2f} to existing position\nNew Total Size: {abs(float(pos_size))} {token}\nEntry Price: ${entry_px:.4f}\nConfidence: {confidence}%\n\nOriginal Analysis:\n{reasoning[:500]}"
                                            save_trade_analysis(token, "ADD TO POSITION", confidence, float(entry_px), add_reasoning)
                                            n.place_tp_sl_orders(token, float(entry_px), abs(float(pos_size)), is_long, TAKE_PROFIT_PERCENTAGE, STOP_LOSS_PERCENTAGE, HL_ACCOUNT)
                            except Exception as e:
                                cprint(f"❌ Error adding to position: {str(e)}", "white", "on_red")
                        else:
                            cprint(f"✅ BUY signal - KEEPING POSITION (add amount too small)", "white", "on_green")
                            cprint(f"💎 Maintaining ${current_position:.2f} position", "cyan")
                    else:
                        cprint(f"✅ BUY signal - AT MAX POSITION", "white", "on_green")
                        cprint(f"💎 Maintaining ${current_position:.2f} / ${max_position:.2f} max", "cyan")
            else:
                # No position - explain what this means
                if action == "SELL":
                    if LONG_ONLY:
                        cprint(f"⏭️  SELL signal but NO POSITION to close", "white", "on_blue")
                        cprint(f"📊 LONG ONLY mode: Can't open short, doing nothing", "cyan")
                    else:
                        # SHORT MODE ENABLED - Open short position
                        # Get account balance and calculate position size with dynamic sizing
                        account_balance = get_account_balance()
                        position_size = calculate_position_size(account_balance, confidence)

                        cprint(f"📉 SELL signal with no position - OPENING SHORT", "white", "on_red")
                        cprint(f"⚡ {EXCHANGE} mode: Opening ${position_size:,.2f} short position", "yellow")
                        try:
                            # Check if we have the open_short function (Aster/HyperLiquid)
                            if hasattr(n, 'open_short'):
                                cprint(f"📉 Executing open_short (${position_size:,.2f})...", "yellow")
                                n.open_short(token, position_size, slippage, leverage=LEVERAGE)
                            else:
                                # Fallback to market_sell which should open short on futures exchanges
                                cprint(f"📉 Executing market_sell to open short (${position_size:,.2f})...", "yellow")
                                n.market_sell(token, position_size, slippage, leverage=LEVERAGE)
                            cprint(f"✅ Short position opened successfully!", "white", "on_green")

                            # Place TP/SL orders on HyperLiquid
                            if EXCHANGE == "HYPERLIQUID":
                                time.sleep(2)  # Wait for position to settle
                                positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)
                                if im_in_pos and entry_px:
                                    n.place_tp_sl_orders(token, float(entry_px), abs(float(pos_size)), is_long, TAKE_PROFIT_PERCENTAGE, STOP_LOSS_PERCENTAGE, HL_ACCOUNT)
                        except Exception as e:
                            cprint(f"❌ Error opening short position: {str(e)}", "white", "on_red")
                elif action == "NOTHING":
                    cprint(f"⏸️  DO NOTHING signal with no position", "white", "on_blue")
                    cprint(f"⏭️  Staying out of market", "cyan")
                else:  # BUY
                    cprint(f"📈 BUY signal with no position", "white", "on_green")

                    if USE_PORTFOLIO_ALLOCATION:
                        cprint(f"📊 Portfolio allocation will handle entry", "white", "on_cyan")
                    else:
                        # Simple mode: Open position with dynamic sizing based on confidence
                        account_balance = get_account_balance()
                        position_size = calculate_position_size(account_balance, confidence)

                        cprint(f"💰 Opening position with {'DYNAMIC' if USE_DYNAMIC_SIZING else 'FIXED'} sizing", "white", "on_green")
                        try:
                            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                                success = n.ai_entry(token, position_size, leverage=LEVERAGE)
                            else:
                                success = n.ai_entry(token, position_size)

                            if success:
                                cprint(f"✅ Position opened successfully!", "white", "on_green")
                                play_trade_sound("open")  # 🔊 Audible notification

                                # Verify position was actually opened
                                time.sleep(2)  # Brief delay for order to settle
                                if EXCHANGE == "HYPERLIQUID":
                                    positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)
                                    if im_in_pos:
                                        mid_price = n.get_current_price(token)
                                        position_usd = abs(float(pos_size)) * mid_price
                                        cprint(f"📊 Confirmed: ${position_usd:,.2f} position | P&L: {pnl_pct:+.2f}%", "green", attrs=['bold'])

                                        # Save trade fill for dashboard tracking
                                        save_trade_fill(token, abs(float(pos_size)), mid_price, "BUY")

                                        # Place TP/SL orders on HyperLiquid
                                        if entry_px:
                                            n.place_tp_sl_orders(token, float(entry_px), abs(float(pos_size)), is_long, TAKE_PROFIT_PERCENTAGE, STOP_LOSS_PERCENTAGE, HL_ACCOUNT)

                                        # Save trade analysis for dashboard
                                        reasoning = row.get('reasoning', 'No analysis available')
                                        save_trade_analysis(token, action, confidence, entry_px, reasoning)
                                    else:
                                        cprint(f"⚠️  Warning: Position verification failed - no position found!", "yellow")
                                elif EXCHANGE == "ASTER":
                                    position = n.get_position(token)
                                    if position and position.get('position_amount', 0) != 0:
                                        pnl_pct = position.get('pnl_percentage', 0)
                                        position_usd = abs(position.get('position_amount', 0)) * position.get('mark_price', 0)
                                        cprint(f"📊 Confirmed: ${position_usd:,.2f} position | P&L: {pnl_pct:+.2f}%", "green", attrs=['bold'])

                                        # Save trade analysis for dashboard
                                        reasoning = row.get('reasoning', 'No analysis available')
                                        entry_price = position.get('entry_price', 0)
                                        save_trade_analysis(token, action, confidence, entry_price, reasoning)
                                    else:
                                        cprint(f"⚠️  Warning: Position verification failed - no position found!", "yellow")
                                else:
                                    position_usd = n.get_token_balance_usd(token)
                                    if position_usd > 0:
                                        cprint(f"📊 Confirmed: ${position_usd:,.2f} position", "green", attrs=['bold'])

                                        # Save trade analysis for dashboard
                                        reasoning = row.get('reasoning', 'No analysis available')
                                        save_trade_analysis(token, action, confidence, 0, reasoning)
                                    else:
                                        cprint(f"⚠️  Warning: Position verification failed - no position found!", "yellow")
                            else:
                                cprint(f"❌ Position not opened (check errors above)", "white", "on_red")
                        except Exception as e:
                            cprint(f"❌ Error opening position: {str(e)}", "white", "on_red")

    def parse_allocation_response(self, response):
        """Parse the AI's allocation response and handle both string and TextBlock formats"""
        try:
            # Handle TextBlock format from Claude 3
            if isinstance(response, list):
                response = response[0].text if hasattr(response[0], 'text') else str(response[0])
            
            print("🔍 Raw response received:")
            print(response)
            
            # Find the JSON block between curly braces
            start = response.find('{')
            end = response.rfind('}') + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON object found in response")
            
            json_str = response[start:end]
            
            # More aggressive JSON cleaning
            json_str = (json_str
                .replace('\n', '')          # Remove newlines
                .replace('    ', '')        # Remove indentation
                .replace('\t', '')          # Remove tabs
                .replace('\\n', '')         # Remove escaped newlines
                .replace(' ', '')           # Remove all spaces
                .strip())                   # Remove leading/trailing whitespace
            
            print("\n🧹 Cleaned JSON string:")
            print(json_str)
            
            # Parse the cleaned JSON
            allocations = json.loads(json_str)
            
            print("\n📊 Parsed allocations:")
            for token, amount in allocations.items():
                print(f"  • {token}: ${amount}")
            
            # Validate amounts are numbers
            for token, amount in allocations.items():
                if not isinstance(amount, (int, float)):
                    raise ValueError(f"Invalid amount type for {token}: {type(amount)}")
                if amount < 0:
                    raise ValueError(f"Negative allocation for {token}: {amount}")
            
            return allocations
            
        except Exception as e:
            print(f"❌ Error parsing allocation response: {str(e)}")
            print("🔍 Raw response:")
            print(response)
            return None

    def parse_portfolio_allocation(self, allocation_text):
        """Parse portfolio allocation from text response"""
        try:
            # Clean up the response text
            cleaned_text = allocation_text.strip()
            if "```json" in cleaned_text:
                # Extract JSON from code block if present
                json_str = cleaned_text.split("```json")[1].split("```")[0]
            else:
                # Find the JSON object between curly braces
                start = cleaned_text.find('{')
                end = cleaned_text.rfind('}') + 1
                json_str = cleaned_text[start:end]
            
            # Parse the JSON
            allocations = json.loads(json_str)
            
            print("📊 Parsed allocations:")
            for token, amount in allocations.items():
                print(f"  • {token}: ${amount}")
            
            return allocations
            
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing allocation JSON: {e}")
            print(f"🔍 Raw text received:\n{allocation_text}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error parsing allocations: {e}")
            return None

    def run(self):
        """Run the trading agent (implements BaseAgent interface)"""
        self.run_trading_cycle()

    def run_trading_cycle(self, strategy_signals=None):
        """Run one complete trading cycle"""
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cprint(f"\n⏰ AI Agent Run Starting at {current_time}", "white", "on_green")

            # 🛑 CHECK DAILY DRAWDOWN CIRCUIT BREAKER
            drawdown_check = check_daily_drawdown()
            if drawdown_check['warning']:
                cprint(f"\n{drawdown_check['message']}", "yellow", attrs=['bold'])

            if not drawdown_check['trading_allowed']:
                cprint(f"\n🛑 TRADING HALTED: {drawdown_check['message']}", "red", attrs=['bold'])
                cprint(f"   Daily P&L: ${drawdown_check['daily_pnl']:,.2f} ({drawdown_check['daily_pnl_pct']:+.2f}%)", "red")
                cprint(f"   To reset: Call reset_daily_drawdown() or wait for new trading day", "yellow")
                return  # Exit without trading
            else:
                # Show daily P&L status
                daily_pnl = drawdown_check['daily_pnl']
                daily_pnl_pct = drawdown_check['daily_pnl_pct']
                limit = drawdown_check['limit'] if not USE_DAILY_DRAWDOWN_PCT else drawdown_check['limit_pct']
                color = "green" if daily_pnl >= 0 else "yellow"
                cprint(f"📊 Daily P&L: ${daily_pnl:,.2f} ({daily_pnl_pct:+.2f}%) | Limit: ${DAILY_DRAWDOWN_LIMIT_USD}", color)

            # Reset recommendations for this cycle (prevents accumulation across cycles)
            self.recommendations_df = pd.DataFrame(columns=['token', 'action', 'confidence', 'reasoning'])

            # Collect OHLCV data for all tokens using this agent's config
            # Use SYMBOLS for Aster/HyperLiquid, MONITORED_TOKENS for Solana
            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                tokens_to_trade = SYMBOLS
                cprint(f"🏦 Using {EXCHANGE} - Trading symbols: {SYMBOLS}", "yellow")
            else:
                tokens_to_trade = MONITORED_TOKENS
                cprint(f"🏦 Using SOLANA - Trading tokens: {MONITORED_TOKENS}", "yellow")

            cprint("📊 Collecting market data...", "white", "on_blue")
            cprint(f"🎯 Tokens to collect: {tokens_to_trade}", "yellow")
            cprint(f"📅 Settings: {DAYSBACK_4_DATA} days @ {DATA_TIMEFRAME}", "yellow")

            market_data = collect_all_tokens(
                tokens=tokens_to_trade,
                days_back=DAYSBACK_4_DATA,
                timeframe=DATA_TIMEFRAME,
                exchange=EXCHANGE  # Pass exchange to data collector
            )

            cprint(f"📦 Market data received for {len(market_data)} tokens", "green")
            if len(market_data) == 0:
                cprint("⚠️ WARNING: No market data collected! Check token list.", "red")
                cprint(f"🔍 Tokens = {tokens_to_trade}", "red")
            
            # Analyze each token's data
            for token, data in market_data.items():
                cprint(f"\n🤖 AI Agent Analyzing Token: {token}", "white", "on_green")
                
                # Include strategy signals in analysis if available
                if strategy_signals and token in strategy_signals:
                    cprint(f"📊 Including {len(strategy_signals[token])} strategy signals in analysis", "cyan")
                    data['strategy_signals'] = strategy_signals[token]
                
                analysis = self.analyze_market_data(token, data)
                print(f"\n📈 Analysis for contract: {token}")
                print(analysis)
                print("\n" + "="*50 + "\n")
            
            # Show recommendations summary
            cprint("\n📊 Moon Dev's Trading Recommendations:", "white", "on_blue")
            summary_df = self.recommendations_df[['token', 'action', 'confidence']].copy()
            print(summary_df.to_string(index=False))

            # Handle exits first (always runs - manages SELL recommendations)
            self.handle_exits()

            # Portfolio allocation (only if enabled and there are BUY recommendations)
            buy_recommendations = self.recommendations_df[self.recommendations_df['action'] == 'BUY']

            if USE_PORTFOLIO_ALLOCATION and len(buy_recommendations) > 0:
                cprint(f"\n💰 Found {len(buy_recommendations)} BUY signal(s) - Using AI portfolio allocation...", "white", "on_green")
                allocation = self.allocate_portfolio()

                if allocation:
                    cprint("\n💼 Moon Dev's Portfolio Allocation:", "white", "on_blue")
                    print(json.dumps(allocation, indent=4))

                    cprint("\n🎯 Executing allocations...", "white", "on_blue")
                    self.execute_allocations(allocation)
                    cprint("\n✨ All allocations executed!", "white", "on_blue")
                else:
                    cprint("\n⚠️ No allocations to execute!", "white", "on_yellow")
            elif not USE_PORTFOLIO_ALLOCATION and len(buy_recommendations) > 0:
                cprint(f"\n💰 Found {len(buy_recommendations)} BUY signal(s)", "white", "on_green")
                cprint("📊 Portfolio allocation is DISABLED - positions opened in handle_exits", "cyan")
            else:
                cprint("\n⏭️  No BUY signals - No entries to make", "white", "on_blue")
                cprint("📊 All signals were SELL or DO NOTHING", "cyan")
            
            # Clean up temp data
            cprint("\n🧹 Cleaning up temporary data...", "white", "on_blue")
            try:
                for file in os.listdir('temp_data'):
                    if file.endswith('_latest.csv'):
                        os.remove(os.path.join('temp_data', file))
                cprint("✨ Temp data cleaned successfully!", "white", "on_green")
            except Exception as e:
                cprint(f"⚠️ Error cleaning temp data: {str(e)}", "white", "on_yellow")
            
        except Exception as e:
            cprint(f"\n❌ Error in trading cycle: {str(e)}", "white", "on_red")
            cprint("🔧 Moon Dev suggests checking the logs and trying again!", "white", "on_blue")

def get_market_volatility():
    """Calculate current market volatility based on ATR%"""
    try:
        # Get BTC data as market proxy
        if EXCHANGE == "HYPERLIQUID":
            data = n.get_data("BTC", timeframe="1H", bars=20, add_indicators=True)
        else:
            return 2.0  # Default medium volatility for other exchanges

        if data is None or data.empty:
            return 2.0

        # Calculate ATR as percentage of price
        atr = data['atr'].iloc[-1] if 'atr' in data.columns else 0
        close = data['close'].iloc[-1]
        atr_percent = (atr / close) * 100 if close > 0 else 2.0

        return atr_percent
    except Exception as e:
        cprint(f"⚠️ Volatility check error: {e}", "yellow")
        return 2.0  # Default to medium

def get_dynamic_interval():
    """Get scan interval based on volatility or preset"""
    global DATA_TIMEFRAME

    # Load settings from file if exists
    settings_file = Path(__file__).parent.parent / "data" / "scan_settings.json"
    try:
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                preset = settings.get('preset', CURRENT_SCAN_PRESET)
                auto_adjust = settings.get('auto_adjust', AUTO_ADJUST_INTERVAL)
        else:
            preset = CURRENT_SCAN_PRESET
            auto_adjust = AUTO_ADJUST_INTERVAL
    except:
        preset = CURRENT_SCAN_PRESET
        auto_adjust = AUTO_ADJUST_INTERVAL

    if auto_adjust:
        # Auto-adjust based on volatility
        volatility = get_market_volatility()

        if volatility > VOLATILITY_THRESHOLDS["high"]:
            preset = "active"
            cprint(f"📈 High volatility ({volatility:.2f}%) → Active mode (15min scans)", "yellow")
        elif volatility < VOLATILITY_THRESHOLDS["low"]:
            preset = "swing"
            cprint(f"📉 Low volatility ({volatility:.2f}%) → Swing mode (60min scans)", "cyan")
        else:
            preset = "standard"
            cprint(f"📊 Normal volatility ({volatility:.2f}%) → Standard mode (30min scans)", "white")

    # Get preset settings
    scan_minutes, timeframe, description = SCAN_PRESETS.get(preset, SCAN_PRESETS["standard"])
    DATA_TIMEFRAME = timeframe  # Update timeframe globally

    cprint(f"🔄 Scan interval: {scan_minutes}min | Timeframe: {timeframe} | {description}", "cyan")

    return scan_minutes * 60  # Return seconds

def main():
    """Main function to run the trading agent every 15 minutes"""
    cprint("🌙 Moon Dev AI Trading System Starting Up! 🚀", "white", "on_blue")

    agent = TradingAgent()
    INTERVAL = get_dynamic_interval()  # Get initial interval

    while True:
        try:
            agent.run_trading_cycle()

            # Check if we have any open positions
            has_position = False
            monitored_token = None

            for token in SYMBOLS if EXCHANGE in ["ASTER", "HYPERLIQUID"] else MONITORED_TOKENS:
                if EXCHANGE == "HYPERLIQUID":
                    positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_pct, is_long = n.get_position(token, HL_ACCOUNT)
                    if im_in_pos:
                        has_position = True
                        monitored_token = token
                        break
                elif EXCHANGE == "ASTER":
                    position = n.get_position(token)
                    if position and position.get('position_amount', 0) != 0:
                        has_position = True
                        monitored_token = token
                        break
                else:
                    position_usd = n.get_token_balance_usd(token)
                    if position_usd > 0:
                        has_position = True
                        monitored_token = token
                        break

            if has_position and monitored_token:
                # We have an open position - monitor P&L instead of sleeping
                cprint(f"\n🔍 Open position detected for {monitored_token}", "yellow", attrs=['bold'])
                monitor_position_pnl(monitored_token)
                cprint(f"\n✅ Position closed.", "green")

                # After position closes, wait before next analysis to respect scan interval
                INTERVAL = get_dynamic_interval()
                next_run = datetime.now() + timedelta(seconds=INTERVAL)
                cprint(f"⏳ Waiting for next scan at {next_run.strftime('%Y-%m-%d %H:%M:%S')} ({INTERVAL//60} min)", "white", "on_green")
                time.sleep(INTERVAL)
            else:
                # No open position - recalculate interval and sleep
                INTERVAL = get_dynamic_interval()
                next_run = datetime.now() + timedelta(seconds=INTERVAL)
                cprint(f"\n⏳ No open positions. Next run at {next_run.strftime('%Y-%m-%d %H:%M:%S')}", "white", "on_green")
                time.sleep(INTERVAL)
                
        except KeyboardInterrupt:
            cprint("\n👋 Moon Dev AI Agent shutting down gracefully...", "white", "on_blue")
            break
        except Exception as e:
            cprint(f"\n❌ Error: {str(e)}", "white", "on_red")
            cprint("🔧 Moon Dev suggests checking the logs and trying again!", "white", "on_blue")
            # Still sleep and continue on error
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main() 