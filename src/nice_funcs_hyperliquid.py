"""
🌙 Moon Dev's HyperLiquid Trading Functions
Focused functions for HyperLiquid perps trading
Built with love by Moon Dev 🚀

LEVERAGE & POSITION SIZING:
- All 'amount' parameters represent NOTIONAL position size (total exposure)
- Leverage is applied by the exchange, reducing required margin
- Example: $25 position at 5x leverage = $25 notional, $5 margin required
- Formula: Required Margin = Notional Position / Leverage
- Default leverage: 5x (configurable below)
"""

import os
import json
import time
import requests
import pandas as pd
import numpy as np
import pandas_ta as ta
import datetime
from datetime import timedelta
from termcolor import colored, cprint
from eth_account.signers.local import LocalAccount
import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from dotenv import load_dotenv
import traceback

# Load environment variables
load_dotenv()

# Hide all warnings
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONNECTION POOLING & CACHING - Reuse connections for SPEED
# ============================================================================
_cached_info = None
_cached_exchange = {}  # keyed by account address
_cached_decimals = {}  # Cache symbol decimals to avoid repeated API calls

def get_cached_info():
    """Get cached Info object (creates once, reuses for all calls)"""
    global _cached_info
    if _cached_info is None:
        _cached_info = Info(constants.MAINNET_API_URL, skip_ws=True)
    return _cached_info

def get_cached_exchange(account):
    """Get cached Exchange object for an account"""
    global _cached_exchange
    addr = account.address
    if addr not in _cached_exchange:
        _cached_exchange[addr] = Exchange(account, constants.MAINNET_API_URL)
    return _cached_exchange[addr]

def reset_connections():
    """Reset all cached connections (call if connections go stale)"""
    global _cached_info, _cached_exchange
    _cached_info = None
    _cached_exchange = {}

# ============================================================================
# CONFIGURATION
# ============================================================================
DEFAULT_LEVERAGE = 3  # Change this to adjust leverage globally (1-50x on HyperLiquid)
                      # Higher leverage = less margin required, but higher liquidation risk
                      # Examples:
                      # - 5x: $25 position needs $5 margin
                      # - 10x: $25 position needs $2.50 margin
                      # - 20x: $25 position needs $1.25 margin

# Constants
BATCH_SIZE = 5000  # MAX IS 5000 FOR HYPERLIQUID
MAX_RETRIES = 3
MAX_ROWS = 5000
BASE_URL = 'https://api.hyperliquid.xyz/info'

# Global variable to store timestamp offset
timestamp_offset = None

def adjust_timestamp(dt):
    """Adjust API timestamps by subtracting the timestamp offset."""
    if timestamp_offset is not None:
        corrected_dt = dt - timestamp_offset
        return corrected_dt
    return dt

def ask_bid(symbol):
    """Get ask and bid prices for a symbol"""
    url = 'https://api.hyperliquid.xyz/info'
    headers = {'Content-Type': 'application/json'}

    data = {
        'type': 'l2Book',
        'coin': symbol
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    l2_data = response.json()
    l2_data = l2_data['levels']

    # get bid and ask
    bid = float(l2_data[0][0]['px'])
    ask = float(l2_data[1][0]['px'])

    return ask, bid, l2_data

def get_sz_px_decimals(symbol):
    """Get size and price decimals for a symbol - CACHED for speed"""
    global _cached_decimals

    # Return cached values if available (saves 2 API calls)
    if symbol in _cached_decimals:
        cached = _cached_decimals[symbol]
        return cached['sz'], cached['px']

    url = 'https://api.hyperliquid.xyz/info'
    headers = {'Content-Type': 'application/json'}
    data = {'type': 'meta'}

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        data = response.json()
        symbols = data['universe']
        symbol_info = next((s for s in symbols if s['name'] == symbol), None)
        if symbol_info:
            sz_decimals = symbol_info['szDecimals']
        else:
            print('Symbol not found')
            return 0, 0
    else:
        print('Error:', response.status_code)
        return 0, 0

    ask = ask_bid(symbol)[0]
    ask_str = str(ask)

    if '.' in ask_str:
        px_decimals = len(ask_str.split('.')[1])
    else:
        px_decimals = 0

    # Cache for future calls
    _cached_decimals[symbol] = {'sz': sz_decimals, 'px': px_decimals}

    print(f'{symbol} price: {ask} | sz decimals: {sz_decimals} | px decimals: {px_decimals}')
    return sz_decimals, px_decimals

def get_position(symbol, account):
    """Get current position for a symbol - uses cached connection for speed"""
    print(f'{colored("Getting position for", "cyan")} {colored(symbol, "yellow")}')

    info = get_cached_info()  # FAST: reuse connection
    user_state = info.user_state(account.address)

    positions = []
    for position in user_state["assetPositions"]:
        if position["position"]["coin"] == symbol and float(position["position"]["szi"]) != 0:
            positions.append(position["position"])
            coin = position["position"]["coin"]
            pos_size = float(position["position"]["szi"])
            entry_px = float(position["position"]["entryPx"])
            pnl_perc = float(position["position"]["returnOnEquity"]) * 100
            print(f'{colored(f"{coin} position:", "green")} Size: {pos_size} | Entry: ${entry_px} | PnL: {pnl_perc:.2f}%')

    im_in_pos = len(positions) > 0

    if not im_in_pos:
        print(f'{colored("No position in", "yellow")} {symbol}')
        return positions, im_in_pos, 0, symbol, 0, 0, True

    # Return position details
    pos_size = positions[0]["szi"]
    pos_sym = positions[0]["coin"]
    entry_px = float(positions[0]["entryPx"])
    pnl_perc = float(positions[0]["returnOnEquity"]) * 100
    is_long = float(pos_size) > 0

    if is_long:
        print(f'{colored("LONG", "green")} position')
    else:
        print(f'{colored("SHORT", "red")} position')

    return positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, is_long

def set_leverage(symbol, leverage, account):
    """Set leverage for a symbol - uses cached connection"""
    print(f'Setting leverage for {symbol} to {leverage}x')
    exchange = get_cached_exchange(account)

    # Update leverage (is_cross=True for cross margin)
    result = exchange.update_leverage(leverage, symbol, is_cross=True)
    print(f'✅ Leverage set to {leverage}x for {symbol}')
    return result

def adjust_leverage_usd_size(symbol, usd_size, leverage, account):
    """Adjust leverage and calculate position size"""
    print(f'Adjusting leverage for {symbol} to {leverage}x with ${usd_size} size')

    # Set the leverage
    set_leverage(symbol, leverage, account)

    # Get current price
    ask, bid, _ = ask_bid(symbol)
    mid_price = (ask + bid) / 2

    # Calculate position size in coins
    pos_size = usd_size / mid_price

    # Get decimals for rounding
    sz_decimals, _ = get_sz_px_decimals(symbol)
    pos_size = round(pos_size, sz_decimals)

    print(f'Position size: {pos_size} {symbol} (${usd_size} at ${mid_price:.2f})')

    return leverage, pos_size

def cancel_all_orders(account):
    """Cancel all open orders - uses cached connections"""
    print(colored('🚫 Cancelling all orders', 'yellow'))
    exchange = get_cached_exchange(account)
    info = get_cached_info()

    # Get all open orders
    open_orders = info.open_orders(account.address)

    if not open_orders:
        print(colored('   No open orders to cancel', 'yellow'))
        return

    # Cancel each order
    for order in open_orders:
        try:
            exchange.cancel(order['coin'], order['oid'])
            print(colored(f'   ✅ Cancelled {order["coin"]} order', 'green'))
        except Exception as e:
            print(colored(f'   ⚠️ Could not cancel {order["coin"]} order: {str(e)}', 'yellow'))

    print(colored('✅ All orders cancelled', 'green'))
    return

def place_tp_sl_orders(symbol, entry_price, position_size, is_long, tp_percent, sl_percent, account):
    """
    Place Take Profit and Stop Loss orders on HyperLiquid

    Args:
        symbol: Token symbol (e.g., 'BTC')
        entry_price: Entry price of the position
        position_size: Size of the position (positive number)
        is_long: True for long, False for short
        tp_percent: Take profit percentage (e.g., 12.0 for +12%)
        sl_percent: Stop loss percentage (e.g., 5.0 for -5%)
        account: HyperLiquid account

    Returns:
        dict with tp_result and sl_result
    """
    print(colored(f'\n🎯 Setting TP/SL orders for {symbol}', 'cyan', attrs=['bold']))

    # Ensure all values are floats (API may return strings)
    entry_price = float(entry_price)
    position_size = float(position_size)
    tp_percent = float(tp_percent)
    sl_percent = float(sl_percent)

    # Use cached connections for SPEED
    exchange = get_cached_exchange(account)
    info = get_cached_info()

    # Cancel existing orders for this symbol to prevent duplicates
    open_orders = info.open_orders(account.address)
    symbol_orders = [o for o in open_orders if o['coin'] == symbol]
    if symbol_orders:
        print(f"   🗑️ Cancelling {len(symbol_orders)} existing orders for {symbol}...")
        # Try batch cancel first (faster)
        try:
            cancel_requests = [{"coin": o['coin'], "oid": o['oid']} for o in symbol_orders]
            if len(cancel_requests) > 1:
                exchange.bulk_cancel(cancel_requests)
            else:
                exchange.cancel(symbol_orders[0]['coin'], symbol_orders[0]['oid'])
        except:
            # Fallback to sequential
            for order in symbol_orders:
                try:
                    exchange.cancel(order['coin'], order['oid'])
                except Exception as e:
                    print(colored(f"   ⚠️ Could not cancel order {order['oid']}: {e}", 'yellow'))
        print(f"   ✅ Cleared existing orders")

    sz_decimals, px_decimals = get_sz_px_decimals(symbol)

    # For trigger orders, use 0 decimals for high-value assets (BTC, ETH)
    # HyperLiquid requires whole number trigger prices for these
    trigger_decimals = 0 if entry_price > 100 else px_decimals

    # Calculate TP and SL prices based on position direction
    if is_long:
        tp_price = round(entry_price * (1 + tp_percent / 100), trigger_decimals)
        sl_price = round(entry_price * (1 - sl_percent / 100), trigger_decimals)
        # For long: TP sells above entry, SL sells below entry
        tp_is_buy = False  # Sell to close long
        sl_is_buy = False  # Sell to close long
    else:
        tp_price = round(entry_price * (1 - tp_percent / 100), trigger_decimals)
        sl_price = round(entry_price * (1 + sl_percent / 100), trigger_decimals)
        # For short: TP buys below entry, SL buys above entry
        tp_is_buy = True   # Buy to close short
        sl_is_buy = True   # Buy to close short

    size = round(abs(position_size), sz_decimals)

    print(f"   Entry: ${entry_price:.4f}")
    print(f"   Position: {'LONG' if is_long else 'SHORT'} {size} {symbol}")
    print(f"   Take Profit: ${tp_price:.4f} (+{tp_percent}%)")
    print(f"   Stop Loss: ${sl_price:.4f} (-{sl_percent}%)")

    results = {"tp_result": None, "sl_result": None}

    try:
        # Place Take Profit order (trigger order)
        tp_order_type = {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}}
        tp_result = exchange.order(symbol, tp_is_buy, size, tp_price, tp_order_type, reduce_only=True)
        results["tp_result"] = tp_result
        print(colored(f'   ✅ Take Profit set at ${tp_price:.4f}', 'green'))
    except Exception as e:
        print(colored(f'   ❌ Failed to set TP: {e}', 'red'))
        results["tp_result"] = {"error": str(e)}

    try:
        # Place Stop Loss order (trigger order)
        sl_order_type = {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}}
        sl_result = exchange.order(symbol, sl_is_buy, size, sl_price, sl_order_type, reduce_only=True)
        results["sl_result"] = sl_result
        print(colored(f'   ✅ Stop Loss set at ${sl_price:.4f}', 'green'))
    except Exception as e:
        print(colored(f'   ❌ Failed to set SL: {e}', 'red'))
        results["sl_result"] = {"error": str(e)}

    return results

def limit_order(coin, is_buy, sz, limit_px, reduce_only, account):
    """Place a limit order - uses cached connection"""
    exchange = get_cached_exchange(account)

    rounding = get_sz_px_decimals(coin)[0]
    sz = round(sz, rounding)

    print(f"🌙 Moon Dev placing order:")
    print(f"Symbol: {coin}")
    print(f"Side: {'BUY' if is_buy else 'SELL'}")
    print(f"Size: {sz}")
    print(f"Price: ${limit_px}")
    print(f"Reduce Only: {reduce_only}")

    order_result = exchange.order(coin, is_buy, sz, limit_px, {"limit": {"tif": "Gtc"}}, reduce_only=reduce_only)

    if isinstance(order_result, dict) and 'response' in order_result:
        print(f"✅ Order placed with status: {order_result['response']['data']['statuses'][0]}")
    else:
        print(f"✅ Order placed")

    return order_result

def kill_switch(symbol, account):
    """Close position at market price - ULTRA FAST using market_close()"""
    print(colored(f'🔪 KILL SWITCH: {symbol}', 'red', attrs=['bold']))

    exchange = get_cached_exchange(account)

    # Use market_close() - single API call, fastest method
    result = exchange.market_close(symbol)

    if result.get('status') == 'ok':
        statuses = result.get('response', {}).get('data', {}).get('statuses', [])
        if statuses and 'filled' in statuses[0]:
            filled = statuses[0]['filled']
            print(colored(f'✅ Closed {symbol} @ ${filled.get("avgPx", "?")}', 'green'))
        else:
            print(colored(f'✅ {symbol} closed', 'green'))
    else:
        print(colored(f'⚠️ Close result: {result}', 'yellow'))

    return result


def kill_switch_with_size(symbol, pos_size, is_long, account):
    """Close position when we already have position data - FASTEST (skips position fetch)"""
    print(colored(f'🔪 FAST CLOSE: {symbol}', 'red', attrs=['bold']))

    exchange = get_cached_exchange(account)

    # Use market_close() - fastest single API call
    result = exchange.market_close(symbol)

    if result.get('status') == 'ok':
        print(colored(f'✅ Closed {symbol}', 'green'))

    return result

def pnl_close(symbol, target, max_loss, account):
    """Close position if PnL target or stop loss is hit"""
    print(f'{colored("Checking PnL conditions", "cyan")}')
    print(f'Target: {target}% | Stop loss: {max_loss}%')

    # Get current position info
    positions, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, is_long = get_position(symbol, account)

    if not im_in_pos:
        print(colored('No position to check', 'yellow'))
        return False

    print(f'Current PnL: {colored(f"{pnl_perc:.2f}%", "green" if pnl_perc > 0 else "red")}')

    # Check if we should close
    if pnl_perc >= target:
        print(colored(f'✅ Target reached! Closing position WIN at {pnl_perc:.2f}%', 'green', attrs=['bold']))
        kill_switch(symbol, account)
        return True
    elif pnl_perc <= max_loss:
        print(colored(f'🛑 Stop loss hit! Closing position LOSS at {pnl_perc:.2f}%', 'red', attrs=['bold']))
        kill_switch(symbol, account)
        return True
    else:
        print(f'Position still open. PnL: {pnl_perc:.2f}%')
        return False

def get_current_price(symbol):
    """Get current price for a symbol"""
    ask, bid, _ = ask_bid(symbol)
    mid_price = (ask + bid) / 2
    return mid_price

def get_account_value(account):
    """Get total account value"""
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    user_state = info.user_state(account.address)
    account_value = float(user_state["marginSummary"]["accountValue"])
    print(f'Account value: ${account_value:,.2f}')
    return account_value

def market_buy(symbol, usd_size, account, auto_tpsl=True, tp_pct=10.0, sl_pct=3.0):
    """Market buy using HyperLiquid with automatic TP/SL

    Args:
        symbol: Token symbol (e.g., 'BTC', 'kPEPE')
        usd_size: USD amount to buy
        account: HyperLiquid account
        auto_tpsl: Automatically set TP/SL orders (default True)
        tp_pct: Take profit percentage (default 10%)
        sl_pct: Stop loss percentage (default 3%)
    """
    import math
    print(colored(f'🛒 Market BUY {symbol} for ${usd_size}', 'green'))

    # Get current ask price
    ask, bid, _ = ask_bid(symbol)

    # Get price decimals for this symbol
    sz_decimals, px_decimals = get_sz_px_decimals(symbol)

    # Overbid by 0.5% to ensure fill (market buy needs to be above ask)
    buy_price = ask * 1.005

    # Round UP to ensure we're above ask (for buys, round up)
    multiplier = 10 ** px_decimals
    buy_price = math.ceil(buy_price * multiplier) / multiplier

    # Calculate position size
    pos_size = usd_size / buy_price

    # Round position size down
    pos_size = round(pos_size, sz_decimals)

    # Ensure minimum order value
    order_value = pos_size * buy_price
    if order_value < 10:
        print(f'   ⚠️ Order value ${order_value:.2f} below $10 minimum, adjusting...')
        pos_size = 11 / buy_price  # $11 to have buffer
        pos_size = round(pos_size, sz_decimals)

    print(f'{symbol} price: {ask} | sz decimals: {sz_decimals} | px decimals: {px_decimals}')
    print(f'   Placing IOC buy at ${buy_price} (0.5% above ask ${ask})')
    print(f'   Position size: {pos_size} {symbol} (value: ${pos_size * buy_price:.2f})')

    # Place IOC order above ask to ensure fill - use cached exchange for speed
    exchange = get_cached_exchange(account)
    order_result = exchange.order(symbol, True, pos_size, buy_price, {"limit": {"tif": "Ioc"}}, reduce_only=False)

    print(colored(f'✅ Market buy executed: {pos_size} {symbol} at ${buy_price}', 'green'))

    # Auto set TP/SL if enabled and order was filled
    if auto_tpsl and order_result.get('status') == 'ok':
        statuses = order_result.get('response', {}).get('data', {}).get('statuses', [])
        if statuses and 'filled' in statuses[0]:
            print(colored(f'🎯 Auto-setting TP/SL (TP: +{tp_pct}%, SL: -{sl_pct}%)', 'cyan'))
            try:
                time.sleep(0.1)  # Minimal pause (reduced from 0.5s)
                # Get FULL position (not just this fill) for correct TP/SL sizing
                positions, im_in_pos, total_size, pos_sym, avg_entry, pnl_pct, is_long = get_position(symbol, account)
                if im_in_pos:
                    # Use total position size and average entry for TP/SL
                    place_tp_sl_orders(symbol, float(avg_entry), abs(float(total_size)), is_long, tp_pct, sl_pct, account)
                else:
                    # Fallback to fill data if position query fails
                    filled = statuses[0]['filled']
                    entry_px = float(filled.get('avgPx', buy_price))
                    filled_sz = float(filled.get('totalSz', pos_size))
                    place_tp_sl_orders(symbol, entry_px, filled_sz, True, tp_pct, sl_pct, account)
            except Exception as e:
                print(colored(f'⚠️ Failed to set TP/SL: {e}', 'yellow'))

    return order_result

def market_sell(symbol, usd_size, account):
    """Market sell using HyperLiquid"""
    print(colored(f'💸 Market SELL {symbol} for ${usd_size}', 'red'))

    # Get current bid price
    ask, bid, _ = ask_bid(symbol)

    # Undersell by 0.1% to ensure fill (market sell needs to be below bid)
    sell_price = bid * 0.999

    # Round to appropriate decimals for BTC (whole numbers)
    if symbol == 'BTC':
        sell_price = round(sell_price)
    else:
        sell_price = round(sell_price, 1)

    # Calculate position size
    pos_size = usd_size / sell_price

    # Get decimals and round
    sz_decimals, _ = get_sz_px_decimals(symbol)
    pos_size = round(pos_size, sz_decimals)

    # Ensure minimum order value
    order_value = pos_size * sell_price
    if order_value < 10:
        print(f'   ⚠️ Order value ${order_value:.2f} below $10 minimum, adjusting...')
        pos_size = 11 / sell_price  # $11 to have buffer
        pos_size = round(pos_size, sz_decimals)

    print(f'   Placing IOC sell at ${sell_price} (0.1% below bid ${bid})')
    print(f'   Position size: {pos_size} {symbol} (value: ${pos_size * sell_price:.2f})')

    # Place IOC order below bid to ensure fill - use cached exchange for speed
    exchange = get_cached_exchange(account)
    order_result = exchange.order(symbol, False, pos_size, sell_price, {"limit": {"tif": "Ioc"}}, reduce_only=False)

    print(colored(f'✅ Market sell executed: {pos_size} {symbol} at ${sell_price}', 'red'))
    return order_result

def close_position(symbol, account):
    """Close any open position for a symbol"""
    positions, im_in_pos, pos_size, _, _, pnl_perc, is_long = get_position(symbol, account)

    if not im_in_pos:
        print(f'No position to close for {symbol}')
        return None

    print(f'Closing {"LONG" if is_long else "SHORT"} position with PnL: {pnl_perc:.2f}%')
    return kill_switch(symbol, account)

# Additional helper functions for agents
def get_balance(account):
    """Get USDC balance"""
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    user_state = info.user_state(account.address)

    # Get withdrawable balance (free balance)
    balance = float(user_state["withdrawable"])
    print(f'Available balance: ${balance:,.2f}')
    return balance

def get_all_positions(account):
    """Get all open positions - uses cached connection for speed"""
    info = get_cached_info()
    user_state = info.user_state(account.address)

    positions = []
    for position in user_state["assetPositions"]:
        if float(position["position"]["szi"]) != 0:
            positions.append({
                'symbol': position["position"]["coin"],
                'size': float(position["position"]["szi"]),
                'entry_price': float(position["position"]["entryPx"]),
                'pnl_percent': float(position["position"]["returnOnEquity"]) * 100,
                'is_long': float(position["position"]["szi"]) > 0
            })

    return positions


def close_all_positions(account):
    """ULTRA FAST close all positions - single API call per position using market_close()"""
    print(colored('🔪 CLOSING ALL POSITIONS', 'red', attrs=['bold']))

    exchange = get_cached_exchange(account)
    info = get_cached_info()

    # Get all positions in one API call
    user_state = info.user_state(account.address)
    positions = [p for p in user_state["assetPositions"] if float(p["position"]["szi"]) != 0]

    if not positions:
        print(colored('✅ No positions to close', 'green'))
        return []

    print(f'   Found {len(positions)} position(s)')

    results = []
    for pos in positions:
        symbol = pos["position"]["coin"]
        size = float(pos["position"]["szi"])
        direction = "LONG" if size > 0 else "SHORT"

        # Use market_close() - fastest method (single API call)
        result = exchange.market_close(symbol)

        if result.get('status') == 'ok':
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'filled' in statuses[0]:
                filled = statuses[0]['filled']
                print(colored(f'   ✅ {symbol} {direction} closed @ ${filled.get("avgPx", "?")}', 'green'))
            else:
                print(colored(f'   ✅ {symbol} closed', 'green'))
        else:
            print(colored(f'   ⚠️ {symbol}: {result}', 'yellow'))

        results.append({'symbol': symbol, 'result': result})

    print(colored('✅ All positions closed', 'green', attrs=['bold']))
    return results

# ============================================================================
# ADDITIONAL HELPER FUNCTIONS (from nice_funcs_hl.py)
# ============================================================================

def _get_exchange():
    """Get exchange instance"""
    private_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
    if not private_key:
        raise ValueError("HYPER_LIQUID_ETH_PRIVATE_KEY not found in .env file")
    account = eth_account.Account.from_key(private_key)
    return Exchange(account, constants.MAINNET_API_URL)

def _get_info():
    """Get info instance"""
    return Info(constants.MAINNET_API_URL, skip_ws=True)

def _get_account_from_env():
    """Initialize and return HyperLiquid account from env"""
    private_key = os.getenv('HYPER_LIQUID_ETH_PRIVATE_KEY')
    if not private_key:
        raise ValueError("HYPER_LIQUID_ETH_PRIVATE_KEY not found in .env file")
    return eth_account.Account.from_key(private_key)

# ============================================================================
# OHLCV DATA FUNCTIONS
# ============================================================================

def _get_ohlcv(symbol, interval, start_time, end_time, batch_size=BATCH_SIZE):
    """Internal function to fetch OHLCV data from Hyperliquid"""
    global timestamp_offset

    # HyperLiquid API requires lowercase intervals (e.g., '1h' not '1H')
    interval = interval.lower()

    print(f'\n🔍 Requesting data for {symbol}:')
    print(f'📊 Batch Size: {batch_size}')
    print(f'⏰ Interval: {interval}')
    print(f'🚀 Start: {start_time.strftime("%Y-%m-%d %H:%M:%S")} UTC')
    print(f'🎯 End: {end_time.strftime("%Y-%m-%d %H:%M:%S")} UTC')

    start_ts = int(start_time.timestamp() * 1000)
    end_ts = int(end_time.timestamp() * 1000)

    # Build request payload
    request_payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": symbol,
            "interval": interval,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": batch_size
        }
    }

    print(f'\n📤 API Request Payload:')
    print(f'   URL: {BASE_URL}')
    print(f'   Payload: {request_payload}')

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                BASE_URL,
                headers={'Content-Type': 'application/json'},
                json=request_payload,
                timeout=10
            )

            print(f'\n📥 API Response:')
            print(f'   Status Code: {response.status_code}')
            print(f'   Response Text: {response.text[:500]}...' if len(response.text) > 500 else f'   Response Text: {response.text}')

            if response.status_code == 200:
                snapshot_data = response.json()
                if snapshot_data:
                    # Handle timestamp offset
                    if timestamp_offset is None:
                        latest_api_timestamp = datetime.datetime.utcfromtimestamp(snapshot_data[-1]['t'] / 1000)
                        system_current_date = datetime.datetime.utcnow()
                        expected_latest_timestamp = system_current_date
                        timestamp_offset = latest_api_timestamp - expected_latest_timestamp
                        print(f"⏱️ Calculated timestamp offset: {timestamp_offset}")

                    # Adjust timestamps
                    for candle in snapshot_data:
                        dt = datetime.datetime.utcfromtimestamp(candle['t'] / 1000)
                        adjusted_dt = adjust_timestamp(dt)
                        candle['t'] = int(adjusted_dt.timestamp() * 1000)

                    first_time = datetime.datetime.utcfromtimestamp(snapshot_data[0]['t'] / 1000)
                    last_time = datetime.datetime.utcfromtimestamp(snapshot_data[-1]['t'] / 1000)
                    print(f'✨ Received {len(snapshot_data)} candles')
                    print(f'📈 First: {first_time}')
                    print(f'📉 Last: {last_time}')
                    return snapshot_data
                print('❌ No data returned by API')
                return None

            print(f'\n⚠️ HTTP Error {response.status_code}')
            print(f'❌ Error details: {response.text}')

            # Try to parse error as JSON for better readability
            try:
                error_json = response.json()
                print(f'📋 Parsed error: {error_json}')
            except:
                pass

        except requests.exceptions.RequestException as e:
            print(f'\n⚠️ Request failed (attempt {attempt + 1}): {e}')
            import traceback
            traceback.print_exc()
            time.sleep(1)
        except Exception as e:
            print(f'\n❌ Unexpected error (attempt {attempt + 1}): {e}')
            import traceback
            traceback.print_exc()
            time.sleep(1)

    print('\n❌ All retry attempts failed')
    return None

def _process_data_to_df(snapshot_data):
    """Convert raw API data to DataFrame"""
    if snapshot_data:
        columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        data = []
        for snapshot in snapshot_data:
            timestamp = datetime.datetime.utcfromtimestamp(snapshot['t'] / 1000)
            # Convert all numeric values to float
            data.append([
                timestamp,
                float(snapshot['o']),
                float(snapshot['h']),
                float(snapshot['l']),
                float(snapshot['c']),
                float(snapshot['v'])
            ])
        df = pd.DataFrame(data, columns=columns)

        # Ensure numeric columns are float64
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype('float64')

        print("\n📊 OHLCV Data Types:")
        print(df.dtypes)

        print("\n📈 First 5 rows of data:")
        print(df.head())

        return df
    return pd.DataFrame()

def add_technical_indicators(df):
    """Add technical indicators to the dataframe

    Optimized indicator set:
    - TIER 1 (Essential): SMA, RSI, MACD, ATR, ADX, OBV, Volume Ratio
    - TIER 2 (Useful): Bollinger, VWAP, Fibonacci (200-bar)
    - TIER 3 (Disabled in config but still calculated): Stochastic, Williams %R, CCI
    """
    if df.empty:
        return df

    try:
        print("\n🔧 Adding technical indicators...")

        # Ensure numeric columns are float64
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype('float64')

        # ============================================================
        # TIER 1: Essential Indicators
        # ============================================================

        # Moving Averages - Trend Analysis
        df['sma_20'] = ta.sma(df['close'], length=20)
        df['sma_50'] = ta.sma(df['close'], length=50)
        df['sma_200'] = ta.sma(df['close'], length=200)
        df['ema_12'] = ta.ema(df['close'], length=12)
        df['ema_26'] = ta.ema(df['close'], length=26)

        # RSI - THE overbought/oversold indicator
        df['rsi'] = ta.rsi(df['close'], length=14)

        # MACD - Momentum + Crossovers
        macd = ta.macd(df['close'])
        df = pd.concat([df, macd], axis=1)

        # ATR - Volatility for stops/position sizing
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        # ATR as percentage of price (for volatility regime detection)
        df['atr_pct'] = (df['atr'] / df['close']) * 100

        # ADX - Trend Strength (>25 = strong trend)
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        df = pd.concat([df, adx], axis=1)

        # OBV - Volume Trend Confirmation
        df['obv'] = ta.obv(df['close'], df['volume'])
        df['obv_sma'] = ta.sma(df['obv'], length=20)  # OBV trend line

        # Volume Ratio - Volume vs 20-period average (>1.5 = spike)
        df['volume_sma'] = ta.sma(df['volume'], length=20)
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)

        # Price Change Percentage (for quick momentum reference)
        df['price_change_1'] = df['close'].pct_change(periods=1) * 100   # 1-bar change
        df['price_change_4'] = df['close'].pct_change(periods=4) * 100   # 4-bar change
        df['price_change_24'] = df['close'].pct_change(periods=24) * 100 # 24-bar change (1 day on 1H)

        # ============================================================
        # TIER 2: Useful Indicators
        # ============================================================

        # Bollinger Bands - Squeeze/Volatility Detection
        bbands = ta.bbands(df['close'])
        df = pd.concat([df, bbands], axis=1)

        # Bollinger Band Width (for squeeze detection)
        bb_upper_col = [c for c in df.columns if 'BBU' in c]
        bb_lower_col = [c for c in df.columns if 'BBL' in c]
        bb_mid_col = [c for c in df.columns if 'BBM' in c]
        if bb_upper_col and bb_lower_col and bb_mid_col:
            df['bb_width'] = (df[bb_upper_col[0]] - df[bb_lower_col[0]]) / df[bb_mid_col[0]] * 100

        # VWAP - Institutional Reference Level
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])

        # Fibonacci Retracement Levels (200-bar lookback for significant levels)
        lookback = min(200, len(df))  # Increased from 50 to 200 for better levels
        recent_high = df['high'].tail(lookback).max()
        recent_low = df['low'].tail(lookback).min()
        fib_range = recent_high - recent_low

        df['fib_high'] = recent_high
        df['fib_low'] = recent_low
        df['fib_236'] = recent_high - (fib_range * 0.236)  # 23.6% retracement
        df['fib_382'] = recent_high - (fib_range * 0.382)  # 38.2% retracement
        df['fib_500'] = recent_high - (fib_range * 0.500)  # 50% retracement
        df['fib_618'] = recent_high - (fib_range * 0.618)  # 61.8% retracement (golden ratio)
        df['fib_786'] = recent_high - (fib_range * 0.786)  # 78.6% retracement

        # ============================================================
        # HIGH-VALUE SIGNALS: Divergence, S/R, Market Regime
        # ============================================================

        # --- RSI DIVERGENCE DETECTION ---
        # Bullish divergence: Price makes lower low, RSI makes higher low
        # Bearish divergence: Price makes higher high, RSI makes lower high
        lookback_div = 14  # Lookback period for divergence detection
        df['rsi_divergence'] = 'NONE'
        df['rsi_divergence_strength'] = 0

        if len(df) >= lookback_div + 5:
            for i in range(lookback_div + 5, len(df)):
                # Get recent window
                price_window = df['close'].iloc[i-lookback_div:i+1]
                rsi_window = df['rsi'].iloc[i-lookback_div:i+1]

                if rsi_window.isna().any():
                    continue

                # Find local minima/maxima in price
                price_min_idx = price_window.idxmin()
                price_max_idx = price_window.idxmax()
                current_price = price_window.iloc[-1]
                current_rsi = rsi_window.iloc[-1]

                # Check for bullish divergence (price lower low, RSI higher low)
                recent_lows = price_window.nsmallest(3)
                if len(recent_lows) >= 2:
                    if current_price <= recent_lows.iloc[0] * 1.01:  # Near recent low
                        # Check if RSI is making higher low
                        price_at_prev_low = recent_lows.iloc[1]
                        prev_low_idx = price_window[price_window == price_at_prev_low].index[0]
                        if prev_low_idx in rsi_window.index:
                            rsi_at_prev_low = df.loc[prev_low_idx, 'rsi']
                            if not pd.isna(rsi_at_prev_low) and current_rsi > rsi_at_prev_low + 3:
                                df.loc[df.index[i], 'rsi_divergence'] = 'BULLISH'
                                df.loc[df.index[i], 'rsi_divergence_strength'] = current_rsi - rsi_at_prev_low

                # Check for bearish divergence (price higher high, RSI lower high)
                recent_highs = price_window.nlargest(3)
                if len(recent_highs) >= 2:
                    if current_price >= recent_highs.iloc[0] * 0.99:  # Near recent high
                        # Check if RSI is making lower high
                        price_at_prev_high = recent_highs.iloc[1]
                        prev_high_idx = price_window[price_window == price_at_prev_high].index[0]
                        if prev_high_idx in rsi_window.index:
                            rsi_at_prev_high = df.loc[prev_high_idx, 'rsi']
                            if not pd.isna(rsi_at_prev_high) and current_rsi < rsi_at_prev_high - 3:
                                df.loc[df.index[i], 'rsi_divergence'] = 'BEARISH'
                                df.loc[df.index[i], 'rsi_divergence_strength'] = rsi_at_prev_high - current_rsi

        # --- OBV DIVERGENCE DETECTION ---
        # Bullish: Price down/flat, OBV up (accumulation)
        # Bearish: Price up/flat, OBV down (distribution)
        df['obv_divergence'] = 'NONE'

        if len(df) >= 20:
            for i in range(20, len(df)):
                price_change_10 = (df['close'].iloc[i] - df['close'].iloc[i-10]) / df['close'].iloc[i-10] * 100
                obv_change_10 = df['obv'].iloc[i] - df['obv'].iloc[i-10]
                obv_sma_current = df['obv_sma'].iloc[i] if not pd.isna(df['obv_sma'].iloc[i]) else 0
                obv_sma_prev = df['obv_sma'].iloc[i-10] if not pd.isna(df['obv_sma'].iloc[i-10]) else 0
                obv_trend = obv_sma_current - obv_sma_prev

                # Bullish divergence: Price down but OBV up (smart money accumulating)
                if price_change_10 < -2 and obv_trend > 0:
                    df.loc[df.index[i], 'obv_divergence'] = 'BULLISH'
                # Bearish divergence: Price up but OBV down (smart money distributing)
                elif price_change_10 > 2 and obv_trend < 0:
                    df.loc[df.index[i], 'obv_divergence'] = 'BEARISH'

        # --- SWING HIGH/LOW SUPPORT & RESISTANCE ---
        # Find significant swing points as actual S/R levels
        swing_lookback = 5  # Bars on each side to confirm swing

        df['swing_high'] = None
        df['swing_low'] = None
        df['nearest_resistance'] = None
        df['nearest_support'] = None
        df['distance_to_resistance_pct'] = None
        df['distance_to_support_pct'] = None

        swing_highs = []
        swing_lows = []

        if len(df) >= swing_lookback * 2 + 1:
            for i in range(swing_lookback, len(df) - swing_lookback):
                # Check for swing high
                is_swing_high = True
                for j in range(1, swing_lookback + 1):
                    if df['high'].iloc[i] <= df['high'].iloc[i-j] or df['high'].iloc[i] <= df['high'].iloc[i+j]:
                        is_swing_high = False
                        break
                if is_swing_high:
                    swing_highs.append((i, df['high'].iloc[i]))
                    df.loc[df.index[i], 'swing_high'] = df['high'].iloc[i]

                # Check for swing low
                is_swing_low = True
                for j in range(1, swing_lookback + 1):
                    if df['low'].iloc[i] >= df['low'].iloc[i-j] or df['low'].iloc[i] >= df['low'].iloc[i+j]:
                        is_swing_low = False
                        break
                if is_swing_low:
                    swing_lows.append((i, df['low'].iloc[i]))
                    df.loc[df.index[i], 'swing_low'] = df['low'].iloc[i]

            # Calculate nearest S/R for the last bar
            if swing_highs and swing_lows:
                current_price = df['close'].iloc[-1]

                # Get recent swing highs above current price (resistance)
                resistances = [h[1] for h in swing_highs if h[1] > current_price]
                if resistances:
                    nearest_resistance = min(resistances)
                    df.loc[df.index[-1], 'nearest_resistance'] = nearest_resistance
                    df.loc[df.index[-1], 'distance_to_resistance_pct'] = ((nearest_resistance - current_price) / current_price) * 100

                # Get recent swing lows below current price (support)
                supports = [l[1] for l in swing_lows if l[1] < current_price]
                if supports:
                    nearest_support = max(supports)
                    df.loc[df.index[-1], 'nearest_support'] = nearest_support
                    df.loc[df.index[-1], 'distance_to_support_pct'] = ((current_price - nearest_support) / current_price) * 100

        # --- MARKET REGIME CLASSIFICATION ---
        # TRENDING_UP: ADX > 25 AND price making higher highs/higher lows
        # TRENDING_DOWN: ADX > 25 AND price making lower highs/lower lows
        # RANGING: ADX < 20 OR price oscillating
        # BREAKOUT: BB squeeze ending + volume spike
        df['market_regime'] = 'UNKNOWN'
        df['regime_strength'] = 0

        if len(df) >= 20:
            for i in range(20, len(df)):
                adx_val = df['ADX_14'].iloc[i] if 'ADX_14' in df.columns and not pd.isna(df['ADX_14'].iloc[i]) else 0
                bb_width_val = df['bb_width'].iloc[i] if 'bb_width' in df.columns and not pd.isna(df['bb_width'].iloc[i]) else 10
                vol_ratio = df['volume_ratio'].iloc[i] if not pd.isna(df['volume_ratio'].iloc[i]) else 1

                # Check price structure (higher highs/lows or lower highs/lows)
                recent_highs = df['high'].iloc[i-10:i+1]
                recent_lows = df['low'].iloc[i-10:i+1]

                # Simple HH/HL or LH/LL detection
                hh_count = sum(1 for j in range(1, len(recent_highs)) if recent_highs.iloc[j] > recent_highs.iloc[j-1])
                ll_count = sum(1 for j in range(1, len(recent_lows)) if recent_lows.iloc[j] < recent_lows.iloc[j-1])

                # Classify regime
                if bb_width_val < 3 and vol_ratio > 1.5:  # Squeeze breakout
                    df.loc[df.index[i], 'market_regime'] = 'BREAKOUT'
                    df.loc[df.index[i], 'regime_strength'] = vol_ratio
                elif adx_val > 25:
                    if hh_count >= 6:  # More higher highs
                        df.loc[df.index[i], 'market_regime'] = 'TRENDING_UP'
                        df.loc[df.index[i], 'regime_strength'] = adx_val
                    elif ll_count >= 6:  # More lower lows
                        df.loc[df.index[i], 'market_regime'] = 'TRENDING_DOWN'
                        df.loc[df.index[i], 'regime_strength'] = adx_val
                    else:
                        df.loc[df.index[i], 'market_regime'] = 'TRENDING'
                        df.loc[df.index[i], 'regime_strength'] = adx_val
                elif adx_val < 20:
                    df.loc[df.index[i], 'market_regime'] = 'RANGING'
                    df.loc[df.index[i], 'regime_strength'] = 20 - adx_val
                else:
                    df.loc[df.index[i], 'market_regime'] = 'TRANSITIONING'
                    df.loc[df.index[i], 'regime_strength'] = adx_val

        # ============================================================
        # TIER 3: Legacy Indicators (calculated for compatibility, disabled in AI)
        # ============================================================

        # Stochastic Oscillator (redundant with RSI)
        stoch = ta.stoch(df['high'], df['low'], df['close'])
        df = pd.concat([df, stoch], axis=1)

        # Williams %R (redundant with RSI)
        df['willr'] = ta.willr(df['high'], df['low'], df['close'], length=14)

        # CCI (noisy signals)
        df['cci'] = ta.cci(df['high'], df['low'], df['close'], length=20)

        print("✅ Technical indicators added (Optimized + High-Value Signals: Divergence, S/R, Regime)")
        return df

    except Exception as e:
        print(f"❌ Error adding technical indicators: {str(e)}")
        traceback.print_exc()
        return df

def get_data(symbol, timeframe='15m', bars=100, add_indicators=True):
    """
    🌙 Moon Dev's Hyperliquid Data Fetcher

    Args:
        symbol (str): Trading pair symbol (e.g., 'BTC', 'ETH')
        timeframe (str): Candle timeframe (default: '15m')
        bars (int): Number of bars to fetch (default: 100, max: 5000)
        add_indicators (bool): Whether to add technical indicators

    Returns:
        pd.DataFrame: OHLCV data with columns [timestamp, open, high, low, close, volume]
                     and technical indicators if requested
    """
    print("\n🌙 Moon Dev's Hyperliquid Data Fetcher")
    print(f"🎯 Symbol: {symbol}")
    print(f"⏰ Timeframe: {timeframe}")
    print(f"📊 Requested bars: {min(bars, MAX_ROWS)}")

    # Ensure we don't exceed max rows
    bars = min(bars, MAX_ROWS)

    # Calculate time window
    end_time = datetime.datetime.utcnow()
    # Add extra time to ensure we get enough bars
    start_time = end_time - timedelta(days=60)

    data = _get_ohlcv(symbol, timeframe, start_time, end_time, batch_size=bars)

    if not data:
        print("❌ No data available.")
        return pd.DataFrame()

    df = _process_data_to_df(data)

    if not df.empty:
        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)

        # Add technical indicators BEFORE cutting to requested bars
        # This ensures indicators have enough history to calculate
        if add_indicators:
            df = add_technical_indicators(df)

        # Now get the most recent bars (after indicators are calculated)
        df = df.tail(bars).reset_index(drop=True)

        print("\n📊 Data summary:")
        print(f"📈 Total candles: {len(df)}")
        print(f"📅 Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print("✨ Thanks for using Moon Dev's Data Fetcher! ✨")

    return df

# ============================================================================
# MULTI-TIMEFRAME ANALYSIS
# ============================================================================

def get_mtf_analysis(symbol, timeframes=['5m', '15m', '1h', '4h']):
    """
    🌙 Multi-Timeframe Analysis

    Fetches data across multiple timeframes and calculates trend alignment.

    Args:
        symbol: Trading pair (e.g., 'BTC')
        timeframes: List of timeframes to analyze

    Returns:
        dict with MTF analysis including alignment score and per-timeframe trends
    """
    print(f"\n📊 Multi-Timeframe Analysis for {symbol}")

    mtf_data = {}

    for tf in timeframes:
        try:
            # Fetch data with indicators (quietly)
            df = get_data(symbol, timeframe=tf, bars=100, add_indicators=True)

            if df.empty or len(df) < 20:
                mtf_data[tf] = {'trend': 'UNKNOWN', 'strength': 0}
                continue

            latest = df.iloc[-1]

            # Determine trend for this timeframe
            trend = 'NEUTRAL'
            strength = 0

            # Price vs SMAs
            price = latest['close']
            sma_20 = latest.get('sma_20', price)
            sma_50 = latest.get('sma_50', price)
            sma_200 = latest.get('sma_200', price)

            # Count bullish/bearish signals
            bullish_signals = 0
            bearish_signals = 0

            # SMA alignment
            if price > sma_20:
                bullish_signals += 1
            else:
                bearish_signals += 1

            if price > sma_50:
                bullish_signals += 1
            else:
                bearish_signals += 1

            if sma_20 > sma_50:
                bullish_signals += 1
            else:
                bearish_signals += 1

            # RSI
            rsi = latest.get('rsi', 50)
            if rsi > 50:
                bullish_signals += 1
            elif rsi < 50:
                bearish_signals += 1

            # MACD
            macd = latest.get('macd', 0)
            macd_signal = latest.get('macd_signal', 0)
            if macd > macd_signal:
                bullish_signals += 1
            else:
                bearish_signals += 1

            # ADX for trend strength
            adx = latest.get('adx', 20)

            # Determine trend
            total_signals = bullish_signals + bearish_signals
            if total_signals > 0:
                bull_pct = bullish_signals / total_signals
                if bull_pct >= 0.7:
                    trend = 'BULLISH'
                    strength = int(bull_pct * 100)
                elif bull_pct <= 0.3:
                    trend = 'BEARISH'
                    strength = int((1 - bull_pct) * 100)
                else:
                    trend = 'NEUTRAL'
                    strength = 50

            # Boost strength if ADX shows strong trend
            if adx > 25:
                strength = min(100, strength + 10)

            mtf_data[tf] = {
                'trend': trend,
                'strength': strength,
                'price': price,
                'sma_20': sma_20,
                'sma_50': sma_50,
                'rsi': rsi,
                'adx': adx
            }

        except Exception as e:
            print(f"  ⚠️ Error fetching {tf}: {e}")
            mtf_data[tf] = {'trend': 'UNKNOWN', 'strength': 0}

    # Calculate overall alignment
    trends = [mtf_data[tf]['trend'] for tf in timeframes if mtf_data[tf]['trend'] != 'UNKNOWN']

    bullish_count = sum(1 for t in trends if t == 'BULLISH')
    bearish_count = sum(1 for t in trends if t == 'BEARISH')
    total_count = len(trends)

    if total_count == 0:
        alignment = 'UNKNOWN'
        alignment_score = 0
        alignment_pct = 0
    elif bullish_count == total_count:
        alignment = 'STRONG_BULLISH'
        alignment_score = 100
        alignment_pct = 100
    elif bearish_count == total_count:
        alignment = 'STRONG_BEARISH'
        alignment_score = -100
        alignment_pct = 100
    elif bullish_count > bearish_count:
        alignment = 'BULLISH'
        alignment_score = int((bullish_count / total_count) * 100)
        alignment_pct = int((bullish_count / total_count) * 100)
    elif bearish_count > bullish_count:
        alignment = 'BEARISH'
        alignment_score = -int((bearish_count / total_count) * 100)
        alignment_pct = int((bearish_count / total_count) * 100)
    else:
        alignment = 'MIXED'
        alignment_score = 0
        alignment_pct = 50

    result = {
        'symbol': symbol,
        'timeframes': mtf_data,
        'alignment': alignment,
        'alignment_score': alignment_score,
        'alignment_pct': alignment_pct,
        'bullish_tfs': bullish_count,
        'bearish_tfs': bearish_count,
        'total_tfs': total_count
    }

    # Print summary
    print(f"\n  📈 MTF Summary for {symbol}:")
    for tf in timeframes:
        data = mtf_data.get(tf, {})
        trend = data.get('trend', 'UNKNOWN')
        strength = data.get('strength', 0)
        emoji = '🟢' if trend == 'BULLISH' else '🔴' if trend == 'BEARISH' else '⚪'
        print(f"    {tf:>4}: {emoji} {trend:<10} (strength: {strength}%)")

    align_emoji = '🟢🟢' if 'STRONG_BULLISH' in alignment else '🔴🔴' if 'STRONG_BEARISH' in alignment else '🟢' if 'BULLISH' in alignment else '🔴' if 'BEARISH' in alignment else '⚪'
    print(f"\n  🎯 Overall: {align_emoji} {alignment} ({alignment_pct}% aligned)")

    return result


# ============================================================================
# MARKET INFO FUNCTIONS
# ============================================================================

def get_market_info():
    """Get current market info for all coins on Hyperliquid"""
    try:
        print("\n🔄 Sending request to Hyperliquid API...")
        response = requests.post(
            BASE_URL,
            headers={'Content-Type': 'application/json'},
            json={"type": "allMids"}
        )

        print(f"📡 Response status code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"📦 Raw response data: {data}")
            return data
        print(f"❌ Bad status code: {response.status_code}")
        print(f"📄 Response text: {response.text}")
        return None
    except Exception as e:
        print(f"❌ Error getting market info: {str(e)}")
        traceback.print_exc()
        return None

def test_market_info():
    print("\n💹 Testing Market Info...")
    try:
        print("🎯 Fetching current market prices...")
        info = get_market_info()

        print(f"\n📊 Response type: {type(info)}")
        if info is not None:
            print(f"📝 Response content: {info}")

        if info and isinstance(info, dict):
            print("\n💰 Current Market Prices:")
            print("=" * 50)
            # Target symbols we're interested in
            target_symbols = ["BTC", "ETH", "SOL", "ARB", "OP", "MATIC"]

            for symbol in target_symbols:
                if symbol in info:
                    try:
                        price = float(info[symbol])
                        print(f"Symbol: {symbol:8} | Price: ${price:,.2f}")
                    except (ValueError, TypeError) as e:
                        print(f"⚠️ Error processing price for {symbol}: {str(e)}")
                else:
                    print(f"⚠️ No price data for {symbol}")
        else:
            print("❌ No valid market info received")
            if info is None:
                print("📛 Response was None")
            else:
                print(f"❓ Unexpected response type: {type(info)}")
    except Exception as e:
        print(f"❌ Error in market info test: {str(e)}")
        print(f"🔍 Full error traceback:")
        traceback.print_exc()

# ============================================================================
# FUNDING RATE FUNCTIONS
# ============================================================================

def get_funding_rates(symbol):
    """
    Get current funding rate for a specific coin on Hyperliquid

    Args:
        symbol (str): Trading pair symbol (e.g., 'BTC', 'ETH', 'FARTCOIN')

    Returns:
        dict: Funding data including rate, mark price, and open interest
    """
    try:
        print(f"\n🔄 Fetching funding rate for {symbol}...")
        response = requests.post(
            BASE_URL,
            headers={'Content-Type': 'application/json'},
            json={"type": "metaAndAssetCtxs"}
        )

        if response.status_code == 200:
            data = response.json()
            if len(data) >= 2 and isinstance(data[0], dict) and isinstance(data[1], list):
                # Get universe (symbols) from first element
                universe = {coin['name']: i for i, coin in enumerate(data[0]['universe'])}

                # Check if symbol exists
                if symbol not in universe:
                    print(f"❌ Symbol {symbol} not found in Hyperliquid universe")
                    print(f"📝 Available symbols: {', '.join(universe.keys())}")
                    return None

                # Get funding data from second element
                funding_data = data[1]
                idx = universe[symbol]

                if idx < len(funding_data):
                    asset_data = funding_data[idx]
                    return {
                        'funding_rate': float(asset_data['funding']),
                        'mark_price': float(asset_data['markPx']),
                        'open_interest': float(asset_data['openInterest'])
                    }

            print("❌ Unexpected response format")
            return None
        print(f"❌ Bad status code: {response.status_code}")
        return None
    except Exception as e:
        print(f"❌ Error getting funding rate for {symbol}: {str(e)}")
        traceback.print_exc()
        return None

def test_funding_rates():
    print("\n💸 Testing Funding Rates...")
    try:
        # Test with some interesting symbols
        test_symbols = ["BTC", "ETH", "SOL"]

        for symbol in test_symbols:
            print(f"\n📊 Testing {symbol}:")
            print("=" * 50)
            data = get_funding_rates(symbol)

            if data:
                # The API returns the 8-hour funding rate
                # To get hourly rate: funding_rate
                # To get annual rate: hourly * 24 * 365
                hourly_rate = float(data['funding_rate']) * 100  # Convert to percentage
                annual_rate = hourly_rate * 24 * 365  # Convert hourly to annual

                print(f"Symbol: {symbol:8} | Hourly: {hourly_rate:7.4f}% | Annual: {annual_rate:7.2f}% | OI: {data['open_interest']:10.2f}")
            else:
                print(f"❌ No funding data received for {symbol}")

    except Exception as e:
        print(f"❌ Error in funding rates test: {str(e)}")
        print(f"🔍 Full error traceback:")
        traceback.print_exc()

# ============================================================================
# ADDITIONAL TRADING FUNCTIONS
# ============================================================================

def get_token_balance_usd(token_mint_address, account):
    """Get USD value of current position

    Args:
        token_mint_address: Token symbol (e.g., 'BTC', 'ETH')
        account: HyperLiquid account object

    Returns:
        float: USD value of position (absolute value)
    """
    try:
        positions, im_in_pos, pos_size, _, _, _, _ = get_position(token_mint_address, account)
        if not im_in_pos:
            return 0

        # Get current price
        mid_price = get_current_price(token_mint_address)
        return abs(float(pos_size) * mid_price)
    except Exception as e:
        cprint(f"❌ Error getting balance for {token_mint_address}: {e}", "red")
        return 0

def ai_entry(symbol, amount, max_chunk_size=None, leverage=DEFAULT_LEVERAGE, account=None):
    """Smart entry (HyperLiquid doesn't need chunking)

    Args:
        symbol: Token symbol
        amount: Total USD amount to invest
        max_chunk_size: Ignored (kept for compatibility)
        leverage: Leverage multiplier
        account: HyperLiquid account object (optional, will create from env if not provided)

    Returns:
        bool: True if successful
    """
    if account is None:
        account = _get_account_from_env()

    # Set leverage
    set_leverage(symbol, leverage, account)

    result = market_buy(symbol, amount, account)
    return result is not None

def open_short(token, amount, slippage=None, leverage=DEFAULT_LEVERAGE, account=None, auto_tpsl=True, tp_pct=10.0, sl_pct=3.0):
    """Open SHORT position explicitly with automatic TP/SL

    Args:
        token: Token symbol
        amount: USD NOTIONAL position size
        slippage: Not used (kept for compatibility)
        leverage: Leverage multiplier
        account: HyperLiquid account object (optional, will create from env if not provided)
        auto_tpsl: Automatically set TP/SL orders (default True)
        tp_pct: Take profit percentage (default 10%)
        sl_pct: Stop loss percentage (default 3%)

    Returns:
        dict: Order response
    """
    if account is None:
        account = _get_account_from_env()

    try:
        # Set leverage
        set_leverage(token, leverage, account)

        # Get current ask price
        ask, bid, _ = ask_bid(token)

        # Overbid to ensure fill (market short needs to sell below current price)
        # But we're opening a short, so we sell, which means we want to sell below bid
        sell_price = bid * 0.999

        # Round to appropriate decimals
        if token == 'BTC':
            sell_price = round(sell_price)
        else:
            sell_price = round(sell_price, 1)

        # Calculate quantity
        pos_size = amount / sell_price

        # Get decimals and round
        sz_decimals, _ = get_sz_px_decimals(token)
        pos_size = round(pos_size, sz_decimals)

        # Calculate required margin
        required_margin = amount / leverage

        print(colored(f'📉 Opening SHORT: {pos_size} {token} @ ${sell_price}', 'red'))
        print(colored(f'💰 Notional Position: ${amount:.2f} | Margin Required: ${required_margin:.2f} ({leverage}x)', 'cyan'))

        # Place market sell to open short - use cached exchange for speed
        exchange = get_cached_exchange(account)
        order_result = exchange.order(token, False, pos_size, sell_price, {"limit": {"tif": "Ioc"}}, reduce_only=False)

        print(colored(f'✅ Short position opened!', 'green'))

        # Auto set TP/SL if enabled and order was filled
        if auto_tpsl and order_result and order_result.get('status') == 'ok':
            statuses = order_result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'filled' in statuses[0]:
                print(colored(f'🎯 Auto-setting TP/SL (TP: +{tp_pct}%, SL: -{sl_pct}%)', 'cyan'))
                try:
                    time.sleep(0.1)  # Minimal pause (reduced from 0.5s)
                    # Get FULL position (not just this fill) for correct TP/SL sizing
                    positions, im_in_pos, total_size, pos_sym, avg_entry, pnl_pct, is_long = get_position(token, account)
                    if im_in_pos:
                        # Use total position size and average entry for TP/SL
                        place_tp_sl_orders(token, float(avg_entry), abs(float(total_size)), is_long, tp_pct, sl_pct, account)
                    else:
                        # Fallback to fill data if position query fails
                        filled = statuses[0]['filled']
                        entry_px = float(filled.get('avgPx', sell_price))
                        filled_sz = float(filled.get('totalSz', pos_size))
                        place_tp_sl_orders(token, entry_px, filled_sz, False, tp_pct, sl_pct, account)
                except Exception as e:
                    print(colored(f'⚠️ Failed to set TP/SL: {e}', 'yellow'))

        return order_result

    except Exception as e:
        print(colored(f'❌ Error opening short: {e}', 'red'))
        traceback.print_exc()
        return None

# Initialize on import
print("✨ HyperLiquid trading functions loaded successfully!")