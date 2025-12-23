"""
Backtesting Module for CryptoVerge Trading Bot
Simulates trading strategies on historical data
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import json
import pandas as pd
import numpy as np
from termcolor import cprint

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

# Import trading agent settings
from src.agents.trading_agent import (
    LEVERAGE, STOP_LOSS_PERCENTAGE, TAKE_PROFIT_PERCENTAGE,
    MIN_CONFIDENCE_TO_TRADE, USE_TRAILING_STOP,
    TRAILING_STOP_ACTIVATION, TRAILING_STOP_DISTANCE,
    USE_DYNAMIC_SIZING, DYNAMIC_SIZE_MIN_PCT, DYNAMIC_SIZE_MAX_PCT,
    MAX_POSITION_PERCENTAGE, LONG_ONLY
)

# Backtesting Configuration
BACKTEST_CONFIG = {
    'initial_balance': 1000,      # Starting balance in USD
    'symbols': ['BTC', 'ETH'],    # Symbols to backtest
    'start_date': '2024-01-01',   # Start date (YYYY-MM-DD)
    'end_date': '2024-12-01',     # End date
    'timeframe': '4H',            # Candlestick timeframe (4H = less noise, stronger signals)
    'trading_fee': 0.0006,        # 0.06% per trade (HyperLiquid maker fee)
    'slippage': 0.001,            # 0.1% slippage estimate
}

# Results storage
BACKTEST_RESULTS_DIR = PROJECT_ROOT / "src" / "data" / "backtest_results"
BACKTEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class BacktestEngine:
    """Backtesting engine for simulating trading strategies"""

    def __init__(self, config=None):
        self.config = config or BACKTEST_CONFIG
        self.balance = self.config['initial_balance']
        self.initial_balance = self.config['initial_balance']
        self.positions = {}  # {symbol: {'size': float, 'entry_price': float, 'side': str}}
        self.trades = []  # List of completed trades
        self.equity_curve = []  # [(timestamp, equity)]
        self.highest_pnl = {}  # For trailing stops {symbol: highest_pnl_pct}

    def calculate_position_size(self, confidence):
        """Calculate position size based on confidence (mirrors live logic)"""
        if USE_DYNAMIC_SIZING and confidence is not None:
            confidence_range = 100 - MIN_CONFIDENCE_TO_TRADE
            confidence_above_min = confidence - MIN_CONFIDENCE_TO_TRADE
            confidence_ratio = max(0, min(1, confidence_above_min / confidence_range))
            position_pct = DYNAMIC_SIZE_MIN_PCT + (DYNAMIC_SIZE_MAX_PCT - DYNAMIC_SIZE_MIN_PCT) * confidence_ratio
        else:
            position_pct = MAX_POSITION_PERCENTAGE

        margin = self.balance * (position_pct / 100)
        notional = margin * LEVERAGE
        return notional, margin

    def open_position(self, symbol, side, price, confidence, timestamp):
        """Open a new position"""
        if symbol in self.positions:
            return False  # Already have a position

        notional, margin = self.calculate_position_size(confidence)

        # Apply slippage
        if side == 'LONG':
            entry_price = price * (1 + self.config['slippage'])
        else:
            entry_price = price * (1 - self.config['slippage'])

        # Calculate size in tokens
        size = notional / entry_price

        # Deduct trading fee from balance
        fee = notional * self.config['trading_fee']
        self.balance -= fee

        self.positions[symbol] = {
            'size': size,
            'entry_price': entry_price,
            'side': side,
            'margin': margin,
            'notional': notional,
            'open_time': timestamp,
            'confidence': confidence
        }
        self.highest_pnl[symbol] = 0

        return True

    def close_position(self, symbol, price, timestamp, reason='signal'):
        """Close an existing position"""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]

        # Apply slippage
        if pos['side'] == 'LONG':
            exit_price = price * (1 - self.config['slippage'])
        else:
            exit_price = price * (1 + self.config['slippage'])

        # Calculate P&L
        if pos['side'] == 'LONG':
            pnl_pct = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100 * LEVERAGE
            pnl_usd = (exit_price - pos['entry_price']) * pos['size']
        else:
            pnl_pct = ((pos['entry_price'] - exit_price) / pos['entry_price']) * 100 * LEVERAGE
            pnl_usd = (pos['entry_price'] - exit_price) * pos['size']

        # Deduct trading fee
        exit_notional = pos['size'] * exit_price
        fee = exit_notional * self.config['trading_fee']
        pnl_usd -= fee

        # Update balance
        self.balance += pnl_usd

        # Record trade
        trade = {
            'symbol': symbol,
            'side': pos['side'],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'size': pos['size'],
            'notional': pos['notional'],
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'open_time': pos['open_time'],
            'close_time': timestamp,
            'duration': str(timestamp - pos['open_time']),
            'confidence': pos['confidence'],
            'reason': reason
        }
        self.trades.append(trade)

        # Clean up
        del self.positions[symbol]
        if symbol in self.highest_pnl:
            del self.highest_pnl[symbol]

        return trade

    def check_stop_loss_take_profit(self, symbol, current_price, timestamp):
        """Check if position should be closed due to SL/TP/Trailing Stop"""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]

        # Calculate current P&L
        if pos['side'] == 'LONG':
            pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100 * LEVERAGE
        else:
            pnl_pct = ((pos['entry_price'] - current_price) / pos['entry_price']) * 100 * LEVERAGE

        # Update trailing stop tracking
        if USE_TRAILING_STOP:
            if pnl_pct > self.highest_pnl.get(symbol, 0):
                self.highest_pnl[symbol] = pnl_pct

            # Check trailing stop
            if self.highest_pnl[symbol] >= TRAILING_STOP_ACTIVATION:
                trailing_stop_level = self.highest_pnl[symbol] - TRAILING_STOP_DISTANCE
                if pnl_pct <= trailing_stop_level:
                    return self.close_position(symbol, current_price, timestamp, 'trailing_stop')

        # Check stop loss
        if pnl_pct <= -STOP_LOSS_PERCENTAGE:
            return self.close_position(symbol, current_price, timestamp, 'stop_loss')

        # Check take profit
        if pnl_pct >= TAKE_PROFIT_PERCENTAGE:
            return self.close_position(symbol, current_price, timestamp, 'take_profit')

        return None

    def get_equity(self, current_prices):
        """Calculate current total equity including unrealized P&L"""
        equity = self.balance

        for symbol, pos in self.positions.items():
            if symbol in current_prices:
                price = current_prices[symbol]
                if pos['side'] == 'LONG':
                    unrealized = (price - pos['entry_price']) * pos['size']
                else:
                    unrealized = (pos['entry_price'] - price) * pos['size']
                equity += unrealized

        return equity

    def simulate_signal(self, row):
        """
        Simulate AI signal generation based on indicators.
        Returns (action, confidence) tuple.

        This is a simplified simulation - replace with actual AI calls for more accuracy.
        """
        # Helper to extract scalar from potentially Series/array values
        def to_scalar(val, default=0):
            if val is None or (hasattr(val, '__len__') and not isinstance(val, str) and len(val) == 0):
                return default
            if pd.isna(val) if not hasattr(val, '__len__') else False:
                return default
            if hasattr(val, 'iloc'):
                return float(val.iloc[0]) if len(val) > 0 else default
            if hasattr(val, 'item'):
                return val.item()
            return float(val)

        # Simple strategy based on RSI and MACD
        close = to_scalar(row['close'], 0)
        rsi = to_scalar(row.get('rsi_14', 50), 50)
        macd = to_scalar(row.get('macd', 0), 0)
        macd_signal = to_scalar(row.get('macd_signal', 0), 0)
        sma_20 = to_scalar(row.get('sma_20', close), close)
        sma_50 = to_scalar(row.get('sma_50', close), close)
        sma_200 = to_scalar(row.get('sma_200', close), close)

        score = 50  # Start neutral

        # RSI signals (stronger weights)
        if rsi < 25:
            score += 25  # Very oversold = strong bullish
        elif rsi < 35:
            score += 15  # Oversold = bullish
        elif rsi > 75:
            score -= 25  # Very overbought = strong bearish
        elif rsi > 65:
            score -= 15  # Overbought = bearish

        # MACD crossover (stronger signal)
        macd_diff = macd - macd_signal
        if macd_diff > 0:
            score += 15
        else:
            score -= 15

        # Price vs SMAs (trend following)
        if close > sma_20:
            score += 8
        else:
            score -= 5
        if close > sma_50:
            score += 7
        else:
            score -= 5
        if close > sma_200:
            score += 10
        else:
            score -= 8

        # Clamp score to 0-100
        score = max(0, min(100, score))

        # Determine action with adjusted thresholds
        if score >= 65:
            action = 'BUY'
            # Scale confidence: score 65-100 maps to confidence 70-95
            confidence = 70 + int((score - 65) * (25 / 35))
        elif score <= 35:
            action = 'SELL'
            # Scale confidence: score 0-35 maps to confidence 70-95
            confidence = 70 + int((35 - score) * (25 / 35))
        else:
            action = 'NOTHING'
            confidence = 50

        return action, min(95, confidence)

    def run_backtest(self, data_dict):
        """
        Run backtest on historical data.

        Args:
            data_dict: Dictionary of {symbol: DataFrame} with OHLCV + indicators
        """
        cprint("\n" + "="*60, "cyan")
        cprint("🔬 STARTING BACKTEST", "cyan", attrs=['bold'])
        cprint("="*60, "cyan")
        cprint(f"Initial Balance: ${self.initial_balance:,.2f}", "white")
        cprint(f"Symbols: {list(data_dict.keys())}", "white")
        cprint(f"Leverage: {LEVERAGE}x", "white")
        cprint(f"Stop Loss: {STOP_LOSS_PERCENTAGE}% | Take Profit: {TAKE_PROFIT_PERCENTAGE}%", "white")
        if USE_TRAILING_STOP:
            cprint(f"Trailing Stop: Activates at {TRAILING_STOP_ACTIVATION}%, trails {TRAILING_STOP_DISTANCE}%", "white")
        if USE_DYNAMIC_SIZING:
            cprint(f"Dynamic Sizing: {DYNAMIC_SIZE_MIN_PCT}% - {DYNAMIC_SIZE_MAX_PCT}%", "white")
        cprint("="*60 + "\n", "cyan")

        # Align all dataframes by timestamp
        all_timestamps = set()
        for df in data_dict.values():
            all_timestamps.update(df.index.tolist())
        all_timestamps = sorted(all_timestamps)

        # Helper to extract scalar value
        def to_scalar(val):
            if hasattr(val, 'iloc'):
                return float(val.iloc[0]) if len(val) > 0 else 0
            if hasattr(val, 'item'):
                return val.item()
            return float(val)

        # Process each timestamp
        for i, ts in enumerate(all_timestamps):
            current_prices = {}

            for symbol, df in data_dict.items():
                if ts not in df.index:
                    continue

                row = df.loc[ts]
                # Handle case where loc returns DataFrame (duplicate indices)
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]

                close_price = to_scalar(row['close'])

                # Skip if price is NaN or invalid
                if pd.isna(close_price) or close_price <= 0:
                    continue

                current_prices[symbol] = close_price

                # Check existing position for SL/TP
                self.check_stop_loss_take_profit(symbol, close_price, ts)

                # Generate signal
                action, confidence = self.simulate_signal(row)

                # Execute trades
                if symbol in self.positions:
                    # We have a position
                    if action == 'SELL' and self.positions[symbol]['side'] == 'LONG':
                        self.close_position(symbol, close_price, ts, 'signal')
                    elif action == 'BUY' and self.positions[symbol]['side'] == 'SHORT':
                        self.close_position(symbol, close_price, ts, 'signal')
                else:
                    # No position
                    if confidence >= MIN_CONFIDENCE_TO_TRADE:
                        if action == 'BUY':
                            self.open_position(symbol, 'LONG', close_price, confidence, ts)
                        elif action == 'SELL' and not LONG_ONLY:
                            self.open_position(symbol, 'SHORT', close_price, confidence, ts)

            # Record equity only if we have valid prices
            equity = self.balance  # Default to balance
            if current_prices:
                equity = self.get_equity(current_prices)
                if not pd.isna(equity):
                    self.equity_curve.append((ts, equity))
                else:
                    equity = self.balance

            # Progress indicator
            if i % 500 == 0:
                pct = (i / len(all_timestamps)) * 100
                print(f"\r⏳ Progress: {pct:.1f}% | Equity: ${equity:,.2f} | Trades: {len(self.trades)}", end='')

        print()  # New line after progress

        # Close any remaining positions at last price
        for symbol in list(self.positions.keys()):
            if symbol in current_prices:
                self.close_position(symbol, current_prices[symbol], all_timestamps[-1], 'end_of_backtest')

        return self.generate_report()

    def generate_report(self):
        """Generate backtest performance report"""
        if not self.trades:
            return {"error": "No trades executed"}

        trades_df = pd.DataFrame(self.trades)

        # Calculate metrics
        total_trades = len(self.trades)
        winning_trades = len(trades_df[trades_df['pnl_usd'] > 0])
        losing_trades = len(trades_df[trades_df['pnl_usd'] < 0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = trades_df['pnl_usd'].sum()
        avg_pnl = trades_df['pnl_usd'].mean()
        avg_win = trades_df[trades_df['pnl_usd'] > 0]['pnl_usd'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['pnl_usd'] < 0]['pnl_usd'].mean() if losing_trades > 0 else 0

        # Calculate profit factor
        gross_profit = trades_df[trades_df['pnl_usd'] > 0]['pnl_usd'].sum()
        gross_loss = abs(trades_df[trades_df['pnl_usd'] < 0]['pnl_usd'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Calculate max drawdown
        equity_df = pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].min()

        # Return on investment
        roi = ((self.balance - self.initial_balance) / self.initial_balance) * 100

        # Trade breakdown by reason
        close_reasons = trades_df['reason'].value_counts().to_dict()

        report = {
            'summary': {
                'initial_balance': self.initial_balance,
                'final_balance': self.balance,
                'total_pnl': total_pnl,
                'roi_pct': roi,
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'max_drawdown_pct': max_drawdown,
                'avg_pnl': avg_pnl,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
            },
            'close_reasons': close_reasons,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }

        # Print report
        cprint("\n" + "="*60, "green")
        cprint("📊 BACKTEST RESULTS", "green", attrs=['bold'])
        cprint("="*60, "green")

        cprint(f"\n💰 PERFORMANCE", "yellow", attrs=['bold'])
        cprint(f"   Initial Balance: ${self.initial_balance:,.2f}", "white")
        cprint(f"   Final Balance:   ${self.balance:,.2f}", "white")
        pnl_color = "green" if total_pnl >= 0 else "red"
        cprint(f"   Total P&L:       ${total_pnl:,.2f} ({roi:+.2f}%)", pnl_color, attrs=['bold'])
        cprint(f"   Max Drawdown:    {max_drawdown:.2f}%", "red" if max_drawdown < -10 else "yellow")

        cprint(f"\n📈 TRADE STATISTICS", "yellow", attrs=['bold'])
        cprint(f"   Total Trades:    {total_trades}", "white")
        cprint(f"   Winning:         {winning_trades} ({win_rate:.1f}%)", "green")
        cprint(f"   Losing:          {losing_trades}", "red")
        cprint(f"   Profit Factor:   {profit_factor:.2f}", "cyan")
        cprint(f"   Avg Win:         ${avg_win:,.2f}", "green")
        cprint(f"   Avg Loss:        ${avg_loss:,.2f}", "red")

        cprint(f"\n🎯 CLOSE REASONS", "yellow", attrs=['bold'])
        for reason, count in close_reasons.items():
            cprint(f"   {reason}: {count}", "white")

        cprint("\n" + "="*60, "green")

        return report

    def save_results(self, report, filename=None):
        """Save backtest results to file"""
        if 'error' in report:
            cprint(f"\n⚠️ Cannot save results: {report['error']}", "yellow")
            return None

        if filename is None:
            filename = f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = BACKTEST_RESULTS_DIR / filename

        # Convert datetime objects to strings for JSON serialization
        save_data = {
            'config': self.config,
            'summary': report.get('summary', {}),
            'close_reasons': report.get('close_reasons', {}),
            'trades': report.get('trades', []),
            'equity_curve': [(str(t), e) for t, e in report.get('equity_curve', [])]
        }

        with open(filepath, 'w') as f:
            json.dump(save_data, f, indent=2, default=str)

        cprint(f"\n💾 Results saved to: {filepath}", "cyan")
        return filepath


def fetch_historical_data(symbol, days=90, timeframe='1H'):
    """Fetch historical OHLCV data for backtesting"""
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)

        # Calculate time range
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        # Map timeframe to interval
        interval_map = {'1H': '1h', '4H': '4h', '1D': '1d', '15m': '15m'}
        interval = interval_map.get(timeframe, '1h')

        # Fetch candles
        candles = info.candles_snapshot(symbol, interval, start_time, end_time)

        if not candles:
            return None

        # Convert to DataFrame (handle dict format from HyperLiquid API)
        df_data = []
        for c in candles:
            if isinstance(c, dict):
                df_data.append({
                    'timestamp': c.get('t'),
                    'open': float(c.get('o', 0)),
                    'high': float(c.get('h', 0)),
                    'low': float(c.get('l', 0)),
                    'close': float(c.get('c', 0)),
                    'volume': float(c.get('v', 0))
                })
            else:
                # Handle tuple/list format
                df_data.append({
                    'timestamp': c[0],
                    'open': float(c[1]),
                    'high': float(c[2]),
                    'low': float(c[3]),
                    'close': float(c[4]),
                    'volume': float(c[5])
                })

        df = pd.DataFrame(df_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.sort_index()  # Ensure chronological order

        # Add technical indicators
        df = add_indicators(df)

        return df

    except Exception as e:
        cprint(f"Error fetching data for {symbol}: {e}", "red")
        return None


def add_indicators(df):
    """Add technical indicators to DataFrame"""
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # SMAs
    df['sma_20'] = df['close'].rolling(window=20).mean()
    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['sma_200'] = df['close'].rolling(window=200).mean()

    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    # Bollinger Bands
    df['bb_middle'] = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
    df['bb_lower'] = df['bb_middle'] - (bb_std * 2)

    # ATR
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(window=14).mean()

    # Fill NaN values
    df.bfill(inplace=True)

    return df


def run_quick_backtest(symbols=None, days=30):
    """Run a quick backtest with default settings"""
    symbols = symbols or ['BTC', 'ETH']

    cprint(f"\n🚀 Starting quick backtest for {symbols} ({days} days)...\n", "cyan", attrs=['bold'])

    # Fetch data
    data_dict = {}
    for symbol in symbols:
        cprint(f"📥 Fetching {symbol} data...", "white")
        df = fetch_historical_data(symbol, days=days)
        if df is not None and len(df) > 0:
            data_dict[symbol] = df
            cprint(f"   ✅ {len(df)} candles loaded", "green")
        else:
            cprint(f"   ❌ Failed to load data", "red")

    if not data_dict:
        cprint("❌ No data available for backtesting", "red")
        return None

    # Run backtest
    engine = BacktestEngine()
    report = engine.run_backtest(data_dict)

    # Save results
    engine.save_results(report)

    return report


if __name__ == "__main__":
    # Run backtest
    report = run_quick_backtest(
        symbols=['BTC', 'ETH'],
        days=60
    )
