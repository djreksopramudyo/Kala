"""
Kala - TECHNICAL-ONLY DAY TRADING ENGINE v2.2 for Indonesian Stock Market
================================================================================

v2.2 UPGRADE - TRAILING STOP SYSTEM:
- Added TRAILING STOP with 4 phases (initial → breakeven → trail → tight trail)
- Adjusted TARGET_PROFIT to +8% (realistic for IDX swing trading)
- Adjusted STOP_LOSS to -5% (ATR handles volatility, hard stop is the floor)
- Trailing stop LOCKS IN PROFITS as stock rises (stop never moves down)
- Phase 1: 0-4% profit → normal stop at -5%
- Phase 2: 4-8% profit → stop moves to breakeven (entry price)
- Phase 3: 8-12% profit → stop trails at -3% below peak price
- Phase 4: 12%+ profit → stop tightens to -2.5% below peak

v2.0 UPGRADE - After experiencing losses from suspended stocks:
- Added SUSPENSION DETECTION (zero volume, price freeze, stale data)
- Added LIQUIDITY FILTER (minimum volume threshold)
- Added MARKET REGIME CHECK (IHSG/JCI health affects all signals)
- Added ADX TREND STRENGTH (only trust strong trends, ADX > 25)
- Added MULTI-TIMEFRAME confirmation (weekly + monthly alignment)
- Added ATR-BASED STOP-LOSS (adapts to volatility, not fixed %)
- Added RISK/REWARD RATIO for each signal

Filosofi: "Saya tidak peduli perusahaannya jualan apa, 
           selama grafiknya naik DAN aman untuk ditradingkan, saya beli."

Tujuan: Trading Jangka Pendek/Menengah (Days to Weeks)
Strategi: Pure Technical Analysis + Safety Filters
Timeline: Day trading / Swing trading (Hold 1 day to 2 weeks)
Update: Daily (check signals every morning before market opens)

Installation:
    pip install yfinance pandas pandas_ta backtesting numpy

Usage:
    python kala_daily_trader.py

Scoring System (v2.1 - 100 points total):
    1. Trend Score       (20 pts) - SMA Crossover (10/50 periods)
    2. Momentum Score    (20 pts) - RSI + MACD (momentum-aware RSI!)
    3. Time Series Score (20 pts) - ROC, slope, acceleration, OBV, persistence
    4. ADX Strength      (10 pts) - Trend strength (only trust ADX > 25)
    5. Multi-TF Score    (10 pts) - Weekly + Monthly trend alignment
    6. Relative Strength (10 pts) - Performance vs IHSG index
    7. Volume + OBV      (10 pts) - Volume confirmation + smart money flow

    KEY FIX in v2.1: RSI > 70 in a strong momentum trend is a CONTINUATION
    signal, not a sell signal. Stocks like BUVA/CDIA that are running hard
    will now score correctly as BUY instead of being penalized.

    Score is then ADJUSTED by:
    - Market Health Multiplier (0.7x to 1.1x based on IHSG)
    - Safety Penalty (suspended = capped at 10, illiquid = 0.6x)

Safety Filters (NEW in v2.0):
    - Suspension detection: zero volume, price freeze, stale data
    - Liquidity filter: min 100K avg daily volume
    - Market regime: IHSG bearish = all scores penalized 30%
    - Trend strength: ADX < 20 = "no trend, don't trade"

Coverage:
    - 672 Sharia-compliant stocks (OJK Daftar Efek Syariah)
    - Automatically filters out suspended/illiquid stocks

WARNING: Technical-only trading is HIGH RISK!
    - False signals are common
    - News can invalidate technical setups instantly
    - ALWAYS use ATR-based stop-loss (shown in output)
    - Only use money you can afford to lose!

Author: Senior Python Quantitative Developer
Target: Indonesian day traders & swing traders
"""

import pandas as pd
import yfinance as yf

try:
    import pandas_ta as ta
except Exception:
    ta = None
# backtesting.py is no longer used (backtests run through kala); guarded
# so a missing install can never block the script.
try:
    from backtesting import Backtest, Strategy  # noqa: F401 (unused)
    from backtesting.lib import crossover  # noqa: F401 (unused)
except Exception:
    Backtest = Strategy = crossover = None
import os
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np

from kala import regime as _regime

warnings.filterwarnings('ignore')

# ============================================================================
# TIMEZONE HELPER - Use Indonesian Time (WIB = UTC+7)
# ============================================================================

def get_indonesian_time():
    """Get current time in Indonesian timezone (WIB = UTC+7)"""
    utc_now = datetime.now(timezone.utc)
    wib_offset = timedelta(hours=7)
    wib_time = utc_now + wib_offset
    return wib_time

def now():
    """Shortcut for Indonesian time"""
    return get_indonesian_time()


# ============================================================================
# SCRIPT IDENTITY
# ============================================================================
"""
THIS IS THE TECHNICAL-ONLY VERSION (Day Trader)
================================================

Key Differences from kala_engine.py (Multi-Factor Version):
- NO fundamental analysis (P/E, P/B, ROE, etc.)
- NO news sentiment analysis
- NO macro indicators (USD/IDR, oil prices, etc.)
- 100% Technical analysis only (SMA, RSI, MACD, Bollinger Bands, Volume)

Use this for:
- Day trading / Swing trading
- Quick momentum plays
- Following chart patterns only

Use kala_engine.py for:
- Long-term investment decisions
- Multi-factor analysis combining technical + fundamental + sentiment
- More comprehensive stock evaluation
"""


# ============================================================================
# OUTPUT LOGGER - Save results to file
# ============================================================================

class DualOutput:
    """Write output to both console and file"""
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w', encoding='utf-8')

    def write(self, message):
        # Handle Unicode for Windows console
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            safe_message = message.encode('ascii', 'ignore').decode('ascii')
            self.terminal.write(safe_message)
        except Exception as e:
            print(f"Error writing to terminal: {e}")
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()
        sys.stdout = self.terminal


def start_logging():
    """Start logging output to file"""
    # Create results folder if it doesn't exist
    if not os.path.exists('results'):
        os.makedirs('results')

    # Create timestamped filename (Indonesian time)
    timestamp = now().strftime('%Y%m%d_%H%M%S')
    filename = f'results/daily_trader_{timestamp}.txt'

    # Start dual output
    dual_output = DualOutput(filename)
    sys.stdout = dual_output

    print(f"Results will be saved to: {filename}")
    print("="*100 + "\n")

    return dual_output, filename, timestamp


def save_to_csv(signals, timestamp):
    """Save technical signals to CSV (no emojis, technical-only data)"""
    if not signals:
        return None

    # Create CSV filename
    csv_file = f'results/daily_trader_{timestamp}.csv'

    # Helper to remove emojis
    def clean_signal(text):
        emoji_map = {'🟢': '', '🔴': '', '🟡': '', '🟠': '', '⚫': '', '⚪': '', '✓': '', '✗': ''}
        for emoji in emoji_map:
            text = text.replace(emoji, '')
        return text.strip()

    # Prepare data for CSV - TECHNICAL + TIME SERIES + SAFETY (v2.1)
    data = []
    for s in signals:
        row = {
            'Ticker': s['ticker'],
            'Date': s['date'].strftime('%Y-%m-%d'),
            'Signal': clean_signal(s['signal']),
            'Technical_Score': f"{s.get('technical_score', 0):.0f}",
            'Raw_Score': f"{s.get('raw_score', 0):.0f}",
            'Price_IDR': f"{s['price']:.0f}",
            'Daily_Change_%': f"{s['daily_change']:.2f}",
            'ROC_5d_%': f"{s.get('roc_5', 0):.2f}",
            'ROC_10d_%': f"{s.get('roc_10', 0):.2f}",
            'ROC_20d_%': f"{s.get('roc_20', 0):.2f}",
            'Momentum_Persistence': f"{s.get('momentum_persistence', 0):.0f}",
            'Slope_%_per_day': f"{s.get('slope_pct_per_day', 0):.3f}",
            'Is_Accelerating': s.get('is_accelerating', False),
            'Relative_Strength_vs_IHSG': f"{s.get('avg_relative_strength', 0):.2f}",
            'OBV_Trend': s.get('obv_trend', 'N/A'),
            'RSI': f"{s['rsi']:.1f}",
            'ADX': f"{s.get('adx', 0):.1f}",
            'In_Strong_Momentum': s.get('in_strong_momentum', False),
            'Volume_Ratio': f"{s.get('volume_ratio', 1.0):.2f}",
            'MACD_Histogram': f"{s.get('macd_histogram', 0):.4f}",
            'BB_Position': s.get('bb_position', 'N/A'),
            'Weekly_Trend': s.get('weekly_trend', 'N/A'),
            'Monthly_Trend': s.get('monthly_trend', 'N/A'),
            'Stop_Loss': f"{s.get('stop_loss', 0):.0f}",
            'Take_Profit': f"{s.get('take_profit', 0):.0f}",
            'Sell_At_Loss_Price': f"{s.get('sell_at_loss_price', 0):.0f}",
            'Sell_At_Profit_Price': f"{s.get('sell_at_profit_price', 0):.0f}",
            'Target_Profit_Pct': f"{s.get('target_profit_pct', TARGET_PROFIT_PCT):.1f}",
            'Stop_Loss_Pct': f"{s.get('stop_loss_pct_config', STOP_LOSS_PCT):.1f}",
            'Risk_Reward': f"{s.get('risk_reward', 0):.1f}",
            'Trailing_Stop_Enabled': TRAILING_STOP_ENABLED,
            'Trailing_Breakeven_At': f"+{TRAILING_BREAKEVEN_PCT}%",
            'Trailing_Start_At': f"+{TRAILING_START_PCT}%",
            'Trailing_Distance': f"-{TRAILING_DISTANCE_PCT}%",
            'Trailing_Tight_At': f"+{TRAILING_TIGHT_TRIGGER_PCT}%",
            'Trailing_Tight_Distance': f"-{TRAILING_TIGHT_DISTANCE_PCT}%",
            'Is_Safe': s.get('is_safe', True),
            'Market_Status': s.get('market_status', 'UNKNOWN'),
        }
        data.append(row)

    # Create DataFrame and save
    df = pd.DataFrame(data)
    df.to_csv(csv_file, index=False)

    return csv_file


# ============================================================================
# CONFIGURATION BLOCK
# ============================================================================

INITIAL_CAPITAL = 3_000_000  # 2.5 Juta IDR
COMMISSION = 0.0019  # 0.19% standard Indonesian brokerage fee

# WHEN TO SELL - Configurable targets (adjust these to your risk tolerance)
TARGET_PROFIT_PCT = 8.0    # SELL when profit reaches +8% (take profit - realistic for IDX swing)
STOP_LOSS_PCT = -5.0       # SELL when loss reaches -5% (cut losses - ATR handles volatility)

# TRAILING STOP CONFIGURATION (v2.2 - smart profit protection)
# The trailing stop dynamically moves your stop-loss UP as the stock rises,
# locking in profits while giving the stock room to breathe.
#
# How it works:
#   Phase 1: Profit 0% to 4%     → Normal stop at STOP_LOSS_PCT (-5%) from entry
#   Phase 2: Profit 4% to 8%     → Stop moves to BREAKEVEN (entry price)
#   Phase 3: Profit 8% to 12%    → Stop trails at -3% below peak price
#   Phase 4: Profit 12%+         → Stop tightens to -2.5% below peak price
#
# Example: You buy at IDR 1,000. Stock runs to IDR 1,120 (+12% peak).
#   → Trailing stop is at IDR 1,120 * 0.975 = IDR 1,092 (+9.2% locked in!)
#   → If stock dips to 1,092, you sell with +9.2% profit instead of waiting for +8% or -5%.
#
TRAILING_STOP_ENABLED = True
TRAILING_BREAKEVEN_PCT = 4.0    # Move stop to breakeven when profit reaches this %
TRAILING_START_PCT = 8.0        # Start trailing stop when profit reaches this %
TRAILING_DISTANCE_PCT = 3.0     # Trail at this % below peak price (Phase 3)
TRAILING_TIGHT_TRIGGER_PCT = 12.0  # Tighten trailing stop above this profit %
TRAILING_TIGHT_DISTANCE_PCT = 2.5  # Tighter trail distance for big runners (Phase 4)

# ============================================================================
# DAFTAR EFEK SYARIAH (DES) - ALL SHARIA-COMPLIANT STOCKS
# Source: OJK (Otoritas Jasa Keuangan) - Updated May & November each year
# Total: 672 stocks (EXACT official DES list)
# ============================================================================

# COMPLETE DES LIST - OFFICIAL 672 SHARIA-COMPLIANT STOCKS FROM OJK
# --- universe extracted to the package (was 672 duplicated tickers) ---
from kala.universe import ALL_SHARIA_STOCKS

# TOP 30 BLUE CHIPS (Jakarta Islamic Index)
TOP_30_JII = [
    'ASII.JK', 'UNVR.JK', 'TLKM.JK', 'BBRI.JK', 'BMRI.JK', 'BBNI.JK', 'ICBP.JK', 'INDF.JK',
    'ADRO.JK', 'ANTM.JK', 'PTBA.JK', 'ITMG.JK', 'INCO.JK', 'UNTR.JK', 'KLBF.JK', 'MYOR.JK',
    'SMGR.JK', 'PGAS.JK', 'CPIN.JK', 'BSDE.JK', 'PWON.JK', 'MNCN.JK', 'EXCL.JK', 'ACES.JK',
    'WIKA.JK', 'PTPP.JK', 'WSKT.JK', 'TPIA.JK', 'ERAA.JK', 'SSMS.JK',
]

# SECTOR-SPECIFIC WATCHLISTS
WATCHLIST = ALL_SHARIA_STOCKS
BANKING = ['BBRI.JK', 'BMRI.JK', 'BBNI.JK', 'BBTN.JK', 'BRIS.JK', 'BTPS.JK', 'PNBS.JK', 'BANK.JK']
MINING = ['ADRO.JK', 'ANTM.JK', 'PTBA.JK', 'INCO.JK', 'ITMG.JK', 'GEMS.JK', 'MDKA.JK', 'TINS.JK', 'BYAN.JK']
CONSUMER = ['UNVR.JK', 'ICBP.JK', 'INDF.JK', 'KLBF.JK', 'MYOR.JK', 'ROTI.JK', 'SIDO.JK', 'CAMP.JK', 'GOOD.JK']
PROPERTY = ['BSDE.JK', 'PWON.JK', 'LPKR.JK', 'SMRA.JK', 'ASRI.JK', 'CTRA.JK', 'DILD.JK', 'APLN.JK']
TELCO = ['TLKM.JK', 'EXCL.JK', 'ISAT.JK', 'MTEL.JK', 'TOWR.JK', 'GHON.JK']
CONSTRUCTION = ['WIKA.JK', 'PTPP.JK', 'WSKT.JK', 'ADHI.JK', 'WTON.JK', 'WEGE.JK', 'JKON.JK']

# ============================================================================
# ACTIVE WATCHLIST - Choose which stocks to analyze
# ============================================================================

# OPTION 1: Top 30 Blue Chips (RECOMMENDED - ~1 min technical-only)
# WATCHLIST = TOP_30_JII

# OPTION 2: Quick Test (First 10 stocks - ~20 seconds)
# WATCHLIST = TOP_30_JII[:10]

# OPTION 3: Full DES - ALL 672 stocks (works fine - uses batch download, no individual API calls)
WATCHLIST = ALL_SHARIA_STOCKS

# OPTION 4: Sector-specific
# WATCHLIST = MINING + BANKING

# OPTION 5: Custom selection
# WATCHLIST = ['ERAL.JK']
# WATCHLIST = ['BBRI.JK', 'TLKM.JK', 'ANTM.JK']

# Backtest period
START_DATE = '2020-03-01'
END_DATE = now().strftime('%Y-%m-%d')  # Indonesian time

# The score at or above which a signal is STRONG rather than plain BUY.
STRONG_BUY_SCORE = 80.0


def signal_for_score(score: float, buy_threshold: float,
                     strong_threshold: float = STRONG_BUY_SCORE,
                     is_safe: bool = True) -> str:
    """The BUY/HOLD/SELL label for a composite score. Pure, so it can be tested.

    Extracted because this five-branch ladder IS the live buy decision, and
    the only thing that had ever exercised it was running the whole scanner
    against the network.

    ``strong_threshold`` never drops below ``buy_threshold``: with the
    forward_test profile's cutoff of 80 and a hardcoded STRONG at 80, the
    plain-BUY band is empty and every qualifying name is STRONG BUY. That is
    correct — the paper trader buys both labels — but a band that can never
    fire should be a consequence of the numbers, not an accident of ordering.
    """
    if not is_safe:
        return 'AVOID'
    strong = max(float(strong_threshold), float(buy_threshold))
    if score >= strong:
        return 'STRONG BUY'
    if score >= buy_threshold:
        return 'BUY'
    if score >= 50:
        return 'HOLD'
    if score >= 35:
        return 'SELL'
    return 'STRONG SELL'


# Default strategy parameters
DEFAULT_FAST_SMA = 10
DEFAULT_SLOW_SMA = 50
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_THRESHOLD = 70

# Optimization ranges (reduced for faster execution)
FAST_SMA_RANGE = range(5, 25, 5)  # [5, 10, 15, 20] - 4 values
SLOW_SMA_RANGE = range(30, 100, 20)  # [30, 50, 70, 90] - 4 values


# ============================================================================
# ADVANCED ANALYTICS: FUNDAMENTALS, VOLUME, MACRO, SENTIMENT
# ============================================================================

# ============================================================================
# TECHNICAL ANALYSIS - VOLUME CONFIRMATION
# ============================================================================

def analyze_volume_confirmation(data: pd.DataFrame, signal: str):
    """
    Confirm signals with volume analysis
    
    Args:
        data: OHLCV DataFrame
        signal: Current trading signal
    
    Returns:
        Confirmation score (0-100) and description
    """
    if len(data) < 20:
        return 50, "Insufficient data"

    # Calculate average volume
    avg_volume = data['Volume'].rolling(20).mean()
    current_volume = data['Volume'].iloc[-1]
    prev_volume = avg_volume.iloc[-1]

    if pd.isna(prev_volume) or prev_volume == 0:
        return 50, "No volume data"

    volume_ratio = current_volume / prev_volume

    # Volume should confirm the trend
    if signal == 'BUY':
        # Higher volume on buy signal is good
        if volume_ratio > 1.5:
            return 90, f"Strong volume ({volume_ratio:.1f}x avg)"
        elif volume_ratio > 1.0:
            return 70, f"Good volume ({volume_ratio:.1f}x avg)"
        else:
            return 40, f"Weak volume ({volume_ratio:.1f}x avg)"

    elif signal == 'SELL':
        # Higher volume on sell signal confirms the move
        if volume_ratio > 1.5:
            return 90, f"Strong selling ({volume_ratio:.1f}x avg)"
        elif volume_ratio > 1.0:
            return 70, f"Confirmed selling ({volume_ratio:.1f}x avg)"
        else:
            return 60, f"Light selling ({volume_ratio:.1f}x avg)"

    else:
        # For HOLD, we want stable volume
        if 0.8 < volume_ratio < 1.2:
            return 80, f"Stable volume ({volume_ratio:.1f}x avg)"
        else:
            return 60, f"Volatile volume ({volume_ratio:.1f}x avg)"


# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class ShariaStrategy:
    """DEPRECATED (v3.1): the old crossover/no-stop backtest strategy. It is no
    longer used -- run_backtest now goes through kala.backtest_ticker, which
    models the live ruleset. Kept only as a name stub; do not use."""
    pass

def download_stock_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download historical OHLCV data from Yahoo Finance
    
    Args:
        ticker: Stock ticker symbol (e.g., 'TLKM.JK')
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
    
    Returns:
        DataFrame with OHLCV data
    """
    print(f"\n{'='*60}")
    print(f"Downloading data for {ticker}...")
    print(f"Period: {start} to {end}")
    print(f"{'='*60}")

    try:
        df = yf.download(ticker, start=start, end=end, progress=False)

        if df.empty:
            raise ValueError(f"No data retrieved for {ticker}")

        # Clean column names (yfinance sometimes returns multi-index)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Ensure required columns exist
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Remove any NaN values
        df = df.dropna()

        print(f"✓ Successfully downloaded {len(df)} bars")
        print(f"  Date range: {df.index[0].date()} to {df.index[-1].date()}")
        print(f"  Price range: IDR {df['Close'].min():,.0f} - {df['Close'].max():,.0f}")

        # refresh this ticker's last-known-good snapshot on every success
        try:
            from kala.datacache import save_frame
            save_frame(ticker, df)
        except Exception:
            pass
        return df

    except Exception as e:
        print(f"✗ Error downloading {ticker}: {str(e)}")
        # resilience: a transient yfinance failure (None/empty/403) falls
        # back to the last-good cached frame instead of cascading into
        # "no data" everywhere. ^JKSE and other non-cached names just get None.
        try:
            from kala.datacache import DEFAULT_MAX_AGE_DAYS, load_frame
            # Age-bounded: an unbounded cache read served a 47-day-old close
            # as today's price to _last_close(), and from there to /rebalance
            # and /buy, with nothing anywhere saying the number was old.
            cached = load_frame(ticker, max_age_days=DEFAULT_MAX_AGE_DAYS)
            if cached is not None:
                print(f"  ↳ serving last-good cached data for {ticker} "
                      f"({len(cached)} bars, may be stale)")
                return cached
        except Exception:
            pass
        return None


# ============================================================================
# BACKTESTING ENGINE
# ============================================================================

_BENCHMARK_CACHE = {}

def _get_ihsg_benchmark():
    """Download-and-cache IHSG (^JKSE) for benchmark-relative backtest stats.
    Returns None quietly if offline/unavailable -- alpha lines are then skipped."""
    if 'ihsg' not in _BENCHMARK_CACHE:
        try:
            _BENCHMARK_CACHE['ihsg'] = download_stock_data('^JKSE', START_DATE, END_DATE)
        except Exception:
            _BENCHMARK_CACHE['ihsg'] = None
    return _BENCHMARK_CACHE['ihsg']


def run_backtest(data: pd.DataFrame, ticker: str, optimize: bool = False):
    """
    Backtest the strategy you ACTUALLY trade (v3.1).

    Previously this ran ShariaStrategy (a golden-cross / death-cross system with
    NO stops) through backtesting.py and curve-fit the SMA periods in-sample --
    measuring a strategy you don't trade and overfitting it. It now runs the same
    engine the live system uses (kala.backtest): composite-score entries,
    the governing/trailing-stop exit ladder, IDX limit-down carry, and asymmetric
    costs. The number you validate here is the number you run live.

    `optimize` is kept for call-site compatibility but ignored (in-sample
    optimization removed as overfitting). Returns (stats_dict, None).
    """
    import numpy as _np

    from kala.backtest import backtest_ticker
    from kala.config import Config

    print(f"\n{'-'*60}")
    print(f"BACKTESTING {ticker}  (live ruleset: stops + trailing + ARB + costs)")
    print(f"{'-'*60}")
    if optimize:
        print("  note: in-sample SMA optimization removed (overfitting); running honest engine.")

    res = backtest_ticker(ticker, data, _get_ihsg_benchmark(), Config())
    trades = res.closed
    n = len(trades)
    rets = [t.net_return_pct for t in trades]
    win_rate = (sum(1 for r in rets if r > 0) / n * 100.0) if n else 0.0

    equity = float(INITIAL_CAPITAL); curve = [equity]
    for r in rets:
        equity *= (1.0 + r / 100.0); curve.append(equity)
    total_return = (curve[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    peak = curve[0]; max_dd = 0.0
    for eq in curve:
        peak = max(peak, eq); max_dd = min(max_dd, (eq / peak - 1.0) * 100.0)
    sharpe = (_np.mean(rets) / _np.std(rets)) if (n > 1 and _np.std(rets) > 0) else 0.0
    locked = sum(1 for t in trades if getattr(t, 'arb_locked_bars', 0) > 0)
    avg = _np.mean(rets) if n else 0.0

    print(f"  trades={n}  win_rate={win_rate:.1f}%  avg_net/trade={avg:+.2f}%  "
          f"max_dd={max_dd:.1f}%  ARB-locked exits={locked}")

    # ---- the number that matters: excess return vs doing nothing ----
    if res.buy_hold_return_pct is not None:
        print(f"  buy&hold {ticker}: {res.buy_hold_return_pct:+.1f}%   "
              f"alpha vs buy&hold: {res.alpha_vs_buy_hold_pct:+.1f}%")
    if res.benchmark_return_pct is not None:
        print(f"  IHSG same window: {res.benchmark_return_pct:+.1f}%   "
              f"ALPHA vs IHSG: {res.alpha_vs_benchmark_pct:+.1f}%"
              + ("   << strategy beats the index" if res.alpha_vs_benchmark_pct > 0
                 else "   << passive IHSG would have done better"))
    stats = {
        'Return [%]': total_return,
        'Win Rate [%]': win_rate,
        '# Trades': float(n),
        'Sharpe Ratio': sharpe,
        'Max. Drawdown [%]': max_dd,
        'Equity Final [$]': curve[-1],
        'Buy&Hold [%]': res.buy_hold_return_pct,
        'IHSG [%]': res.benchmark_return_pct,
        'Alpha vs IHSG [%]': res.alpha_vs_benchmark_pct,
    }
    return stats, None

def print_results(stats, ticker: str, data: pd.DataFrame):
    """
    Print formatted backtest results
    
    Args:
        stats: Backtest statistics
        ticker: Stock ticker symbol
        data: Original OHLCV data
    """
    print(f"\n{'='*60}")
    print(f"RESULTS FOR {ticker}")
    print(f"{'='*60}\n")

    # Calculate Buy & Hold return
    buy_hold_return = ((data['Close'].iloc[-1] / data['Close'].iloc[0]) - 1) * 100

    # Extract key metrics
    strategy_return = stats['Return [%]']
    win_rate = stats['Win Rate [%]']
    num_trades = stats['# Trades']
    sharpe_ratio = stats['Sharpe Ratio']
    max_drawdown = stats['Max. Drawdown [%]']

    # Get optimized parameters if available
    try:
        fast_sma = stats._strategy.fast_sma
        slow_sma = stats._strategy.slow_sma
        params_optimized = True
    except Exception:   # bare except also swallows KeyboardInterrupt/SystemExit
        fast_sma = DEFAULT_FAST_SMA
        slow_sma = DEFAULT_SLOW_SMA
        params_optimized = False

    # Print performance comparison
    print("📊 PERFORMANCE COMPARISON")
    print(f"{'─'*60}")
    print(f"  Buy & Hold Return:     {buy_hold_return:>10.2f}%")
    print(f"  Strategy Return:       {strategy_return:>10.2f}%")
    print(f"  Outperformance:        {strategy_return - buy_hold_return:>10.2f}%")
    print()

    # Print strategy metrics
    print("📈 STRATEGY METRICS")
    print(f"{'─'*60}")
    print(f"  Win Rate:              {win_rate:>10.2f}%")
    print(f"  Number of Trades:      {num_trades:>10.0f}")
    print(f"  Sharpe Ratio:          {sharpe_ratio:>10.2f}")
    print(f"  Max Drawdown:          {max_drawdown:>10.2f}%")
    print()

    # Print optimized parameters
    print("⚙️  STRATEGY PARAMETERS")
    print(f"{'─'*60}")
    print(f"  Fast SMA:              {fast_sma:>10.0f} days")
    print(f"  Slow SMA:              {slow_sma:>10.0f} days")
    print(f"  RSI Period:            {DEFAULT_RSI_PERIOD:>10.0f} days")
    print(f"  RSI Threshold:         {DEFAULT_RSI_THRESHOLD:>10.0f}")
    if params_optimized:
        print(f"  Status:                {'OPTIMIZED':>10}")
    else:
        print(f"  Status:                {'DEFAULT':>10}")
    print()

    # Print capital metrics
    final_equity = stats['Equity Final [$]']
    profit = final_equity - INITIAL_CAPITAL
    print("💰 CAPITAL SUMMARY")
    print(f"{'─'*60}")
    print(f"  Initial Capital:       IDR {INITIAL_CAPITAL:>12,}")
    print(f"  Final Equity:          IDR {final_equity:>12,.0f}")
    print(f"  Total Profit/Loss:     IDR {profit:>12,.0f}")
    print()

    # Performance verdict — judged on EXPECTANCY, not win rate.
    # A 45%-win system with fat winners beats a 60%-win system with fat
    # losers; gating the verdict on `win_rate > 50` (as this used to)
    # rewards exactly the wrong shape of P&L. Per-trade expectancy is
    # derived geometrically from total return and trade count.
    if num_trades > 0:
        expectancy = ((1.0 + strategy_return / 100.0) ** (1.0 / num_trades) - 1.0) * 100.0
    else:
        expectancy = 0.0
    print(f"  Expectancy/Trade:      {expectancy:>10.2f}%   (EV per trade — the number that compounds)")
    print()

    if strategy_return > buy_hold_return and expectancy > 0:
        verdict = "✓ STRATEGY OUTPERFORMED (positive EV/trade, beat buy & hold)"
        emoji = "🚀"
    elif strategy_return > 0:
        verdict = "~ PROFITABLE BUT UNDERPERFORMED"
        emoji = "📊"
    else:
        verdict = "✗ STRATEGY UNPROFITABLE"
        emoji = "⚠️"

    print(f"{emoji} {verdict}")
    print(f"{'='*60}\n")


# ============================================================================
# REAL-TIME SIGNAL GENERATION (WITH ADVANCED ANALYTICS)
# ============================================================================

def calculate_live_indicators(data: pd.DataFrame, fast_period: int = 10,
                               slow_period: int = 50, rsi_period: int = 14):
    """
    Calculate current indicator values for live trading
    
    Args:
        data: OHLCV DataFrame
        fast_period: Fast SMA period
        slow_period: Slow SMA period
        rsi_period: RSI period
    
    Returns:
        Dictionary with current indicator values
    """
    if len(data) < slow_period:
        return None

    # Calculate SMAs
    data['SMA_Fast'] = data['Close'].rolling(fast_period).mean()
    data['SMA_Slow'] = data['Close'].rolling(slow_period).mean()

    # Calculate RSI
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))

    # Get current (latest) values
    current = data.iloc[-1]
    previous = data.iloc[-2]

    return {
        'close': current['Close'],
        'sma_fast': current['SMA_Fast'],
        'sma_slow': current['SMA_Slow'],
        'rsi': current['RSI'],
        'prev_sma_fast': previous['SMA_Fast'],
        'prev_sma_slow': previous['SMA_Slow'],
    }


def generate_signal(indicators: dict, rsi_threshold: int = 70):
    """
    Generate trading signal based on current indicators
    
    Args:
        indicators: Dictionary with current indicator values
        rsi_threshold: RSI threshold for overbought
    
    Returns:
        Signal ('BUY', 'SELL', 'HOLD') and reason
    """
    if indicators is None:
        return 'WAIT', 'Insufficient data'

    close = indicators['close']
    sma_fast = indicators['sma_fast']
    sma_slow = indicators['sma_slow']
    rsi = indicators['rsi']
    prev_fast = indicators['prev_sma_fast']
    prev_slow = indicators['prev_sma_slow']

    # Check for crossovers
    golden_cross = (prev_fast <= prev_slow) and (sma_fast > sma_slow)
    death_cross = (prev_fast >= prev_slow) and (sma_fast < sma_slow)

    # Generate signal
    if golden_cross and rsi < rsi_threshold:
        return 'BUY', f'Golden Cross + RSI={rsi:.1f} (not overbought)'
    elif death_cross:
        return 'SELL', 'Death Cross (Fast SMA crossed below Slow)'
    elif sma_fast > sma_slow and rsi < rsi_threshold:
        return 'HOLD', f'Uptrend intact, RSI={rsi:.1f}'
    elif sma_fast > sma_slow and rsi >= rsi_threshold:
        return 'CAUTION', f'Uptrend but overbought (RSI={rsi:.1f})'
    elif sma_fast < sma_slow:
        return 'AVOID', 'Downtrend (Fast below Slow)'
    else:
        return 'HOLD', 'Neutral conditions'


# ============================================================================
# TIME SERIES ANALYSIS - Momentum, Trend Slope, Relative Strength
# ============================================================================

_ihsg_returns = None  # Cache IHSG returns for relative strength


def get_ihsg_returns():
    """
    Download and cache IHSG daily returns for relative strength calculations.
    Called once per run.
    """
    global _ihsg_returns
    if _ihsg_returns is not None:
        return _ihsg_returns

    try:
        end_date = now().replace(tzinfo=None)
        start_date = end_date - timedelta(days=100)
        jci = yf.download('^JKSE', start=start_date, end=end_date, progress=False)

        if jci.empty or len(jci) < 20:
            _ihsg_returns = {}
            return _ihsg_returns

        if isinstance(jci.columns, pd.MultiIndex):
            jci.columns = jci.columns.get_level_values(0)

        close = jci['Close']
        _ihsg_returns = {
            'close': close,
            'roc_5': ((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]) * 100 if len(close) >= 5 else 0,
            'roc_10': ((close.iloc[-1] - close.iloc[-10]) / close.iloc[-10]) * 100 if len(close) >= 10 else 0,
            'roc_20': ((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20]) * 100 if len(close) >= 20 else 0,
        }
        return _ihsg_returns
    except Exception:   # bare except also swallows KeyboardInterrupt/SystemExit
        _ihsg_returns = {}
        return _ihsg_returns


def calculate_time_series_metrics(data: pd.DataFrame):
    """
    TIME SERIES ANALYSIS for a single stock.
    
    This is what was missing - instead of just looking at current indicator values,
    we analyze the TRAJECTORY, MOMENTUM, and ACCELERATION of price movement.
    
    Stocks like BUVA/CDIA that are in strong momentum runs will score high here
    even if RSI is "overbought" (RSI > 70 in a strong trend is a continuation signal).
    
    Returns:
        dict with momentum metrics, or None if insufficient data
    """
    if data.empty or len(data) < 20:
        return None

    close = data['Close']
    volume = data['Volume']

    try:
        # ============================================================
        # 1. RATE OF CHANGE (ROC) - How much has the stock moved?
        # ============================================================
        roc_5 = ((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]) * 100 if len(close) >= 5 else 0
        roc_10 = ((close.iloc[-1] - close.iloc[-10]) / close.iloc[-10]) * 100 if len(close) >= 10 else 0
        roc_20 = ((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20]) * 100 if len(close) >= 20 else 0

        # ============================================================
        # 2. LINEAR REGRESSION SLOPE - Is the trend accelerating?
        # ============================================================
        # Slope of last 20 days (normalized as % per day)
        recent_20 = close.tail(20).values
        x_20 = np.arange(len(recent_20))
        slope_20, intercept_20 = np.polyfit(x_20, recent_20, 1) if len(recent_20) >= 20 else (0, 0)
        slope_pct_per_day = (slope_20 / recent_20[0]) * 100 if recent_20[0] != 0 else 0

        # Slope of last 10 days vs previous 10 days (acceleration)
        if len(close) >= 20:
            recent_10 = close.tail(10).values
            prev_10 = close.iloc[-20:-10].values
            slope_recent = np.polyfit(np.arange(len(recent_10)), recent_10, 1)[0] if len(recent_10) >= 10 else 0
            slope_prev = np.polyfit(np.arange(len(prev_10)), prev_10, 1)[0] if len(prev_10) >= 10 else 0
            acceleration = slope_recent - slope_prev  # Positive = getting steeper
        else:
            slope_recent = 0
            slope_prev = 0
            acceleration = 0

        is_accelerating = acceleration > 0

        # ============================================================
        # 3. ON BALANCE VOLUME (OBV) - Smart money accumulation
        # ============================================================
        obv = pd.Series(0.0, index=data.index)
        for i in range(1, len(data)):
            if close.iloc[i] > close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
            elif close.iloc[i] < close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]

        # OBV trend: compare OBV now vs 10 days ago
        obv_change_10 = obv.iloc[-1] - obv.iloc[-10] if len(obv) >= 10 else 0
        obv_trend = 'ACCUMULATION' if obv_change_10 > 0 else 'DISTRIBUTION'

        # OBV slope (normalized)
        obv_recent = obv.tail(10).values
        obv_slope = np.polyfit(np.arange(len(obv_recent)), obv_recent, 1)[0] if len(obv_recent) >= 10 else 0

        # ============================================================
        # 4. RELATIVE STRENGTH vs IHSG
        # ============================================================
        ihsg = get_ihsg_returns()

        relative_strength_5 = roc_5 - ihsg.get('roc_5', 0) if ihsg else roc_5
        relative_strength_10 = roc_10 - ihsg.get('roc_10', 0) if ihsg else roc_10
        relative_strength_20 = roc_20 - ihsg.get('roc_20', 0) if ihsg else roc_20

        # Average relative strength
        avg_relative_strength = (relative_strength_5 + relative_strength_10 + relative_strength_20) / 3
        is_outperforming = avg_relative_strength > 0

        # ============================================================
        # 5. CONSECUTIVE MOVE ANALYSIS
        # ============================================================
        consecutive_up = 0
        consecutive_down = 0

        for i in range(len(close) - 1, 0, -1):
            if close.iloc[i] > close.iloc[i-1]:
                if consecutive_down > 0:
                    break
                consecutive_up += 1
            elif close.iloc[i] < close.iloc[i-1]:
                if consecutive_up > 0:
                    break
                consecutive_down += 1
            else:
                break

        # ============================================================
        # 6. PRICE POSITION vs MOVING AVERAGES (momentum gauge)
        # ============================================================
        ema_8 = close.ewm(span=8).mean().iloc[-1]
        ema_21 = close.ewm(span=21).mean().iloc[-1]
        sma_50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else close.mean()

        current = close.iloc[-1]
        above_ema8 = current > ema_8
        above_ema21 = current > ema_21
        above_sma50 = current > sma_50

        # Distance from EMAs (how far above/below)
        dist_from_ema8_pct = ((current - ema_8) / ema_8) * 100
        dist_from_ema21_pct = ((current - ema_21) / ema_21) * 100

        # ============================================================
        # 7. MOMENTUM PERSISTENCE SCORE (0-100)
        # ============================================================
        # This is the key metric: how strong is the momentum?
        momentum_persistence = 0

        # ROC contribution (up to 30 pts)
        if roc_5 > 10:
            momentum_persistence += 15
        elif roc_5 > 5:
            momentum_persistence += 10
        elif roc_5 > 0:
            momentum_persistence += 5

        if roc_20 > 20:
            momentum_persistence += 15
        elif roc_20 > 10:
            momentum_persistence += 10
        elif roc_20 > 0:
            momentum_persistence += 5

        # Slope contribution (up to 20 pts)
        if slope_pct_per_day > 1.0:
            momentum_persistence += 20
        elif slope_pct_per_day > 0.5:
            momentum_persistence += 15
        elif slope_pct_per_day > 0.2:
            momentum_persistence += 10
        elif slope_pct_per_day > 0:
            momentum_persistence += 5

        # Acceleration bonus (up to 15 pts)
        if is_accelerating:
            if acceleration > 10:
                momentum_persistence += 15
            elif acceleration > 5:
                momentum_persistence += 10
            else:
                momentum_persistence += 5

        # Relative strength contribution (up to 15 pts)
        if avg_relative_strength > 10:
            momentum_persistence += 15
        elif avg_relative_strength > 5:
            momentum_persistence += 10
        elif avg_relative_strength > 0:
            momentum_persistence += 5

        # OBV confirmation (up to 10 pts)
        if obv_trend == 'ACCUMULATION' and roc_5 > 0:
            momentum_persistence += 10  # Price up + volume accumulating = very bullish
        elif obv_trend == 'ACCUMULATION':
            momentum_persistence += 5   # Volume accumulating even if price flat

        # Consecutive up days bonus (up to 10 pts)
        if consecutive_up >= 5:
            momentum_persistence += 10
        elif consecutive_up >= 3:
            momentum_persistence += 7
        elif consecutive_up >= 2:
            momentum_persistence += 3

        # Cap at 100
        momentum_persistence = min(100, momentum_persistence)

        return {
            # Rate of change
            'roc_5': roc_5,
            'roc_10': roc_10,
            'roc_20': roc_20,
            # Trend slope
            'slope_pct_per_day': slope_pct_per_day,
            'acceleration': acceleration,
            'is_accelerating': is_accelerating,
            # OBV
            'obv_trend': obv_trend,
            'obv_slope': obv_slope,
            # Relative strength
            'relative_strength_5': relative_strength_5,
            'relative_strength_20': relative_strength_20,
            'avg_relative_strength': avg_relative_strength,
            'is_outperforming': is_outperforming,
            # Consecutive moves
            'consecutive_up': consecutive_up,
            'consecutive_down': consecutive_down,
            # EMA positions
            'ema_8': ema_8,
            'ema_21': ema_21,
            'above_ema8': above_ema8,
            'above_ema21': above_ema21,
            'above_sma50': above_sma50,
            'dist_from_ema8_pct': dist_from_ema8_pct,
            'dist_from_ema21_pct': dist_from_ema21_pct,
            # Composite score
            'momentum_persistence': momentum_persistence,
        }

    except Exception:
        return None


# ============================================================================
# MARKET HEALTH CHECK - Check IHSG (JCI) before trading anything
# ============================================================================

_market_health = None

# Set by live_trading_dashboard() at the end of every scan. Lets a caller
# distinguish a genuinely quiet market from a scan that saw almost nothing —
# an empty BUY list looks identical in both cases.
LAST_SCAN_COVERAGE: dict | None = None

# Below this share of the watchlist actually analysed, the scan is degraded
# enough that "no buy signals" stops being evidence about the market.
MIN_SCAN_COVERAGE_PCT = 50.0


def _regime_unavailable(reason: str) -> dict:
    """Market-health payload for 'we tried to read the tape and failed'.

    Deliberately NOT 'UNKNOWN'. That string also marks benchmark warm-up bars
    (see kala/regime.py), which legitimately fail open — so spelling a
    fetch FAILURE the same way made a network blip silently indistinguishable
    from a benign one, and the block_buys_in_bear veto (the only hard regime
    protection the live scanner has, since the soft score multiplier was
    retired) never fired. UNAVAILABLE fails closed instead.
    """
    return {'status': _regime.UNAVAILABLE, 'multiplier': 1.0, 'trend': 'N/A',
            'change_5d': 0, 'change_20d': 0, 'unavailable_reason': reason}


def check_market_health():
    """
    Check overall IHSG/JCI index health BEFORE analyzing individual stocks.
    If the market is in a downtrend, ALL buy signals should be weakened.

    Returns:
        Dictionary with market health info and a penalty/bonus multiplier
    """
    global _market_health
    if _market_health is not None:
        return _market_health

    print("  Checking overall market health (IHSG/JCI)...", end=" ", flush=True)

    try:
        end_date = now().replace(tzinfo=None)
        start_date = end_date - timedelta(days=100)

        # Download IHSG (Jakarta Composite Index)
        jci = yf.download('^JKSE', start=start_date, end=end_date, progress=False)

        if jci.empty or len(jci) < 50:
            print("✗ No IHSG data")
            _market_health = _regime_unavailable('no IHSG data (empty or < 50 bars)')
            return _market_health

        if isinstance(jci.columns, pd.MultiIndex):
            jci.columns = jci.columns.get_level_values(0)

        # Calculate IHSG indicators
        sma_20 = jci['Close'].rolling(20).mean().iloc[-1]
        sma_50 = jci['Close'].rolling(50).mean().iloc[-1]
        current_jci = jci['Close'].iloc[-1]

        # 5-day and 20-day changes
        change_5d = ((current_jci - jci['Close'].iloc[-5]) / jci['Close'].iloc[-5]) * 100 if len(jci) >= 5 else 0
        change_20d = ((current_jci - jci['Close'].iloc[-20]) / jci['Close'].iloc[-20]) * 100 if len(jci) >= 20 else 0

        # Market regime detection
        if current_jci > sma_20 > sma_50:
            status = 'BULLISH'
            multiplier = 1.1   # Boost buy signals by 10%
            trend = 'Strong uptrend (Price > SMA20 > SMA50)'
        elif current_jci > sma_20:
            status = 'MODERATE_BULL'
            multiplier = 1.0   # Normal
            trend = 'Moderate uptrend (Price > SMA20)'
        elif current_jci > sma_50:
            status = 'NEUTRAL'
            multiplier = 0.9   # Slight caution
            trend = 'Neutral (Above SMA50 but below SMA20)'
        elif current_jci < sma_20 < sma_50:
            status = 'BEARISH'
            multiplier = 0.7   # Heavy penalty - reduce buy signals by 30%
            trend = 'Strong downtrend (Price < SMA20 < SMA50)'
        else:
            status = 'MODERATE_BEAR'
            multiplier = 0.8   # Moderate penalty
            trend = 'Moderate downtrend (Price < SMA50)'

        _market_health = {
            'status': status,
            'multiplier': multiplier,
            'trend': trend,
            'jci_price': current_jci,
            'sma_20': sma_20,
            'sma_50': sma_50,
            'change_5d': change_5d,
            'change_20d': change_20d,
        }

        print(f"✓ IHSG: {status} ({change_5d:+.1f}% 5d, {change_20d:+.1f}% 20d)")
        return _market_health

    except Exception as e:
        print(f"✗ Error: {e}")
        _market_health = _regime_unavailable(f'IHSG fetch failed: {e}')
        return _market_health


# ============================================================================
# STOCK SAFETY CHECKS - Suspension, liquidity, staleness
# ============================================================================

# Minimum daily volume (IDR) to consider a stock tradeable
MIN_AVG_VOLUME = 100000   # At least 100K shares/day average
MIN_TRADING_DAYS = 10     # Must have traded at least 10 of last 20 days
STALE_DATA_DAYS = 5       # If last trade > 5 days ago, consider stale/suspended


def check_stock_safety(data: pd.DataFrame, ticker: str):
    """
    Check if a stock is safe to trade (not suspended, liquid, not stale).
    
    Returns:
        (is_safe: bool, warnings: list, flags: dict)
    """
    warnings_list = []
    flags = {
        'suspended': False,
        'low_liquidity': False,
        'stale_data': False,
        'zero_volume_streak': 0,
        'avg_volume': 0,
        'days_since_trade': 0,
    }

    if data.empty or len(data) < 20:
        return False, ['Insufficient data (< 20 days)'], flags

    # 1. CHECK FOR SUSPENSION: Zero volume for multiple days
    recent_volume = data['Volume'].tail(10)
    zero_vol_days = (recent_volume == 0).sum()
    flags['zero_volume_streak'] = zero_vol_days

    if zero_vol_days >= 5:
        flags['suspended'] = True
        warnings_list.append(f"LIKELY SUSPENDED: {zero_vol_days}/10 days with zero volume")
    elif zero_vol_days >= 3:
        warnings_list.append(f"WARNING: {zero_vol_days}/10 days with zero volume")

    # 2. CHECK STALE DATA: Last trading date too old
    last_trade_date = data.index[-1]
    today = pd.Timestamp(now().replace(tzinfo=None).date())
    days_since = (today - last_trade_date).days
    flags['days_since_trade'] = days_since

    if days_since > STALE_DATA_DAYS:
        flags['stale_data'] = True
        warnings_list.append(f"STALE DATA: Last trade was {days_since} days ago")

    # 3. CHECK LIQUIDITY: Average volume too low
    avg_vol_20 = data['Volume'].tail(20).mean()
    flags['avg_volume'] = avg_vol_20

    if avg_vol_20 < MIN_AVG_VOLUME:
        flags['low_liquidity'] = True
        warnings_list.append(f"LOW LIQUIDITY: Avg volume {avg_vol_20:,.0f} (min: {MIN_AVG_VOLUME:,})")

    # 4. CHECK TRADING FREQUENCY: How many of last 20 days had volume > 0
    active_days = (data['Volume'].tail(20) > 0).sum()
    if active_days < MIN_TRADING_DAYS:
        warnings_list.append(f"THIN TRADING: Only {active_days}/20 active trading days")

    # 5. CHECK FOR PRICE FREEZE: Same closing price for 5+ days (sign of suspension)
    recent_close = data['Close'].tail(5)
    if recent_close.nunique() == 1:
        flags['suspended'] = True
        warnings_list.append("PRICE FROZEN: Same close price for 5+ days (likely suspended)")

    is_safe = not flags['suspended'] and not flags['stale_data'] and not flags['low_liquidity']

    return is_safe, warnings_list, flags


def get_live_signal(ticker: str, fast_sma: int = 10, slow_sma: int = 50,
                    preloaded_data: pd.DataFrame = None, market_health: dict = None):
    """
    TECHNICAL-ONLY trading signal with SAFETY CHECKS
    
    v2.0 Improvements:
    - Suspension detection (zero volume, stale data, price freeze)
    - Liquidity filter (minimum volume threshold)
    - Market regime adjustment (IHSG/JCI health affects all signals)
    - ADX trend strength (only trust strong trends)
    - ATR-based stop-loss levels (proper risk management)
    - Multi-timeframe confirmation (weekly + daily alignment)
    
    Args:
        ticker: Stock ticker symbol
        fast_sma: Fast SMA period (default: 10)
        slow_sma: Slow SMA period (default: 50)
        preloaded_data: Pre-downloaded DataFrame (from batch download)
        market_health: Pre-fetched market health data
    
    Returns:
        Dictionary with signal information, safety flags, and risk levels
    """
    try:
        if preloaded_data is not None:
            data = preloaded_data
        else:
            end_date = now().replace(tzinfo=None)
            start_date = end_date - timedelta(days=200)
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)

        if data.empty or len(data) < slow_sma:
            return None

        # Clean data
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # ============================================================
        # SAFETY CHECK: Is this stock tradeable?
        # ============================================================
        is_safe, safety_warnings, safety_flags = check_stock_safety(data, ticker)

        # Calculate base indicators
        indicators = calculate_live_indicators(data, fast_sma, slow_sma)
        if indicators is None:
            return None

        # ============================================================
        # TECHNICAL INDICATORS
        # ============================================================

        # 1. MACD (12, 26, 9)
        macd_line = data['Close'].ewm(span=12).mean() - data['Close'].ewm(span=26).mean()
        macd_signal = macd_line.ewm(span=9).mean()
        macd_current = macd_line.iloc[-1]
        macd_signal_current = macd_signal.iloc[-1]
        macd_histogram = macd_current - macd_signal_current

        # 2. Bollinger Bands (20 period, 2 std)
        bb_period = 20
        bb_std = 2
        bb_middle = data['Close'].rolling(bb_period).mean()
        bb_std_dev = data['Close'].rolling(bb_period).std()
        bb_upper = bb_middle + (bb_std * bb_std_dev)
        bb_lower = bb_middle - (bb_std * bb_std_dev)

        current_price = indicators['close']
        bb_position = 'MIDDLE'
        if current_price > bb_upper.iloc[-1]:
            bb_position = 'ABOVE_UPPER'
        elif current_price < bb_lower.iloc[-1]:
            bb_position = 'BELOW_LOWER'
        elif current_price > bb_middle.iloc[-1]:
            bb_position = 'UPPER_HALF'
        else:
            bb_position = 'LOWER_HALF'

        # 3. Volume analysis
        avg_volume = data['Volume'].rolling(20).mean().iloc[-1]
        current_volume = data['Volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0.0

        # 4. ADX - Average Directional Index (trend strength)
        # ADX > 25 = strong trend, ADX < 20 = weak/no trend
        high = data['High']
        low = data['Low']
        close = data['Close']

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr_14 = true_range.rolling(14).mean()
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr_14)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr_14)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        adx = dx.rolling(14).mean().iloc[-1] if not dx.rolling(14).mean().empty else 0
        atr_current = atr_14.iloc[-1] if not atr_14.empty else 0

        # 5. Weekly trend confirmation (use 5-day data as weekly proxy)
        weekly_close = data['Close'].iloc[-5] if len(data) >= 5 else data['Close'].iloc[0]
        weekly_trend = 'UP' if current_price > weekly_close else 'DOWN'

        # 6. Monthly trend (use 20-day data as monthly proxy)
        monthly_close = data['Close'].iloc[-20] if len(data) >= 20 else data['Close'].iloc[0]
        monthly_trend = 'UP' if current_price > monthly_close else 'DOWN'

        # Daily change
        prev_close = data['Close'].iloc[-2]
        daily_change = ((current_price - prev_close) / prev_close) * 100
        latest_date = data.index[-1]

        # ============================================================
        # TIME SERIES ANALYSIS (v2.1 - Momentum Detection)
        # ============================================================
        ts_metrics = calculate_time_series_metrics(data)

        # ============================================================
        # SCORING SYSTEM (v2.1 - Momentum-Aware)
        #
        # KEY FIX: RSI > 70 in a strong uptrend is a CONTINUATION
        # signal, not a sell signal. Stocks like BUVA/CDIA that are
        # in strong momentum runs should score HIGH, not get penalized.
        # ============================================================

        sma_fast = indicators['sma_fast']
        sma_slow = indicators['sma_slow']
        rsi = indicators['rsi']

        # Determine if stock is in a STRONG MOMENTUM context
        # (used to adjust how we interpret RSI and other indicators)
        in_strong_momentum = (
            ts_metrics is not None and
            ts_metrics.get('momentum_persistence', 0) >= 60 and
            sma_fast > sma_slow
        )

        # 1. Trend Score (20 points max) - SMA positioning
        trend_score = 0
        if sma_fast > sma_slow:
            sma_spread = ((sma_fast - sma_slow) / sma_slow) * 100
            if sma_spread > 5:
                trend_score = 20
            elif sma_spread > 2:
                trend_score = 15
            else:
                trend_score = 10
        else:
            sma_spread = ((sma_slow - sma_fast) / sma_fast) * 100
            if sma_spread > 5:
                trend_score = 0
            elif sma_spread > 2:
                trend_score = 3
            else:
                trend_score = 6

        # 2. Momentum Score (20 points max) - RSI + MACD
        #    KEY FIX: RSI > 70 in strong momentum = CONTINUATION, not sell
        momentum_score = 0

        # RSI (10 pts) - Context-aware scoring
        if in_strong_momentum:
            # In strong momentum: RSI > 70 is NORMAL and bullish
            if 50 < rsi < 80:
                momentum_score += 10  # Sweet spot for momentum stocks
            elif rsi >= 80:
                momentum_score += 6   # Extreme, but still riding the trend
            elif 40 < rsi < 50:
                momentum_score += 7   # Momentum fading slightly
            elif rsi < 30:
                momentum_score += 2   # Momentum broken
            else:
                momentum_score += 5
        else:
            # Normal context: standard RSI interpretation
            if 40 < rsi < 60:
                momentum_score += 10
            elif 30 < rsi < 70:
                momentum_score += 7
            elif rsi > 70:
                momentum_score += 4   # Overbought without momentum = risky
            else:
                momentum_score += 3   # Oversold

        # MACD (10 pts)
        if macd_current > macd_signal_current and macd_histogram > 0:
            momentum_score += 10
        elif macd_current > macd_signal_current:
            momentum_score += 7
        elif macd_current < macd_signal_current and macd_histogram < 0:
            momentum_score += 0
        else:
            momentum_score += 3

        # 3. TIME SERIES SCORE (20 points max) - NEW! This is the key addition
        #    Based on ROC, slope, acceleration, relative strength, OBV
        ts_score = 0
        if ts_metrics:
            mp = ts_metrics['momentum_persistence']
            if mp >= 80:
                ts_score = 20  # Extremely strong momentum
            elif mp >= 60:
                ts_score = 16  # Strong momentum
            elif mp >= 40:
                ts_score = 12  # Moderate momentum
            elif mp >= 20:
                ts_score = 6   # Weak momentum
            else:
                ts_score = 0   # No momentum / bearish

        # 4. Trend Strength Score (10 points max) - ADX
        adx_score = 0
        if adx > 40:
            adx_score = 10
        elif adx > 25:
            adx_score = 8
        elif adx > 20:
            adx_score = 4
        else:
            adx_score = 0

        # 5. Multi-Timeframe Score (10 points max)
        mtf_score = 0
        if weekly_trend == 'UP' and monthly_trend == 'UP' and sma_fast > sma_slow:
            mtf_score = 10
        elif weekly_trend == 'UP' and sma_fast > sma_slow:
            mtf_score = 7
        elif weekly_trend == 'DOWN' and monthly_trend == 'DOWN' and sma_fast < sma_slow:
            mtf_score = 0
        else:
            mtf_score = 4

        # 6. Relative Strength Score (10 points max) - NEW! vs IHSG
        rs_score = 0
        if ts_metrics:
            avg_rs = ts_metrics.get('avg_relative_strength', 0)
            if avg_rs > 10:
                rs_score = 10  # Massively outperforming IHSG
            elif avg_rs > 5:
                rs_score = 8
            elif avg_rs > 0:
                rs_score = 5   # Slightly outperforming
            elif avg_rs > -5:
                rs_score = 2   # Slightly underperforming
            else:
                rs_score = 0   # Lagging badly

        # 7. Volume + OBV Score (10 points max) - Enhanced with OBV
        volume_score = 0
        # Raw volume ratio (5 pts)
        if volume_ratio > 2.0:
            volume_score += 5
        elif volume_ratio > 1.5:
            volume_score += 4
        elif volume_ratio > 1.0:
            volume_score += 3
        elif volume_ratio > 0.5:
            volume_score += 1
        else:
            volume_score += 0

        # OBV trend (5 pts) - Smart money flow
        if ts_metrics and ts_metrics.get('obv_trend') == 'ACCUMULATION':
            volume_score += 5  # Money flowing IN
        elif ts_metrics and ts_metrics.get('obv_trend') == 'DISTRIBUTION':
            volume_score += 0  # Money flowing OUT
        else:
            volume_score += 2  # Unknown

        # ============================================================
        # TOTAL SCORE + ADJUSTMENTS
        # ============================================================

        raw_score = trend_score + momentum_score + ts_score + adx_score + mtf_score + rs_score + volume_score

        # MARKET ADJUSTMENT: If IHSG is bearish, reduce all scores
        # No market_health at all is also a failure to read the tape, not a
        # benign regime — same fail-closed treatment as a failed fetch.
        mkt = market_health if market_health else _regime_unavailable('market health unavailable')

        # ============================================================
        # REAL ENTRY SCORE (v3.2) — delegates to the tested engine
        #
        # Everything backtested/walk-forward-validated in this project
        # (kala.backtest, kala.walkforward) scores candidates with
        # kala.scoring.composite_score at score_entry_threshold=60, NOT
        # the hand-tuned blend above (raw_score/trend_score/momentum_score/
        # etc. — kept only for the diagnostic sub-score breakdown still
        # returned below, no longer what decides BUY/SELL). Live signals
        # used to be generated by that untested formula at an untested
        # threshold (65), so every validated backtest result was answering a
        # question about a strategy that wasn't the one actually trading.
        # This computes the SAME composite score the backtest uses, on the
        # SAME point-in-time feature set (kala.scoring.compute_features),
        # so live signals are finally governed by what was actually
        # validated.
        #
        # No soft regime multiplier is applied to it (unlike the old
        # adjusted_score) — regime risk is handled by the hard
        # block_buys_in_bear veto in evaluate_entry below, which is what the
        # backtest actually used to model bear markets. Safety penalties
        # (suspended/illiquid/stale) are a separate, orthogonal concern and
        # still apply, same as before.
        # ============================================================
        from kala.config import live_config as _live_config
        from kala.scoring import composite_score as _composite_score
        from kala.scoring import compute_features as _compute_features
        _feats = _compute_features(data)
        _raw_composite = _composite_score(_feats).iloc[-1]
        composite_technical_score = float(_raw_composite) if _raw_composite == _raw_composite else 0.0  # NaN -> 0

        # SAFETY PENALTY: Suspended/illiquid stocks get crushed
        if safety_flags.get('suspended'):
            composite_technical_score = min(composite_technical_score, 10)  # Cap at 10 (STRONG SELL)
        elif safety_flags.get('low_liquidity'):
            composite_technical_score *= 0.6  # 40% penalty
        elif safety_flags.get('stale_data'):
            composite_technical_score *= 0.7  # 30% penalty

        technical_score = max(0, min(100, composite_technical_score))
        # The cutoff the CONFIGURED profile says to buy at — not a hardcoded
        # Config() default. This line used to read the legacy 60 regardless of
        # runner_config.json, while daily_run logged the profile's 80 on every
        # run. See kala.config.live_config.
        buy_threshold = _live_config().backtest.score_entry_threshold

        # ATR-based stop-loss (dynamic, volatility-adjusted)
        stop_loss_price = current_price - (2 * atr_current) if atr_current > 0 else current_price * 0.95
        stop_loss_pct = ((stop_loss_price - current_price) / current_price) * 100
        take_profit_price = current_price + (3 * atr_current) if atr_current > 0 else current_price * 1.15
        risk_reward = abs((take_profit_price - current_price) / (current_price - stop_loss_price)) if (current_price - stop_loss_price) != 0 else 0

        # Fixed % targets (from config - clear "when to sell" levels)
        sell_at_loss_price = current_price * (1 + STOP_LOSS_PCT / 100)
        sell_at_profit_price = current_price * (1 + TARGET_PROFIT_PCT / 100)

        # Generate signal based on the validated composite score
        signal = signal_for_score(technical_score, buy_threshold, is_safe=is_safe)

        # --- BUY-SIDE GUARDRAILS (v3.1) -----------------------------------
        # The scanner rewards momentum, so it would happily buy a stock that has
        # already blown off (the PTPW case). Veto BUYs that are overbought,
        # parabolic, distributing, thin-volume, or fired in a bearish tape.
        entry_vetoes = []
        if signal in ('BUY', 'STRONG BUY'):
            try:
                from kala.entries import evaluate_entry
                from kala.entry_settings import load_entry_config
                # Was: evaluate_entry(data, market_status=...) with no cfg, so
                # EntryConfig()'s defaults applied and all five vetoes were
                # hardcoded ON — the measured-WORST setting, unreachable from
                # runner_config.json. Defaults are unchanged; the config can
                # now select something else. See kala/entry_settings.py.
                _ecfg, _ = load_entry_config()
                _entry = evaluate_entry(data, market_status=mkt.get('status'),
                                        cfg=_ecfg)
                entry_vetoes = _entry.vetoes
                if not _entry.allowed:
                    signal = 'HOLD'  # downgrade: do not chase
            except Exception as _e:  # noqa: BLE001 - reported, not swallowed
                # A crash here used to leave the BUY standing with an empty
                # veto list and nothing said so: the guardrail failed OPEN and
                # looked like "no veto fired". Now the failure is carried in
                # the veto list itself, so a reader sees it.
                from kala.entry_settings import veto_check_failed_note
                entry_vetoes = [veto_check_failed_note(_e)]

        # Build result dictionary
        result = {
            '_history': data.copy(),   # raw OHLCV, for the exit engine
            'ticker': ticker,
            'date': latest_date,
            'price': current_price,
            'daily_change': daily_change,
            'signal': signal,
            'entry_vetoes': entry_vetoes,
            'technical_score': technical_score,
            'raw_score': raw_score,
            'sma_fast': sma_fast,
            'sma_slow': sma_slow,
            'rsi': rsi,
            'macd': macd_current,
            'macd_signal': macd_signal_current,
            'macd_histogram': macd_histogram,
            'bb_position': bb_position,
            'volume_ratio': volume_ratio,
            'adx': adx,
            'atr': atr_current,
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend,
            'market_status': mkt.get('status', 'UNKNOWN'),
            'in_strong_momentum': in_strong_momentum,
            # Time series metrics
            'ts_score': ts_score,
            'rs_score': rs_score,
            'roc_5': ts_metrics.get('roc_5', 0) if ts_metrics else 0,
            'roc_10': ts_metrics.get('roc_10', 0) if ts_metrics else 0,
            'roc_20': ts_metrics.get('roc_20', 0) if ts_metrics else 0,
            'slope_pct_per_day': ts_metrics.get('slope_pct_per_day', 0) if ts_metrics else 0,
            'is_accelerating': ts_metrics.get('is_accelerating', False) if ts_metrics else False,
            'obv_trend': ts_metrics.get('obv_trend', 'N/A') if ts_metrics else 'N/A',
            'avg_relative_strength': ts_metrics.get('avg_relative_strength', 0) if ts_metrics else 0,
            'is_outperforming': ts_metrics.get('is_outperforming', False) if ts_metrics else False,
            'momentum_persistence': ts_metrics.get('momentum_persistence', 0) if ts_metrics else 0,
            'consecutive_up': ts_metrics.get('consecutive_up', 0) if ts_metrics else 0,
            # Risk management
            'stop_loss': stop_loss_price,
            'stop_loss_pct': stop_loss_pct,
            'take_profit': take_profit_price,
            'risk_reward': risk_reward,
            # Fixed % targets (configurable - clear "when to sell")
            'sell_at_loss_price': sell_at_loss_price,
            'sell_at_profit_price': sell_at_profit_price,
            'target_profit_pct': TARGET_PROFIT_PCT,
            'stop_loss_pct_config': STOP_LOSS_PCT,
            # Safety flags
            'is_safe': is_safe,
            'safety_warnings': safety_warnings,
            'safety_flags': safety_flags,
            # Sub-scores
            'trend_score': trend_score,
            'momentum_score': momentum_score,
            'adx_score': adx_score,
            'mtf_score': mtf_score,
            # 'rs_score' intentionally omitted here — it's set once above in
            # the time-series-metrics block (same value); a second key was a
            # harmless-but-confusing duplicate that lint (F601) flagged.
            'volume_score': volume_score,
        }

        return result

    except Exception:
        return None


# ============================================================================
# TRAILING STOP CALCULATOR (v2.2)
# ============================================================================

def calculate_trailing_stop(entry_price: float, current_price: float, peak_price: float = None):
    """
    Calculate the dynamic trailing stop-loss level based on profit phases.
    
    The trailing stop protects profits by moving the stop-loss UP as the stock
    rises, while never moving it DOWN. This locks in gains progressively.
    
    Args:
        entry_price: Price you bought at (IDR)
        current_price: Current market price (IDR)
        peak_price: Highest price since entry (IDR). If None, uses current_price.
    
    Returns:
        Dictionary with trailing stop details:
            - trailing_stop_price: The stop-loss price level
            - trailing_stop_pct: Stop level as % from entry
            - phase: Current trailing phase (1-4)
            - phase_name: Human-readable phase description
            - profit_locked_pct: Minimum profit locked in (% from entry)
            - peak_price: Highest price tracked
    """
    if not TRAILING_STOP_ENABLED:
        # Fallback to fixed stop-loss if trailing is disabled
        stop_price = entry_price * (1 + STOP_LOSS_PCT / 100)
        return {
            'trailing_stop_price': stop_price,
            'trailing_stop_pct': STOP_LOSS_PCT,
            'phase': 0,
            'phase_name': 'FIXED (trailing disabled)',
            'profit_locked_pct': STOP_LOSS_PCT,
            'peak_price': current_price,
        }

    # Track the peak price (highest since entry)
    if peak_price is None:
        peak_price = current_price
    peak_price = max(peak_price, current_price)

    # Calculate profit from entry to peak
    peak_profit_pct = ((peak_price - entry_price) / entry_price) * 100
    current_profit_pct = ((current_price - entry_price) / entry_price) * 100

    # Determine phase and stop level
    if peak_profit_pct >= TRAILING_TIGHT_TRIGGER_PCT:
        # PHASE 4: Big runner → tight trail at -2.5% below peak
        phase = 4
        phase_name = f'TIGHT TRAIL (-{TRAILING_TIGHT_DISTANCE_PCT}% from peak)'
        trailing_stop_price = peak_price * (1 - TRAILING_TIGHT_DISTANCE_PCT / 100)

    elif peak_profit_pct >= TRAILING_START_PCT:
        # PHASE 3: Good profit → trail at -3% below peak
        phase = 3
        phase_name = f'TRAILING (-{TRAILING_DISTANCE_PCT}% from peak)'
        trailing_stop_price = peak_price * (1 - TRAILING_DISTANCE_PCT / 100)

    elif peak_profit_pct >= TRAILING_BREAKEVEN_PCT:
        # PHASE 2: Moderate profit → stop at breakeven
        phase = 2
        phase_name = 'BREAKEVEN LOCK'
        trailing_stop_price = entry_price  # Stop at entry = zero loss

    else:
        # PHASE 1: Early stage → normal stop
        phase = 1
        phase_name = f'INITIAL STOP ({STOP_LOSS_PCT}%)'
        trailing_stop_price = entry_price * (1 + STOP_LOSS_PCT / 100)

    # IMPORTANT: Trailing stop NEVER moves down
    # The stop only moves UP to protect more profit
    min_stop = entry_price * (1 + STOP_LOSS_PCT / 100)  # Floor = hard stop
    trailing_stop_price = max(trailing_stop_price, min_stop)

    # Calculate locked-in profit %
    profit_locked_pct = ((trailing_stop_price - entry_price) / entry_price) * 100
    trailing_stop_pct = ((trailing_stop_price - entry_price) / entry_price) * 100

    return {
        'trailing_stop_price': trailing_stop_price,
        'trailing_stop_pct': trailing_stop_pct,
        'phase': phase,
        'phase_name': phase_name,
        'profit_locked_pct': profit_locked_pct,
        'peak_price': peak_price,
        'peak_profit_pct': peak_profit_pct,
    }


def check_exit_signals(ticker: str, entry_price: float, current_data: dict = None, peak_price: float = None):
    """
    Check whether to EXIT a position you own.

    v3.0 - delegates to the tested ``kala`` engine, fixing three bugs that
    lived here: urgency could be DOWNGRADED by a later weaker rule; the death
    cross fired every day below trend instead of on the cross; and the MACD
    threshold was an absolute IDR value. Return contract is unchanged, so
    check_my_stocks.py / monitor_portfolio keep working.
    """
    from kala.live import evaluate_position

    if current_data is None:
        current_data = get_live_signal(ticker)
    if not current_data:
        return {'ticker': ticker, 'entry_price': entry_price, 'exit_signal': False,
                'urgency': 'NORMAL', 'reasons': ['Cannot fetch data']}

    history = current_data.get('_history')
    if history is None or len(history) < 60:
        cur = current_data.get('price', entry_price)
        return {'ticker': ticker, 'entry_price': entry_price, 'current_price': cur,
                'profit_pct': (cur - entry_price) / entry_price * 100,
                'profit_idr': cur - entry_price, 'exit_signal': False, 'urgency': 'NORMAL',
                'reasons': ['Insufficient price history for exit engine'],
                'technical_data': current_data}

    return evaluate_position(
        ticker=ticker, entry_price=entry_price, history=history, peak_price=peak_price,
        market_status=current_data.get('market_status'), technical_data=current_data,
    )

def monitor_portfolio(positions: list):
    """
    Monitor all your open positions and check for exit signals (v2.2 - trailing stops)
    
    Args:
        positions: List of dicts with:
            {'ticker': str, 'entry_price': float, 'shares': int, 'peak_price': float (optional)}
            
            peak_price = highest price the stock has reached since you bought it.
            If you don't provide peak_price, it defaults to current_price (conservative).
            TIP: Track peak_price manually or check your broker's high-since-entry.
    
    Example:
        positions = [
            {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000, 'peak_price': 5800},
            {'ticker': 'TLKM.JK', 'entry_price': 3500, 'shares': 500},
        ]
        monitor_portfolio(positions)
    """
    print("\n" + "="*100)
    print("PORTFOLIO EXIT MONITOR v2.2 - Trailing Stop System")
    print("="*100)
    print(f"Generated: {now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print(f"Monitoring {len(positions)} positions")
    if TRAILING_STOP_ENABLED:
        print(f"Trailing Stop: ON (Breakeven at +{TRAILING_BREAKEVEN_PCT}%, Trail at +{TRAILING_START_PCT}% / -{TRAILING_DISTANCE_PCT}%, Tight at +{TRAILING_TIGHT_TRIGGER_PCT}% / -{TRAILING_TIGHT_DISTANCE_PCT}%)")
    else:
        print(f"Trailing Stop: OFF (Fixed targets: +{TARGET_PROFIT_PCT}% / {STOP_LOSS_PCT}%)")
    print("="*100 + "\n")

    results = []

    for pos in positions:
        ticker = pos['ticker']
        entry_price = pos['entry_price']
        shares = pos.get('shares', 0)
        peak_price = pos.get('peak_price', None)  # v2.2: peak tracking

        print(f"Checking {ticker}...", end=" ", flush=True)

        exit_data = check_exit_signals(ticker, entry_price, peak_price=peak_price)

        if exit_data:
            exit_data['shares'] = shares
            exit_data['total_profit_idr'] = exit_data['profit_idr'] * shares
            results.append(exit_data)
            print(f"✓ ({exit_data['profit_pct']:+.1f}%)")
        else:
            print("✗ Failed")

    # Display results
    print("\n" + "="*120)
    print("EXIT SIGNAL SUMMARY")
    print("="*120)
    print(f"{'Ticker':<10} {'Entry':<10} {'Current':<10} {'Peak':<10} {'P/L %':<8} {'Trail Phase':<22} {'Trail Stop':<12} {'Locked':<10} {'Status':<15}")
    print("-"*120)

    urgent_exits = []
    consider_exits = []
    hold_positions = []

    for r in results:
        ticker = r['ticker']
        entry = f"{r['entry_price']:,.0f}"
        current = f"{r['current_price']:,.0f}"
        peak = f"{r.get('peak_price', r['current_price']):,.0f}"
        pl_pct = f"{r['profit_pct']:+.1f}%"
        trail_phase = r.get('trailing_phase_name', 'N/A')[:20]
        trail_stop = f"{r.get('trailing_stop_price', 0):,.0f}"
        locked = f"{r.get('profit_locked_pct', 0):+.1f}%"

        if r['exit_signal']:
            if r['urgency'] == 'URGENT':
                status = "EXIT NOW"
                urgent_exits.append(r)
            else:
                status = "CONSIDER"
                consider_exits.append(r)
        else:
            status = "HOLD"
            hold_positions.append(r)

        print(f"  {ticker:<10} {entry:<10} {current:<10} {peak:<10} {pl_pct:<8} {trail_phase:<22} {trail_stop:<12} {locked:<10} {status:<15}")

    # Detailed exit analysis
    if urgent_exits:
        print("\n" + "="*100)
        print("URGENT EXITS - SELL IMMEDIATELY")
        print("="*100)

        for r in urgent_exits:
            print(f"\n{r['ticker']} - SELL {r['shares']} shares @ IDR {r['current_price']:,.0f}")
            print(f"   Entry: IDR {r['entry_price']:,.0f} | Peak: IDR {r.get('peak_price', r['current_price']):,.0f} | P/L: {r['profit_pct']:+.2f}% (IDR {r['total_profit_idr']:+,.0f})")
            print(f"   Trailing Phase: {r.get('trailing_phase_name', 'N/A')} | Stop: IDR {r.get('trailing_stop_price', 0):,.0f} | Locked: {r.get('profit_locked_pct', 0):+.1f}%")
            print("   REASONS:")
            for reason in r['reasons']:
                print(f"      • {reason}")

    if consider_exits:
        print("\n" + "="*100)
        print("CONSIDER EXITING - Review these positions")
        print("="*100)

        for r in consider_exits:
            print(f"\n{r['ticker']} - Consider selling {r['shares']} shares")
            print(f"   Entry: IDR {r['entry_price']:,.0f} | Current: IDR {r['current_price']:,.0f} | Peak: IDR {r.get('peak_price', r['current_price']):,.0f}")
            print(f"   P/L: {r['profit_pct']:+.2f}% (IDR {r['total_profit_idr']:+,.0f})")
            print(f"   Trailing Phase: {r.get('trailing_phase_name', 'N/A')} | Stop: IDR {r.get('trailing_stop_price', 0):,.0f} | Locked: {r.get('profit_locked_pct', 0):+.1f}%")
            print("   REASONS:")
            for reason in r['reasons']:
                print(f"      • {reason}")

    if hold_positions:
        print("\n" + "="*100)
        print("HOLD - These positions look good")
        print("="*100)
        for r in hold_positions:
            trail_info = f"Phase {r.get('trailing_phase', 1)}: {r.get('trailing_phase_name', 'N/A')}" if TRAILING_STOP_ENABLED else ""
            print(f"   {r['ticker']}: {r['profit_pct']:+.2f}% (IDR {r['total_profit_idr']:+,.0f}) | Trail stop: IDR {r.get('trailing_stop_price', 0):,.0f} ({r.get('profit_locked_pct', 0):+.1f}%) | {trail_info}")

    print("\n" + "="*100 + "\n")

    return results


def batch_download_prices(tickers: list, days: int = 200):
    """
    Download price data for ALL tickers at once (massive speedup).
    Instead of 672 individual API calls, this makes ~1 bulk request.
    
    Args:
        tickers: List of ticker symbols
        days: Number of historical days to fetch
    
    Returns:
        Dictionary of {ticker: DataFrame} for each stock
    """
    end_date = now().replace(tzinfo=None)
    start_date = end_date - timedelta(days=days)

    print(f"\n  Batch downloading {len(tickers)} stocks at once...", flush=True)

    # yfinance supports downloading multiple tickers in one call
    # This is MUCH faster than individual downloads
    # Process in chunks to avoid timeout on very large lists
    CHUNK_SIZE = 50  # Download 50 tickers per batch
    all_stock_data = {}

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        chunk_num = (i // CHUNK_SIZE) + 1
        total_chunks = (len(tickers) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"  Downloading batch {chunk_num}/{total_chunks} ({len(chunk)} stocks)...", end=" ", flush=True)

        try:
            # Download all tickers in this chunk at once
            raw_data = yf.download(
                chunk,
                start=start_date,
                end=end_date,
                progress=False,
                threads=True,  # Use multi-threading internally
                group_by='ticker'
            )

            if raw_data.empty:
                print("✗ Empty")
                continue

            # Extract per-ticker data from the batch result
            if len(chunk) == 1:
                # Single ticker: columns are simple (Open, High, Low, Close, Volume)
                ticker = chunk[0]
                if not raw_data.empty:
                    all_stock_data[ticker] = raw_data.copy()
            else:
                # Multiple tickers: columns are MultiIndex (ticker, column)
                for ticker in chunk:
                    try:
                        if ticker in raw_data.columns.get_level_values(0):
                            stock_df = raw_data[ticker].dropna(how='all')
                            if not stock_df.empty and len(stock_df) > 0:
                                all_stock_data[ticker] = stock_df.copy()
                    except (KeyError, TypeError):
                        pass

            print(f"✓ ({len([t for t in chunk if t in all_stock_data])}/{len(chunk)} OK)")

            # Delay between chunks to avoid rate limits (longer for large scans)
            if i + CHUNK_SIZE < len(tickers):
                time.sleep(2.0 if len(tickers) > 100 else 1.0)

        except Exception as e:
            print(f"✗ Error: {e}")
            # Wait longer on error, then retry the chunk as one batch
            time.sleep(5.0)
            try:
                raw_data = yf.download(
                    chunk, start=start_date, end=end_date,
                    progress=False, threads=False, group_by='ticker'
                )
                if not raw_data.empty:
                    if len(chunk) == 1:
                        all_stock_data[chunk[0]] = raw_data.copy()
                    else:
                        for ticker in chunk:
                            try:
                                if ticker in raw_data.columns.get_level_values(0):
                                    stock_df = raw_data[ticker].dropna(how='all')
                                    if not stock_df.empty:
                                        all_stock_data[ticker] = stock_df.copy()
                            except (KeyError, TypeError):
                                pass
                    print(f"  ↳ Retry OK ({len([t for t in chunk if t in all_stock_data])} stocks)")
            except Exception:
                print("  ↳ Retry also failed, skipping chunk")

    print(f"  Total: {len(all_stock_data)}/{len(tickers)} stocks downloaded successfully\n")
    return all_stock_data


def live_trading_dashboard():
    """
    TECHNICAL-ONLY Day Trading Dashboard v2.0
    
    New in v2.0:
    - Market health check (IHSG/JCI) before analyzing individual stocks
    - Suspension detection (zero volume, stale data, price freeze)
    - Liquidity filter (minimum volume threshold)
    - ADX trend strength (only trust strong trends)
    - Multi-timeframe confirmation (weekly + daily alignment)
    - ATR-based stop-loss and take-profit levels
    - Risk/reward ratio for each signal
    """
    global _market_health, _ihsg_returns
    _market_health = None  # Reset cache for fresh run
    _ihsg_returns = None   # Reset IHSG cache

    print("\n" + "="*100)
    print("KALA - DAY TRADER DASHBOARD v2.1 (TECHNICAL + TIME SERIES)")
    print("="*100)
    print(f"Generated: {now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print("Market: Indonesia Stock Exchange (IDX)")
    print("Analysis: Technical + Safety Checks + Market Regime + Multi-Timeframe")
    print("="*100)

    signals = []

    # STEP 1: Check overall market health FIRST
    print("\nSTEP 1: Checking market regime (IHSG/JCI)...")
    mkt = check_market_health()

    print(f"\n  MARKET STATUS: {mkt['status']}")
    print(f"  {mkt.get('trend', 'N/A')}")
    if mkt.get('jci_price'):
        print(f"  IHSG: {mkt['jci_price']:,.0f} | 5-day: {mkt['change_5d']:+.1f}% | 20-day: {mkt['change_20d']:+.1f}%")

    if mkt['status'] == 'BEARISH':
        print("\n  *** WARNING: IHSG is BEARISH! All buy signals will be penalized by 30%. ***")
        print("  *** Consider reducing position sizes or staying in cash. ***")
    elif mkt['status'] == 'MODERATE_BEAR':
        print("\n  *** CAUTION: IHSG showing weakness. Buy signals penalized by 20%. ***")
    elif mkt['status'] == 'BULLISH':
        print("\n  *** Market is BULLISH. Buy signals boosted by 10%. ***")

    # STEP 2: Batch download ALL price data at once
    print("\nSTEP 2: Downloading all price data in bulk...")
    start_time = time.time()
    all_data = batch_download_prices(WATCHLIST)
    download_time = time.time() - start_time
    print(f"  Download completed in {download_time:.1f} seconds")

    # STEP 3: Analyze each stock with safety checks
    print(f"\nSTEP 3: Analyzing {len(all_data)} stocks with safety filters...\n")

    skipped_suspended = 0
    skipped_illiquid = 0

    no_data = 0

    for ticker in WATCHLIST:
        print(f"  → {ticker}...", end=" ", flush=True)

        stock_data = all_data.get(ticker)
        if stock_data is None:
            no_data += 1
            print(" ✗ No data")
            continue

        signal_data = get_live_signal(
            ticker, DEFAULT_FAST_SMA, DEFAULT_SLOW_SMA,
            preloaded_data=stock_data, market_health=mkt
        )

        if signal_data:
            if signal_data.get('safety_flags', {}).get('suspended'):
                skipped_suspended += 1
                print(" ⚠ SUSPENDED/HALTED - skipped")
            elif signal_data.get('safety_flags', {}).get('low_liquidity'):
                skipped_illiquid += 1
                signals.append(signal_data)
                print(f" ⚠ LOW LIQUIDITY (Score: {signal_data['technical_score']:.0f}/100)")
            else:
                signals.append(signal_data)
                print(f" ✓ (Score: {signal_data['technical_score']:.0f}/100 | ADX: {signal_data.get('adx', 0):.0f})")
        else:
            print(" ✗ Failed")

    elapsed = time.time() - start_time

    # How much of the watchlist this scan actually saw. daily_run reads this
    # to tell "the market offered nothing" apart from "the scanner never
    # ran" — two states whose daily message used to be identical.
    global LAST_SCAN_COVERAGE
    LAST_SCAN_COVERAGE = {
        "attempted": len(WATCHLIST),
        "analysed": len(signals),
        "no_data": no_data,
        "coverage_pct": (len(signals) / len(WATCHLIST) * 100.0) if WATCHLIST else 0.0,
    }

    if not signals:
        # RAISE, don't return None. Returning None reached daily_run as
        # `... or []` — an empty BUY list with no stage error, i.e. a total
        # data outage rendered as "No new orders for tomorrow". stage()
        # exists to catch and report exactly this.
        raise RuntimeError(
            f"scan fetched no usable data for any of {len(WATCHLIST)} tickers "
            f"— data feed is down, this is NOT 'no opportunities today'")

    # Safety summary
    print("\n  SAFETY SUMMARY:")
    print(f"  Analyzed: {len(signals)} stocks | Suspended: {skipped_suspended} | Low liquidity: {skipped_illiquid}")
    print(f"  Total time: {elapsed:.1f} seconds")

    # Print main signals table
    print("\n" + "="*100)
    print("TECHNICAL TRADING SIGNALS v2.0 (Safety-Filtered)")
    print("="*100)

    # Define signal colors/emojis
    signal_emoji = {
        'STRONG BUY': '🟢🟢',
        'BUY': '🟢',
        'HOLD': '🟡',
        'SELL': '🔴',
        'STRONG SELL': '🔴🔴',
        'AVOID': '⛔',
    }

    # Filter out unsafe stocks from the main list, show them separately
    safe_signals = [s for s in signals if s.get('is_safe', True)]
    unsafe_signals = [s for s in signals if not s.get('is_safe', True)]

    # Sort safe signals by technical score
    safe_signals.sort(key=lambda x: x.get('technical_score', 0), reverse=True)

    # Print header
    print(f"{'Ticker':<10} {'Signal':<15} {'Score':<8} {'Price':<13} {'ROC20':<9} {'MomP':<6} {'ADX':<5} {'RS':<7} {'OBV':<6} {'Notes'}")
    print("-"*120)

    # Print each SAFE signal
    for s in safe_signals:
        signal_text = s['signal']
        emoji = signal_emoji.get(signal_text, '⚪')
        ticker = s['ticker']
        signal = f"{emoji} {signal_text}"
        score = f"{s.get('technical_score', 0):.0f}/100"
        price = f"IDR {s['price']:,.0f}"
        roc20 = f"{s.get('roc_20', 0):+.1f}%"
        mom_p = f"{s.get('momentum_persistence', 0):.0f}"
        adx_val = f"{s.get('adx', 0):.0f}"
        rs = f"{s.get('avg_relative_strength', 0):+.1f}%"
        obv = s.get('obv_trend', 'N/A')[:3]

        # Collect notes
        notes = []
        if s.get('in_strong_momentum'):
            notes.append("MOMENTUM")
        if s.get('is_outperforming'):
            notes.append("beats IHSG")
        if s.get('is_accelerating'):
            notes.append("accel")
        if s.get('adx', 0) < 20:
            notes.append("no trend")
        note_str = ", ".join(notes) if notes else ""

        print(f"{ticker:<10} {signal:<15} {score:<8} {price:<13} {roc20:<9} {mom_p:<6} {adx_val:<5} {rs:<7} {obv:<6} {note_str}")

    # Print unsafe stocks separately
    if unsafe_signals:
        print(f"\n{'='*120}")
        print("⛔ UNSAFE STOCKS (Suspended/Illiquid/Stale - DO NOT TRADE)")
        print(f"{'='*120}")
        for s in unsafe_signals:
            ticker = s['ticker']
            warnings = "; ".join(s.get('safety_warnings', ['Unknown']))
            print(f"  {ticker}: {warnings}")

    # Print detailed technical analysis for top opportunities
    print("\n" + "="*100)
    print("DETAILED TECHNICAL ANALYSIS (Top 10 Opportunities)")
    print("="*100)

    # Show top 10 by technical score (only safe stocks)
    top_signals = [s for s in safe_signals if s.get('is_safe', True)][:10]

    for s in top_signals:
        signal_text = s['signal']
        emoji = signal_emoji.get(signal_text, '⚪')

        print(f"\n{emoji} {s['ticker']} - {signal_text}")
        print("-"*120)

        # Price info
        print(f"PRICE: IDR {s['price']:,.0f} ({s['daily_change']:+.2f}% today) | Data: {s['date'].strftime('%Y-%m-%d')}")
        print(f"TECHNICAL SCORE: {s.get('technical_score', 0):.0f}/100 (Raw: {s.get('raw_score', 0):.0f} x Market: {mkt.get('multiplier', 1.0):.1f})")

        # Risk management
        print("\nRISK MANAGEMENT / WHEN TO SELL (v2.2 Trailing Stop):")
        print(f"   • HARD STOP-LOSS:    IDR {s.get('sell_at_loss_price', 0):,.0f} (below {s.get('stop_loss_pct_config', STOP_LOSS_PCT):+.0f}%) [absolute floor]")
        print(f"   • TARGET PROFIT:     IDR {s.get('sell_at_profit_price', 0):,.0f} (above +{s.get('target_profit_pct', TARGET_PROFIT_PCT):.0f}%)")
        print(f"   • ATR Stop-Loss:     IDR {s.get('stop_loss', 0):,.0f} ({s.get('stop_loss_pct', 0):+.1f}%) [volatility-based]")
        print(f"   • ATR Take-Profit:   IDR {s.get('take_profit', 0):,.0f} [volatility-based]")
        print(f"   • Risk/Reward:       {s.get('risk_reward', 0):.1f}:1")
        if TRAILING_STOP_ENABLED:
            price = s['price']
            print(f"   TRAILING STOP PHASES (if you buy at IDR {price:,.0f}):")
            print(f"     Phase 1: +0% to +{TRAILING_BREAKEVEN_PCT}%  → Stop at IDR {price * (1 + STOP_LOSS_PCT/100):,.0f} ({STOP_LOSS_PCT:+.0f}% from entry)")
            print(f"     Phase 2: +{TRAILING_BREAKEVEN_PCT}% to +{TRAILING_START_PCT}%  → Stop moves to IDR {price:,.0f} (BREAKEVEN)")
            print(f"     Phase 3: +{TRAILING_START_PCT}% to +{TRAILING_TIGHT_TRIGGER_PCT}% → Stop trails at -{TRAILING_DISTANCE_PCT}% below peak")
            print(f"     Phase 4: +{TRAILING_TIGHT_TRIGGER_PCT}%+       → Stop tightens to -{TRAILING_TIGHT_DISTANCE_PCT}% below peak")

        # Breakdown of technical score
        print("\nSCORE BREAKDOWN (v2.1):")
        print(f"   • Trend Score:       {s.get('trend_score', 0):.0f}/20  (SMA positioning)")
        print(f"   • Momentum Score:    {s.get('momentum_score', 0):.0f}/20  (RSI + MACD)")
        print(f"   • Time Series Score: {s.get('ts_score', 0):.0f}/20  (ROC, slope, acceleration)")
        print(f"   • ADX Strength:      {s.get('adx_score', 0):.0f}/10  (ADX = {s.get('adx', 0):.0f})")
        print(f"   • Multi-Timeframe:   {s.get('mtf_score', 0):.0f}/10  (Weekly: {s.get('weekly_trend', 'N/A')}, Monthly: {s.get('monthly_trend', 'N/A')})")
        print(f"   • Relative Strength: {s.get('rs_score', 0):.0f}/10  (vs IHSG: {s.get('avg_relative_strength', 0):+.1f}%)")
        print(f"   • Volume + OBV:      {s.get('volume_score', 0):.0f}/10  (Vol: {s.get('volume_ratio', 1.0):.2f}x, OBV: {s.get('obv_trend', 'N/A')})")

        # Time series analysis (NEW!)
        print("\nTIME SERIES ANALYSIS:")
        print(f"   • Momentum Score:   {s.get('momentum_persistence', 0):.0f}/100")
        print(f"   • 5-day Return:     {s.get('roc_5', 0):+.2f}%")
        print(f"   • 10-day Return:    {s.get('roc_10', 0):+.2f}%")
        print(f"   • 20-day Return:    {s.get('roc_20', 0):+.2f}%")
        print(f"   • Trend Slope:      {s.get('slope_pct_per_day', 0):+.3f}%/day")
        print(f"   • Accelerating:     {'YES' if s.get('is_accelerating') else 'NO'}")
        print(f"   • vs IHSG:          {s.get('avg_relative_strength', 0):+.1f}% ({'OUTPERFORMING' if s.get('is_outperforming') else 'UNDERPERFORMING'})")
        print(f"   • OBV:              {s.get('obv_trend', 'N/A')}")
        print(f"   • Consecutive Up:   {s.get('consecutive_up', 0)} days")

        if s.get('in_strong_momentum'):
            print("   ** STRONG MOMENTUM DETECTED: RSI > 70 treated as continuation, not sell **")

        # Detailed indicators
        print("\nTRADITIONAL INDICATORS:")
        print(f"   • SMA Fast (10):    {s['sma_fast']:.2f}")
        print(f"   • SMA Slow (50):    {s['sma_slow']:.2f}")
        sma_trend = "UPTREND" if s['sma_fast'] > s['sma_slow'] else "DOWNTREND"
        print(f"   • Trend:            {sma_trend}")

        print(f"\n   • ADX:              {s.get('adx', 0):.1f}")
        if s.get('adx', 0) > 40:
            adx_label = "VERY STRONG trend (high conviction)"
        elif s.get('adx', 0) > 25:
            adx_label = "STRONG trend (tradeable)"
        elif s.get('adx', 0) > 20:
            adx_label = "WEAK trend (caution!)"
        else:
            adx_label = "NO TREND (AVOID trading this!)"
        print(f"   • ADX Meaning:      {adx_label}")

        print(f"\n   • RSI (14):         {s['rsi']:.2f}")
        if s.get('in_strong_momentum') and s['rsi'] > 70:
            rsi_label = "HIGH RSI but in STRONG MOMENTUM (continuation signal)"
        elif s['rsi'] > 70:
            rsi_label = "OVERBOUGHT (no momentum support = risky)"
        elif s['rsi'] < 30:
            rsi_label = "OVERSOLD (potential bounce)"
        elif 40 < s['rsi'] < 60:
            rsi_label = "NEUTRAL (healthy)"
        else:
            rsi_label = "NORMAL"
        print(f"   • RSI Status:       {rsi_label}")

        print(f"\n   • MACD Histogram:   {s.get('macd_histogram', 0):.4f}")
        macd_status = "BULLISH" if s.get('macd_histogram', 0) > 0 else "BEARISH"
        print(f"   • MACD Status:      {macd_status}")

        print(f"\n   • Bollinger Band:   {s.get('bb_position', 'N/A')}")

        # Safety status
        if s.get('safety_warnings'):
            print("\n   WARNINGS:")
            for w in s['safety_warnings']:
                print(f"      • {w}")

    # Summary and recommendations
    print("\n" + "="*100)
    print("TECHNICAL SUMMARY v2.0")
    print("="*100)

    # Market regime
    print(f"\nMARKET REGIME: {mkt.get('status', 'UNKNOWN')} | Score Multiplier: {mkt.get('multiplier', 1.0):.1f}x")

    avoid_stocks = [s for s in signals if s['signal'] == 'AVOID']
    strong_buy = [s for s in safe_signals if s['signal'] == 'STRONG BUY']
    buy = [s for s in safe_signals if s['signal'] == 'BUY']
    hold = [s for s in safe_signals if s['signal'] == 'HOLD']
    sell = [s for s in safe_signals if s['signal'] == 'SELL']
    strong_sell = [s for s in safe_signals if s['signal'] == 'STRONG SELL']

    if avoid_stocks:
        tickers = [s['ticker'] for s in avoid_stocks]
        print(f"\n⛔ AVOID:       {len(avoid_stocks)} stocks (suspended/illiquid) - {tickers}")

    if strong_buy:
        # Only show strong buys with good ADX
        good_buys = [s for s in strong_buy if s.get('adx', 0) > 20]
        weak_buys = [s for s in strong_buy if s.get('adx', 0) <= 20]
        if good_buys:
            tickers = [f"{s['ticker']}(ADX:{s.get('adx',0):.0f})" for s in good_buys]
            print(f"\n🟢🟢 STRONG BUY: {len(good_buys)} stocks - {tickers}")
        if weak_buys:
            tickers = [f"{s['ticker']}(ADX:{s.get('adx',0):.0f})" for s in weak_buys]
            print(f"   ⚠ Weak-trend STRONG BUY: {len(weak_buys)} stocks (ADX < 20, risky!) - {tickers}")
    if buy:
        tickers = [s['ticker'] for s in buy]
        print(f"🟢 BUY:         {len(buy)} stocks - {tickers}")
    if hold:
        print(f"🟡 HOLD:        {len(hold)} stocks")
    if sell:
        tickers = [s['ticker'] for s in sell]
        print(f"🔴 SELL:        {len(sell)} stocks - {tickers}")
    if strong_sell:
        tickers = [s['ticker'] for s in strong_sell]
        print(f"🔴🔴 STRONG SELL: {len(strong_sell)} stocks - {tickers}")

    # WHEN TO SELL - Clear price/percent targets for BUY & STRONG BUY stocks
    buy_candidates = [s for s in safe_signals if s['signal'] in ('BUY', 'STRONG BUY')]
    if buy_candidates:
        print(f"\n{'='*120}")
        print("WHEN TO SELL - Action Levels (v2.2 Trailing Stop System)")
        print(f"{'='*120}")
        print(f"  {'Ticker':<10} {'Buy @':<14} {'Hard Stop':<14} {'Breakeven @':<14} {'Trail Start @':<14} {'Target':<14}")
        print(f"  {'':<10} {'(entry)':<14} {'({0}%)'.format(STOP_LOSS_PCT):<14} {'(+{0}%)'.format(TRAILING_BREAKEVEN_PCT):<14} {'(+{0}%)'.format(TRAILING_START_PCT):<14} {'(+{0}%)'.format(TARGET_PROFIT_PCT):<14}")
        print(f"  {'-'*110}")
        for s in buy_candidates[:15]:
            ticker = s['ticker']
            price = s['price']
            sl_price = price * (1 + STOP_LOSS_PCT / 100)
            be_price = price * (1 + TRAILING_BREAKEVEN_PCT / 100)
            trail_price = price * (1 + TRAILING_START_PCT / 100)
            tp_price = price * (1 + TARGET_PROFIT_PCT / 100)
            print(f"  {ticker:<10} IDR {price:>8,.0f}   IDR {sl_price:>8,.0f}   IDR {be_price:>8,.0f}     IDR {trail_price:>8,.0f}     IDR {tp_price:>8,.0f}")
        if len(buy_candidates) > 15:
            print(f"  ... and {len(buy_candidates) - 15} more (see detailed analysis)")
        print("\n  HOW THE TRAILING STOP WORKS:")
        print(f"  1. Buy stock → Stop at {STOP_LOSS_PCT}% below entry (hard floor)")
        print(f"  2. Stock hits +{TRAILING_BREAKEVEN_PCT}% → Stop moves UP to breakeven (entry price)")
        print(f"  3. Stock hits +{TRAILING_START_PCT}% → Stop trails at -{TRAILING_DISTANCE_PCT}% below the PEAK price")
        print(f"  4. Stock hits +{TRAILING_TIGHT_TRIGGER_PCT}% → Stop tightens to -{TRAILING_TIGHT_DISTANCE_PCT}% below peak (locks more profit)")
        print("  The stop NEVER moves down. It only moves UP to protect more profit.")
        print("\n  Edit TRAILING_* config at top of script to customize phases.")

    if safe_signals:
        print(f"\nTOP PICK: {safe_signals[0]['ticker']} (Score: {safe_signals[0].get('technical_score', 0):.0f}/100 | ADX: {safe_signals[0].get('adx', 0):.0f} | R:R: {safe_signals[0].get('risk_reward', 0):.1f}:1)")
        print(f"WORST:    {safe_signals[-1]['ticker']} (Score: {safe_signals[-1].get('technical_score', 0):.0f}/100)")

    print(f"\nTotal analyzed: {len(signals)} | Safe: {len(safe_signals)} | Unsafe: {len(unsafe_signals)} | Suspended: {skipped_suspended}")

    # v2.1 improvements summary
    print(f"\n{'='*100}")
    print("v2.1 FEATURES ACTIVE:")
    print("  [✓] Time Series Analysis (ROC, slope, acceleration, momentum persistence)")
    print("  [✓] Relative Strength vs IHSG (outperforming stocks rank higher)")
    print("  [✓] OBV Smart Money Flow (accumulation vs distribution)")
    print("  [✓] Momentum-aware RSI (RSI > 70 in strong trend = continuation, not sell)")
    print("  [✓] Suspension detection (zero volume, price freeze, stale data)")
    print(f"  [✓] Liquidity filter (min {MIN_AVG_VOLUME:,} avg daily volume)")
    print(f"  [✓] Market regime check (IHSG/JCI trend = {mkt.get('status', 'UNKNOWN')})")
    print("  [✓] ADX trend strength + Multi-timeframe confirmation")
    print("  [✓] ATR-based stop-loss + Risk/Reward ratio")
    print(f"  [✓] TRAILING STOP SYSTEM (v2.2): Breakeven at +{TRAILING_BREAKEVEN_PCT}%, Trail at +{TRAILING_START_PCT}% / -{TRAILING_DISTANCE_PCT}%, Tight at +{TRAILING_TIGHT_TRIGGER_PCT}% / -{TRAILING_TIGHT_DISTANCE_PCT}%")
    print(f"  [✓] WHEN TO SELL: Target +{TARGET_PROFIT_PCT:.0f}% | Hard Stop {STOP_LOSS_PCT:.0f}% | Trailing enabled: {TRAILING_STOP_ENABLED}")

    print("\nDISCLAIMER: Technical analysis with safety filters. Still high risk!")
    print("             ALWAYS use stop-loss. NEVER ignore suspended stock warnings.")
    print("             This is for educational purposes only. Not financial advice.")
    print("="*100 + "\n")

    return signals


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def analyze_single_stock(ticker: str, optimize: bool = True):
    """
    Analyze a single stock with backtesting
    
    Args:
        ticker: Stock ticker symbol
        optimize: Whether to optimize parameters
    """
    # Download data
    data = download_stock_data(ticker, START_DATE, END_DATE)

    if data is None or len(data) < 200:
        print(f"✗ Insufficient data for {ticker}, skipping...")
        return None

    # Run backtest
    stats, bt = run_backtest(data, ticker, optimize=optimize)

    # Print results
    print_results(stats, ticker, data)

    return stats


def analyze_watchlist(optimize: bool = True):
    """
    Analyze all stocks in the watchlist
    
    Args:
        optimize: Whether to optimize parameters for each stock
    """
    print("\n" + "="*60)
    print("KALA - ALGORITHMIC TRADING ENGINE")
    print("="*60)
    print(f"Capital:     IDR {INITIAL_CAPITAL:,}")
    print(f"Commission:  {COMMISSION*100:.2f}%")
    print(f"Watchlist:   {len(WATCHLIST)} stocks")
    print(f"Period:      {START_DATE} to {END_DATE}")
    print("="*60)

    results = {}

    for ticker in WATCHLIST:
        try:
            stats = analyze_single_stock(ticker, optimize=optimize)
            if stats is not None:
                results[ticker] = stats
        except Exception as e:
            print(f"\n✗ Error analyzing {ticker}: {str(e)}\n")
            continue

    # Print summary
    if results:
        print("\n" + "="*60)
        print("PORTFOLIO SUMMARY")
        print("="*60)
        print(f"{'Ticker':<12} {'Return':<12} {'Win Rate':<12} {'Sharpe':<10}")
        print("─"*60)

        for ticker, stats in results.items():
            ret = stats['Return [%]']
            wr = stats['Win Rate [%]']
            sharpe = stats['Sharpe Ratio']
            print(f"{ticker:<12} {ret:>10.2f}% {wr:>10.2f}% {sharpe:>10.2f}")

        print("="*60)


def main():
    """Main entry point - Technical-Only Day Trading"""

    # Start logging to file
    dual_output, log_file, timestamp = start_logging()

    try:
        # ====================================================================
        # KALA DAY TRADER - TECHNICAL ONLY MODE
        # ====================================================================

        print("\nKALA - DAY TRADER v2.2 (TECHNICAL + SAFETY + TRAILING STOP)")
        print(f"{'='*100}")
        print(f"v2.2: Trailing stop system, adjusted targets (+{TARGET_PROFIT_PCT}% / {STOP_LOSS_PCT}%), breakeven lock")
        print(f"Analysis Date: {now().strftime('%A, %B %d, %Y at %H:%M:%S')} WIB")
        print(f"Total DES Stocks Available: {len(ALL_SHARIA_STOCKS)}")
        print(f"Currently analyzing: {len(WATCHLIST)} stocks")
        print(f"Estimated time: ~{max(30, len(WATCHLIST) // 3)} seconds (batch download optimized)")
        print(f"{'='*100}\n")

        # LIVE TECHNICAL SIGNALS with safety filters
        # Run time: ~1-2 minutes for Top 30 JII
        signals = live_trading_dashboard()

        # Save to CSV
        csv_file = None
        if signals:
            csv_file = save_to_csv(signals, timestamp)

        # ================================================================
        # PORTFOLIO OPTIMIZATION (HRP - Volatility Targeting)
        # Tells you EXACTLY how many lots to buy of each stock.
        # Allocates LESS to volatile stocks for balanced risk.
        # ================================================================
        if signals:
            try:
                from portfolio_optimizer import optimize_from_signals

                portfolio = optimize_from_signals(
                    signals,
                    total_capital=INITIAL_CAPITAL,
                    strategy='hrp',         # HRP for short-term trading
                    top_n=10,               # Max 10 stocks in portfolio
                    min_score=65,           # Only BUY and STRONG BUY
                    score_key='technical_score',
                )
            except ImportError:
                print("\n  [Portfolio Optimizer not available - pip install pypfopt]")
            except Exception as e:
                print(f"\n  [Portfolio optimization error: {e}]")

        # ALTERNATIVE MODES (uncomment to use):

        # MODE 2: MONITOR YOUR POSITIONS (Check when to sell stocks you own)
        # Replace with your actual positions:
        # TIP: Include 'peak_price' = highest price since you bought for accurate trailing stops!
        # my_positions = [
        #     {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000, 'peak_price': 5800},
        #     {'ticker': 'TLKM.JK', 'entry_price': 3500, 'shares': 500, 'peak_price': 3700},
        #     {'ticker': 'ASII.JK', 'entry_price': 4800, 'shares': 200},  # no peak = assumes current
        # ]
        # monitor_portfolio(my_positions)

        # MODE 3: CHECK SINGLE STOCK EXIT SIGNAL (with trailing stop)
        # exit_signal = check_exit_signals('BBRI.JK', entry_price=5200, peak_price=5800)
        # if exit_signal['exit_signal']:
        #     print(f"\n🔴 SELL SIGNAL for {exit_signal['ticker']}!")
        #     print(f"   P/L: {exit_signal['profit_pct']:+.2f}%")
        #     print(f"   Trail Phase: {exit_signal['trailing_phase_name']}")
        #     print(f"   Trail Stop: IDR {exit_signal['trailing_stop_price']:,.0f}")
        #     print(f"   Locked Profit: {exit_signal['profit_locked_pct']:+.1f}%")
        #     for reason in exit_signal['reasons']:
        #         print(f"   • {reason}")

        # MODE 4: QUICK TEST (First 10 stocks only)
        # global WATCHLIST
        # WATCHLIST = WATCHLIST[:10]
        # signals = live_trading_dashboard()
        # if signals:
        #     csv_file = save_to_csv(signals, timestamp)

        # MODE 5: BACKTEST MODE (Test strategy on historical data)
    # analyze_watchlist(optimize=False)

        # MODE 6: SINGLE STOCK BACKTEST (Detailed analysis)
        # analyze_single_stock('BBRI.JK', optimize=False)

        # Success message
        print(f"\n{'='*100}")
        print("ANALYSIS COMPLETE!")
        print(f"{'='*100}")
        print("\nSAVED FILES:")
        print(f"   Full Report (TXT): {os.path.basename(log_file)}")
        if signals and csv_file:
            print(f"   Summary (CSV):     {os.path.basename(csv_file)}")
        print(f"\nLocation: {os.path.abspath('results')}")
        print("\nTIP: Open the CSV file in Excel for easy sorting and filtering!")
        print("     Sort by 'Technical_Score' column to see best opportunities!")
        print("\nWARNING: Use stop-loss orders! Technical analysis is HIGH RISK!")
        print(f"{'='*100}\n")

    except Exception as e:
        print(f"\nERROR OCCURRED: {str(e)}")
        print(f"Partial results saved to: {log_file}")
        raise

    finally:
        # Close the log file
        dual_output.close()


if __name__ == '__main__':
    main()
