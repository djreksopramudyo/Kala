"""
Kala - Advanced Algorithmic Trading Engine for Indonesian Stock Market
=============================================================================

Installation:
    pip install -r requirements.txt

Usage:
    python kala_engine.py

Features:
    1. 🔴 LIVE TRADING SIGNALS - Real-time BUY/SELL/HOLD recommendations
    2. 📊 MULTI-FACTOR ANALYSIS - 5-factor composite scoring system
    3. 🔬 PARAMETER OPTIMIZATION - Find optimal SMA settings per stock
    4. 💰 P&L BACKTESTING - Test strategy performance vs Buy & Hold
    5. 📄 AUTO-SAVE RESULTS - Saves to TXT and CSV files automatically

6-Factor Analysis (v2.1 - with Time Series):
    1. Technical (30%)   - SMA Crossover + RSI (momentum-aware)
    2. Momentum (10%)    - Time Series: ROC, slope, OBV, relative strength vs IHSG
    3. Fundamental (25%) - P/E, P/B, ROE, Debt/Equity, Profit Margin
    4. Volume (15%)      - Confirmation of price moves
    5. Macro (10%)       - USD/IDR, Oil prices, Commodities
    6. Sentiment (10%)   - Multi-source news analysis

News Sources (8 Total):
    TIER 1 - OFFICIAL:
    - IDX Official (idx.co.id) - Exchange announcements & corporate actions ⭐
    
    TIER 2 - INTERNATIONAL:
    - Yahoo Finance - Bloomberg, Reuters, MarketWatch
    
    TIER 3 - INDONESIAN MEDIA:
    - IDX Channel - Specialized stock market news portal ⭐
    - CNBC Indonesia - Leading business news
    - Kontan - Top financial newspaper (trader favorite)
    - Bisnis Indonesia - Established business publication
    - Detik Finance - Popular financial portal

Strategy:
    - Entry: Golden Cross (Fast SMA > Slow SMA) + RSI < 70
    - Exit: Death Cross (Fast SMA < Slow SMA)
    - Default: 10-day Fast SMA, 50-day Slow SMA, 14-day RSI

Coverage:
    - 672 Sharia-compliant stocks (OJK Daftar Efek Syariah)
    - All sectors: Banking, Mining, Consumer, Property, etc.

Author: Senior Python Quantitative Developer
Target: Indonesian retail algorithmic traders
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
import random
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import numpy as np

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
# TIME SERIES ANALYSIS - Momentum, Trend Slope, Relative Strength
# ============================================================================

_ihsg_ts_data = None  # Cache for IHSG returns

def get_ihsg_ts_returns():
    """Download and cache IHSG daily returns for relative strength calculations."""
    global _ihsg_ts_data
    if _ihsg_ts_data is not None:
        return _ihsg_ts_data
    try:
        end_date = now().replace(tzinfo=None)
        start_date = end_date - timedelta(days=100)
        jci = yf.download('^JKSE', start=start_date, end=end_date, progress=False)
        if jci.empty or len(jci) < 20:
            _ihsg_ts_data = {}
            return _ihsg_ts_data
        if isinstance(jci.columns, pd.MultiIndex):
            jci.columns = jci.columns.get_level_values(0)
        close = jci['Close']
        _ihsg_ts_data = {
            'roc_5': ((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]) * 100 if len(close) >= 5 else 0,
            'roc_10': ((close.iloc[-1] - close.iloc[-10]) / close.iloc[-10]) * 100 if len(close) >= 10 else 0,
            'roc_20': ((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20]) * 100 if len(close) >= 20 else 0,
        }
        return _ihsg_ts_data
    except:
        _ihsg_ts_data = {}
        return _ihsg_ts_data


def calculate_time_series_score(data: pd.DataFrame):
    """
    Time Series Analysis for momentum detection.
    
    Calculates:
    - Rate of Change (5d, 10d, 20d)
    - Linear regression slope
    - Trend acceleration
    - On Balance Volume (OBV) trend
    - Relative strength vs IHSG
    - Momentum persistence score (0-100)
    
    Returns dict with metrics or None if insufficient data.
    """
    if data.empty or len(data) < 20:
        return None

    close = data['Close']
    volume = data['Volume']

    try:
        # ROC
        roc_5 = ((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]) * 100 if len(close) >= 5 else 0
        roc_10 = ((close.iloc[-1] - close.iloc[-10]) / close.iloc[-10]) * 100 if len(close) >= 10 else 0
        roc_20 = ((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20]) * 100 if len(close) >= 20 else 0

        # Linear regression slope (last 20 days)
        recent_20 = close.tail(20).values
        slope_20 = np.polyfit(np.arange(len(recent_20)), recent_20, 1)[0] if len(recent_20) >= 20 else 0
        slope_pct = (slope_20 / recent_20[0]) * 100 if recent_20[0] != 0 else 0

        # Acceleration
        if len(close) >= 20:
            slope_recent = np.polyfit(np.arange(10), close.tail(10).values, 1)[0]
            slope_prev = np.polyfit(np.arange(10), close.iloc[-20:-10].values, 1)[0]
            acceleration = slope_recent - slope_prev
        else:
            acceleration = 0

        # OBV
        obv = pd.Series(0.0, index=data.index)
        for i in range(1, len(data)):
            if close.iloc[i] > close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
            elif close.iloc[i] < close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]
        obv_trend = 'ACCUMULATION' if obv.iloc[-1] > obv.iloc[-10] else 'DISTRIBUTION'

        # Relative strength vs IHSG
        ihsg = get_ihsg_ts_returns()
        rs_5 = roc_5 - ihsg.get('roc_5', 0)
        rs_20 = roc_20 - ihsg.get('roc_20', 0)
        avg_rs = (rs_5 + rs_20) / 2

        # Momentum persistence score (0-100)
        mp = 0
        if roc_5 > 10: mp += 15
        elif roc_5 > 5: mp += 10
        elif roc_5 > 0: mp += 5

        if roc_20 > 20: mp += 15
        elif roc_20 > 10: mp += 10
        elif roc_20 > 0: mp += 5

        if slope_pct > 1.0: mp += 20
        elif slope_pct > 0.5: mp += 15
        elif slope_pct > 0.2: mp += 10
        elif slope_pct > 0: mp += 5

        if acceleration > 0:
            mp += min(15, int(acceleration))

        if avg_rs > 10: mp += 15
        elif avg_rs > 5: mp += 10
        elif avg_rs > 0: mp += 5

        if obv_trend == 'ACCUMULATION' and roc_5 > 0: mp += 10
        elif obv_trend == 'ACCUMULATION': mp += 5

        mp = min(100, mp)

        return {
            'roc_5': roc_5, 'roc_10': roc_10, 'roc_20': roc_20,
            'slope_pct': slope_pct, 'acceleration': acceleration,
            'is_accelerating': acceleration > 0,
            'obv_trend': obv_trend,
            'avg_relative_strength': avg_rs,
            'is_outperforming': avg_rs > 0,
            'momentum_persistence': mp,
        }
    except:
        return None


# ============================================================================
# OUTPUT LOGGER - Save results to file
# ============================================================================

class DualOutput:
    """Write output to both console and file"""
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w', encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
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
    filename = f'results/kala_{timestamp}.txt'

    # Start dual output
    dual_output = DualOutput(filename)
    sys.stdout = dual_output

    print(f"📝 Results will be saved to: {filename}")
    print("="*100 + "\n")

    return dual_output, filename, timestamp


def save_to_csv(signals, timestamp):
    """Save results summary to CSV for easy viewing"""
    if not signals:
        return None

    # Create CSV filename
    csv_file = f'results/kala_{timestamp}.csv'

    # Prepare data for CSV
    data = []
    for s in signals:
        row = {
            'Ticker': s['ticker'],
            'Date': s['date'].strftime('%Y-%m-%d'),
            'Price_IDR': f"{s['price']:.0f}",
            'Daily_Change_%': f"{s['daily_change']:.2f}",
            'Signal': s.get('composite_signal', s['signal']),
            'Composite_Score': f"{s.get('composite_score', 0):.0f}",
            'Technical_Score': f"{s.get('technical_score', 0):.0f}",
            'Momentum_Score': f"{s.get('momentum_persistence', 0):.0f}",
            'Fundamental_Score': f"{s.get('fundamental_score', 0):.0f}",
            'Volume_Score': f"{s.get('volume_score', 0):.0f}",
            'Macro_Score': f"{s.get('macro_score', 0):.0f}",
            'Sentiment_Score': f"{s.get('sentiment_score', 0):.0f}",
            'RSI': f"{s['rsi']:.1f}",
            'ROC_5d_%': f"{s.get('roc_5', 0):.2f}",
            'ROC_20d_%': f"{s.get('roc_20', 0):.2f}",
            'Relative_Strength_vs_IHSG': f"{s.get('avg_relative_strength', 0):.2f}",
            'OBV_Trend': s.get('obv_trend', 'N/A'),
            'Fast_SMA': f"{s['sma_fast']:.2f}",
            'Slow_SMA': f"{s['sma_slow']:.2f}",
        }
        data.append(row)

    # Create DataFrame and save
    df = pd.DataFrame(data)
    df.to_csv(csv_file, index=False)

    return csv_file


# ============================================================================
# CONFIGURATION BLOCK
# ============================================================================

INITIAL_CAPITAL = 10_000_000  # 20 Juta IDR
COMMISSION = 0.0019  # 0.19% standard Indonesian brokerage fee

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

# OPTION 1: Top 30 Blue Chips (~5-8 min with IDX integration)
# WATCHLIST = TOP_30_JII

# OPTION 2: Quick Test (~2 min)
# WATCHLIST = TOP_30_JII[:10]

# OPTION 3: Full DES - ALL 672 stocks (now safe with Phase 1 batch download + pre-filter)
WATCHLIST = ALL_SHARIA_STOCKS

# OPTION 4: Sector-specific
# WATCHLIST = MINING + BANKING

# OPTION 5: Custom selection
# WATCHLIST = ['BBRI.JK', 'TLKM.JK', 'ANTM.JK']

# Backtest period
START_DATE = '2020-01-01'
END_DATE = now().strftime('%Y-%m-%d')  # Indonesian time

# Default strategy parameters
DEFAULT_FAST_SMA = 10
DEFAULT_SLOW_SMA = 50
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_THRESHOLD = 70

# Parallel analysis threads (for fundamental + sentiment per-stock calls)
# ⚠️ Keep low to avoid Yahoo Finance rate limits on .info/.news calls
# The pre-filter eliminates dead stocks first, so this only hits qualified ones
MAX_WORKERS = 5

# Optimization ranges (reduced for faster execution)
FAST_SMA_RANGE = range(5, 25, 5)  # [5, 10, 15, 20] - 4 values
SLOW_SMA_RANGE = range(30, 100, 20)  # [30, 50, 70, 90] - 4 values


# ============================================================================
# ADVANCED ANALYTICS: FUNDAMENTALS, VOLUME, MACRO, SENTIMENT
# ============================================================================

def get_fundamental_data(ticker: str, max_retries: int = 3):
    """
    Fetch fundamental data for a stock with retry on auth/rate errors
    
    Args:
        ticker: Stock ticker symbol
        max_retries: Maximum retry attempts
    
    Returns:
        Dictionary with fundamental metrics
    """
    for attempt in range(max_retries):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            if info is None or 'trailingPE' not in info and 'currentPrice' not in info:
                raise ValueError("Empty info response - possible auth failure")

            # Extract key fundamentals
            fundamentals = {
                'pe_ratio': info.get('trailingPE', None),
                'forward_pe': info.get('forwardPE', None),
                'pb_ratio': info.get('priceToBook', None),
                'debt_to_equity': info.get('debtToEquity', None),
                'roe': info.get('returnOnEquity', None),
                'profit_margin': info.get('profitMargins', None),
                'market_cap': info.get('marketCap', None),
                'dividend_yield': info.get('dividendYield', None),
                'beta': info.get('beta', None),
            }

            return fundamentals

        except Exception as e:
            error_msg = str(e)
            is_retryable = any(kw in error_msg for kw in [
                "Too Many Requests", "429", "401", "Unauthorized",
                "Invalid Crumb", "unable to access", "NoneType", "Empty info"
            ])
            if is_retryable and attempt < max_retries - 1:
                time.sleep(8 * (2 ** attempt))
                continue
            return None

    return None


def analyze_fundamentals(fundamentals: dict):
    """
    Score fundamentals (0-100, higher is better)
    
    Args:
        fundamentals: Dictionary with fundamental metrics
    
    Returns:
        Score and analysis text
    """
    if not fundamentals:
        return 50, "No data available"

    score = 0
    reasons = []
    max_score = 0

    # P/E Ratio (lower is better, but not too low)
    if fundamentals.get('pe_ratio'):
        max_score += 20
        pe = fundamentals['pe_ratio']
        if 5 < pe < 15:
            score += 20
            reasons.append(f"✓ Good P/E ({pe:.1f})")
        elif 15 <= pe < 25:
            score += 10
            reasons.append(f"~ Moderate P/E ({pe:.1f})")
        else:
            reasons.append(f"✗ High/Low P/E ({pe:.1f})")

    # P/B Ratio (lower is better)
    if fundamentals.get('pb_ratio'):
        max_score += 20
        pb = fundamentals['pb_ratio']
        if pb < 1.5:
            score += 20
            reasons.append(f"✓ Low P/B ({pb:.2f})")
        elif pb < 3:
            score += 10
            reasons.append(f"~ Moderate P/B ({pb:.2f})")
        else:
            reasons.append(f"✗ High P/B ({pb:.2f})")

    # Debt to Equity (lower is better)
    if fundamentals.get('debt_to_equity'):
        max_score += 20
        de = fundamentals['debt_to_equity']
        if de < 50:
            score += 20
            reasons.append(f"✓ Low debt ({de:.1f}%)")
        elif de < 100:
            score += 10
            reasons.append(f"~ Moderate debt ({de:.1f}%)")
        else:
            reasons.append(f"✗ High debt ({de:.1f}%)")

    # ROE (higher is better)
    if fundamentals.get('roe'):
        max_score += 20
        roe = fundamentals['roe'] * 100
        if roe > 15:
            score += 20
            reasons.append(f"✓ Strong ROE ({roe:.1f}%)")
        elif roe > 10:
            score += 10
            reasons.append(f"~ Good ROE ({roe:.1f}%)")
        else:
            reasons.append(f"✗ Weak ROE ({roe:.1f}%)")

    # Profit Margin (higher is better)
    if fundamentals.get('profit_margin'):
        max_score += 20
        margin = fundamentals['profit_margin'] * 100
        if margin > 15:
            score += 20
            reasons.append(f"✓ High margin ({margin:.1f}%)")
        elif margin > 5:
            score += 10
            reasons.append(f"~ Good margin ({margin:.1f}%)")
        else:
            reasons.append(f"✗ Low margin ({margin:.1f}%)")

    # Normalize score to 0-100
    if max_score > 0:
        final_score = (score / max_score) * 100
    else:
        final_score = 50  # Neutral if no data

    analysis = "; ".join(reasons) if reasons else "Limited data"

    return final_score, analysis


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


def get_macro_indicators():
    """
    Fetch macro indicators relevant to Indonesian market
    
    Returns:
        Dictionary with macro data
    """
    try:
        # USD/IDR exchange rate
        usdidr = yf.Ticker('IDR=X')
        idr_data = usdidr.history(period='5d')

        if not idr_data.empty:
            current_idr = idr_data['Close'].iloc[-1]
            prev_idr = idr_data['Close'].iloc[0]
            idr_change = ((current_idr - prev_idr) / prev_idr) * 100
        else:
            current_idr = None
            idr_change = 0

        # Crude Oil (relevant for Indonesian energy stocks)
        oil = yf.Ticker('CL=F')
        oil_data = oil.history(period='5d')

        if not oil_data.empty:
            current_oil = oil_data['Close'].iloc[-1]
            prev_oil = oil_data['Close'].iloc[0]
            oil_change = ((current_oil - prev_oil) / prev_oil) * 100
        else:
            current_oil = None
            oil_change = 0

        return {
            'usd_idr': current_idr,
            'usd_idr_change': idr_change,
            'oil_price': current_oil,
            'oil_change': oil_change,
            'commodity_trend': oil_change,
        }

    except Exception:
        return {
            'usd_idr': None,
            'usd_idr_change': 0,
            'oil_price': None,
            'oil_change': 0,
            'commodity_trend': 0,
        }


def analyze_macro_impact(ticker: str, macro: dict):
    """
    Analyze how macro factors affect the stock
    
    Args:
        ticker: Stock ticker
        macro: Macro indicators dictionary
    
    Returns:
        Score (0-100) and analysis
    """
    score = 50  # Neutral default
    reasons = []

    # Sector-specific analysis
    if 'ANTM' in ticker:
        # Mining stock - benefits from commodity strength
        if macro['commodity_trend'] > 2:
            score += 20
            reasons.append(f"✓ Commodities up ({macro['commodity_trend']:.1f}%)")
        elif macro['commodity_trend'] < -2:
            score -= 20
            reasons.append(f"✗ Commodities down ({macro['commodity_trend']:.1f}%)")

    # IDR weakness generally helps exporters
    if macro['usd_idr_change'] > 1:
        score += 10
        reasons.append("✓ IDR weaker (good for exporters)")
    elif macro['usd_idr_change'] < -1:
        score -= 10
        reasons.append("✗ IDR stronger")

    # Ensure score stays in range
    score = max(0, min(100, score))

    analysis = "; ".join(reasons) if reasons else "Neutral macro environment"

    return score, analysis


# ----------------------------------------------------------------------------
# News scraping + sentiment — DELEGATED to the shared, single-owner module
# (kala/news.py), same treatment check_exit_signals got. The function
# names and return contracts are unchanged so every caller in this file keeps
# working; the implementations now live in exactly one place, shared with the
# daily scheduler and the Telegram bot.
# ----------------------------------------------------------------------------
from kala.news import (  # noqa: E402
    get_news_sentiment,
    scrape_idx_announcements,
    scrape_indonesian_news,
    translate_to_english,
)

# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class ShariaStrategy:
    """DEPRECATED (v3.1): old crossover/no-stop backtest strategy, no longer used.
    run_backtest goes through kala.backtest_ticker (live ruleset)."""
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

        return df

    except Exception as e:
        print(f"✗ Error downloading {ticker}: {str(e)}")
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
    Backtest the strategy you ACTUALLY trade (v3.0).

    Previously this ran ``ShariaStrategy`` -- a golden-cross / death-cross system
    with NO stops -- and optionally curve-fit the SMA periods in-sample. That
    measured a strategy you don't trade and overfit the parameters to history.

    It now runs the same engine the live system uses (``kala.backtest``):
    composite-score entries, the governing/trailing-stop exit ladder, IDX
    limit-down ("ARB") carry, and asymmetric buy/sell/tax/spread costs. So the
    number you validate here is the number you run live.

    The ``optimize`` flag is kept for call-site compatibility but ignored --
    in-sample optimization was removed because it overfits.

    Returns ``(stats_dict, None)``; ``stats_dict`` is print_results-compatible.
    """
    import numpy as _np

    from kala.backtest import backtest_ticker
    from kala.config import Config

    print(f"\n{'-'*60}")
    print(f"BACKTESTING {ticker}  (live ruleset: stops + trailing + ARB + costs)")
    print(f"{'-'*60}")
    if optimize:
        print("  note: in-sample SMA optimization removed (overfitting); running honest engine.")

    cfg = Config()  # canonical risk model + realistic IDX cost model
    res = backtest_ticker(ticker, data, _get_ihsg_benchmark(), cfg)

    trades = res.closed
    n = len(trades)
    rets = [t.net_return_pct for t in trades]
    win_rate = (sum(1 for r in rets if r > 0) / n * 100.0) if n else 0.0

    # trade-by-trade equity curve -> total return + max drawdown
    equity = float(INITIAL_CAPITAL)
    curve = [equity]
    for r in rets:
        equity *= (1.0 + r / 100.0)
        curve.append(equity)
    total_return = (curve[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    peak = curve[0]; max_dd = 0.0
    for eq in curve:
        peak = max(peak, eq)
        max_dd = min(max_dd, (eq / peak - 1.0) * 100.0)

    # per-trade Sharpe (mean/std of trade returns) -- a comparator, not annualised
    sharpe = (_np.mean(rets) / _np.std(rets)) if (n > 1 and _np.std(rets) > 0) else 0.0
    locked_exits = sum(1 for t in trades if getattr(t, 'arb_locked_bars', 0) > 0)
    avg = _np.mean(rets) if n else 0.0

    print(f"  trades={n}  win_rate={win_rate:.1f}%  avg_net/trade={avg:+.2f}%  "
          f"max_dd={max_dd:.1f}%  ARB-locked exits={locked_exits}")

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
        'Sharpe Ratio': sharpe,            # per-trade Sharpe of net returns
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
    except:
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

    # Performance verdict
    if strategy_return > buy_hold_return and win_rate > 50:
        verdict = "✓ STRATEGY OUTPERFORMED"
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

    # v3.0 - delegates to kala.indicators. Two fixes vs. the old version:
    #   * does NOT mutate the caller's DataFrame (it used to write SMA_*/RSI cols)
    #   * uses Wilder's RSI, not a simple rolling mean
    from kala import indicators as _ind
    close = data['Close']
    sma_fast = _ind.sma(close, fast_period)
    sma_slow = _ind.sma(close, slow_period)
    rsi = _ind.rsi(close, rsi_period)

    return {
        'close': float(close.iloc[-1]),
        'sma_fast': float(sma_fast.iloc[-1]),
        'sma_slow': float(sma_slow.iloc[-1]),
        'rsi': float(rsi.iloc[-1]),
        'prev_sma_fast': float(sma_fast.iloc[-2]),
        'prev_sma_slow': float(sma_slow.iloc[-2]),
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
# BATCH DOWNLOAD - Download all price data at once (massive speedup)
# ============================================================================

def batch_download_prices(tickers: list, days: int = 200):
    """
    Download price data for ALL tickers at once.
    Instead of 672 individual API calls, this makes ~14 bulk requests.
    """
    end_date = now().replace(tzinfo=None)
    start_date = end_date - timedelta(days=days)

    print(f"\n  Batch downloading {len(tickers)} stocks...", flush=True)

    CHUNK_SIZE = 50
    all_stock_data = {}

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        chunk_num = (i // CHUNK_SIZE) + 1
        total_chunks = (len(tickers) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"  Downloading batch {chunk_num}/{total_chunks} ({len(chunk)} stocks)...", end=" ", flush=True)

        try:
            raw_data = yf.download(
                chunk, start=start_date, end=end_date,
                progress=False, threads=True, group_by='ticker'
            )

            if raw_data.empty:
                print("✗ Empty")
                continue

            if len(chunk) == 1:
                ticker = chunk[0]
                if not raw_data.empty:
                    all_stock_data[ticker] = raw_data.copy()
            else:
                for ticker in chunk:
                    try:
                        if ticker in raw_data.columns.get_level_values(0):
                            stock_df = raw_data[ticker].dropna(how='all')
                            if not stock_df.empty and len(stock_df) > 0:
                                all_stock_data[ticker] = stock_df.copy()
                    except (KeyError, TypeError):
                        pass

            print(f"✓ ({len([t for t in chunk if t in all_stock_data])}/{len(chunk)} OK)")

            if i + CHUNK_SIZE < len(tickers):
                time.sleep(2.0 if len(tickers) > 100 else 1.0)

        except Exception as e:
            print(f"✗ Error: {e}")
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
                    print("  ↳ Retry OK")
            except:
                print("  ↳ Retry failed, skipping chunk")

    print(f"  Total: {len(all_stock_data)}/{len(tickers)} stocks downloaded\n")
    return all_stock_data


def prefilter_stocks(all_price_data: dict, min_days: int = 30, min_avg_volume: int = 50000):
    """
    Pre-filter stocks using already-downloaded OHLCV data (ZERO API calls).
    
    Eliminates dead, suspended, and illiquid stocks BEFORE making
    expensive individual .info and .news API calls.
    
    Returns:
        dict of {ticker: DataFrame} for stocks that pass the filter
    """
    qualified = {}
    skipped = {'too_short': 0, 'low_volume': 0, 'suspended': 0, 'no_price': 0}

    cutoff_date = (now().replace(tzinfo=None) - timedelta(days=10))

    for ticker, df in all_price_data.items():
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if len(df) < min_days:
            skipped['too_short'] += 1
            continue

        last_trade = df.index[-1]
        if hasattr(last_trade, 'tz') and last_trade.tz is not None:
            last_trade = last_trade.tz_localize(None)
        if last_trade < cutoff_date:
            skipped['suspended'] += 1
            continue

        avg_vol = df['Volume'].tail(20).mean() if 'Volume' in df.columns else 0
        if avg_vol < min_avg_volume:
            skipped['low_volume'] += 1
            continue

        last_close = df['Close'].iloc[-1] if 'Close' in df.columns else 0
        if last_close <= 0:
            skipped['no_price'] += 1
            continue

        qualified[ticker] = df

    total_skipped = sum(skipped.values())
    print(f"  Pre-filter: {len(qualified)} qualified, {total_skipped} skipped")
    print(f"    (short history: {skipped['too_short']}, low volume: {skipped['low_volume']}, "
          f"suspended: {skipped['suspended']}, no price: {skipped['no_price']})")
    print(f"    → Saved ~{total_skipped * 3} unnecessary API calls (.info + .news + fundamentals)")

    return qualified


# ============================================================================
# MACRO DATA CACHE - Fetch once, reuse for all stocks
# ============================================================================

_macro_cache = None

def get_cached_macro_indicators():
    """Get macro indicators with caching (fetched ONCE, not per stock)"""
    global _macro_cache
    if _macro_cache is None:
        print("  Fetching macro indicators (once)...", end=" ", flush=True)
        _macro_cache = get_macro_indicators()
        print("✓")
    return _macro_cache


def get_live_signal(ticker: str, fast_sma: int = 10, slow_sma: int = 50,
                    advanced: bool = True, preloaded_data: pd.DataFrame = None,
                    cached_macro: dict = None):
    """
    Get current trading signal for a stock with advanced analytics
    
    Args:
        ticker: Stock ticker symbol
        fast_sma: Fast SMA period
        slow_sma: Slow SMA period
        advanced: Include fundamental, volume, macro, and sentiment analysis
        preloaded_data: Pre-downloaded price data (from batch download)
        cached_macro: Pre-fetched macro indicators (to avoid refetching per stock)
    
    Returns:
        Dictionary with comprehensive signal information
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

        # Calculate technical indicators
        indicators = calculate_live_indicators(data, fast_sma, slow_sma)

        if indicators is None:
            return None

        # Generate base signal
        signal, reason = generate_signal(indicators)

        # Calculate daily change
        current_price = indicators['close']
        prev_close = data['Close'].iloc[-2]
        daily_change = ((current_price - prev_close) / prev_close) * 100

        # Get latest date
        latest_date = data.index[-1]

        # ============================================================
        # TIME SERIES ANALYSIS (v2.1) - Momentum detection
        # ============================================================
        ts_metrics = calculate_time_series_score(data)

        # Base result
        result = {
            'ticker': ticker,
            'date': latest_date,
            'price': current_price,
            'daily_change': daily_change,
            'signal': signal,
            'reason': reason,
            'sma_fast': indicators['sma_fast'],
            'sma_slow': indicators['sma_slow'],
            'rsi': indicators['rsi'],
            'technical_score': 0,
            # Time series data
            'roc_5': ts_metrics.get('roc_5', 0) if ts_metrics else 0,
            'roc_20': ts_metrics.get('roc_20', 0) if ts_metrics else 0,
            'momentum_persistence': ts_metrics.get('momentum_persistence', 0) if ts_metrics else 0,
            'avg_relative_strength': ts_metrics.get('avg_relative_strength', 0) if ts_metrics else 0,
            'is_outperforming': ts_metrics.get('is_outperforming', False) if ts_metrics else False,
            'obv_trend': ts_metrics.get('obv_trend', 'N/A') if ts_metrics else 'N/A',
            'slope_pct': ts_metrics.get('slope_pct', 0) if ts_metrics else 0,
            'is_accelerating': ts_metrics.get('is_accelerating', False) if ts_metrics else False,
        }

        # Calculate technical score (now momentum-aware)
        # Base score from signal
        if signal == 'BUY':
            base_tech = 80
        elif signal == 'HOLD':
            base_tech = 60
        elif signal == 'CAUTION':
            base_tech = 45
        elif signal == 'SELL':
            base_tech = 25
        else:  # AVOID
            base_tech = 15

        # Adjust technical score with momentum (up to +20 or -10)
        if ts_metrics:
            mp = ts_metrics['momentum_persistence']
            if mp >= 70:
                base_tech = min(100, base_tech + 15)   # Strong momentum boost
            elif mp >= 50:
                base_tech = min(100, base_tech + 8)    # Moderate boost
            elif mp >= 30:
                base_tech = base_tech                   # Neutral
            elif mp < 15:
                base_tech = max(0, base_tech - 10)     # Negative momentum penalty

        result['technical_score'] = base_tech
        result['momentum_score'] = ts_metrics.get('momentum_persistence', 0) if ts_metrics else 0

        # Add advanced analytics if requested
        if advanced:
            # Fundamental analysis
            fundamentals = get_fundamental_data(ticker)
            fund_score, fund_analysis = analyze_fundamentals(fundamentals)
            result['fundamental_score'] = fund_score
            result['fundamental_analysis'] = fund_analysis
            result['fundamentals'] = fundamentals

            # Volume confirmation (uses pre-downloaded data - no API call)
            vol_score, vol_analysis = analyze_volume_confirmation(data, signal)
            result['volume_score'] = vol_score
            result['volume_analysis'] = vol_analysis

            # Macro impact (use cached data - NO API call per stock)
            macro = cached_macro if cached_macro else get_cached_macro_indicators()
            macro_score, macro_analysis = analyze_macro_impact(ticker, macro)
            result['macro_score'] = macro_score
            result['macro_analysis'] = macro_analysis
            result['macro_data'] = macro

            # News sentiment
            sentiment_score, news_count, sentiment_text = get_news_sentiment(ticker)
            result['sentiment_score'] = sentiment_score
            result['news_count'] = news_count
            result['sentiment_analysis'] = sentiment_text

            # ---- Composite score: FAIL LOUD, don't dilute ------------------
            # A scraped factor that failed used to fall back to a fake-neutral
            # 50 and silently drag the score toward the middle. Instead we DROP
            # unavailable factors and renormalise the weights over what we have,
            # then flag exactly what was missing.
            fund_available = bool(fundamentals)
            macro_available = bool(macro)
            # news_count == 0 covers BOTH failure paths ("DEGRADED: source
            # unavailable" AND "No recent news found") — the old string sniff
            # only caught the first, so a no-news day blended a phantom
            # neutral-50 sentiment into the composite instead of dropping it.
            sentiment_available = news_count > 0

            factors = {
                'technical':   (result['technical_score'],   0.30, True),
                'momentum':    (result['momentum_score'],    0.10, True),
                'fundamental': (result['fundamental_score'], 0.25, fund_available),
                'volume':      (result['volume_score'],      0.15, True),
                'macro':       (result['macro_score'],       0.10, macro_available),
                'sentiment':   (result['sentiment_score'],   0.10, sentiment_available),
            }
            avail = {k: (v, w) for k, (v, w, ok) in factors.items() if ok}
            wsum = sum(w for _, w in avail.values())
            result['composite_score'] = (
                sum(v * w for v, w in avail.values()) / wsum
                if wsum > 0 else result['technical_score']
            )
            degraded = [k for k, (v, w, ok) in factors.items() if not ok]
            result['degraded_factors'] = degraded
            result['data_quality'] = (
                'FULL' if not degraded
                else 'DEGRADED: scored without ' + ', '.join(degraded)
            )

            # Update signal based on composite score
            if result['composite_score'] >= 75:
                result['composite_signal'] = 'STRONG BUY'
            elif result['composite_score'] >= 60:
                result['composite_signal'] = 'BUY'
            elif result['composite_score'] >= 50:
                result['composite_signal'] = 'HOLD'
            elif result['composite_score'] >= 35:
                result['composite_signal'] = 'SELL'
            else:
                result['composite_signal'] = 'STRONG SELL'

        # --- BUY-SIDE GUARDRAILS — same vetoes as the live trader ----------
        # This dashboard used to be able to say BUY on a setup the validated
        # live system (kala_daily_trader / the bot) would refuse:
        # overbought, parabolic, OBV distribution, thin-volume surge. That is
        # how "the two files disagree, which do I follow?" happens. Running
        # the SAME evaluate_entry here ends it: a vetoed BUY is downgraded to
        # HOLD in this dashboard too. (market_status=None because this script
        # doesn't compute the IHSG regime — the price/volume vetoes still
        # apply; the bear-market block lives in the daily runner.)
        result['entry_vetoes'] = []
        try:
            needs_veto_check = ('BUY' in str(result.get('signal', ''))
                                or 'BUY' in str(result.get('composite_signal', '')))
            if needs_veto_check:
                from kala.entries import evaluate_entry
                _entry = evaluate_entry(data, market_status=None)
                result['entry_vetoes'] = _entry.vetoes
                if not _entry.allowed:
                    if 'BUY' in str(result.get('signal', '')):
                        result['signal'] = 'HOLD'
                        result['reason'] = ('vetoed: ' + '; '.join(_entry.vetoes))[:160]
                    if 'BUY' in str(result.get('composite_signal', '')):
                        result['composite_signal'] = 'HOLD'
        except Exception:
            pass

        return result

    except Exception:
        return None


def live_trading_dashboard(advanced: bool = True):
    """
    Display live trading signals for all watchlist stocks with advanced analytics
    
    Args:
        advanced: Include fundamental, volume, macro, and sentiment analysis
    """
    print("\n" + "="*100)
    print("🔴 KALA - ADVANCED RESEARCH DASHBOARD")
    print("="*100)
    print("⚠️  RESEARCH VIEW, NOT THE TRADING SIGNAL. Its multi-factor blend")
    print("    (fundamental/macro/sentiment) has never been backtested. The")
    print("    validated signal is kala_daily_trader / the bot's /scan;")
    print("    when the two disagree, follow /scan. BUYs shown here have at")
    print("    least passed the same entry vetoes as the live system.")
    print("="*100)
    print(f"Generated: {now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print("Market: Indonesia Stock Exchange (IDX)")
    if advanced:
        print("Analysis: Technical + Fundamental + Volume + Macro + Sentiment")
    else:
        print("Analysis: Technical Only (SMA Crossover + RSI)")
    print("="*100)

    signals = []
    start_time = time.time()

    # ── PHASE 1: Batch download ALL OHLCV data (cheap: ~14 batch calls for 672 stocks)
    print("\n📥 STEP 1: Batch downloading all price data...")
    all_price_data = batch_download_prices(WATCHLIST)

    # ── PHASE 2: Pre-filter (eliminate dead/illiquid stocks BEFORE expensive API calls)
    print("\n🔍 STEP 2: Pre-filtering stocks (eliminating dead/illiquid)...")
    qualified_stocks = prefilter_stocks(all_price_data)
    qualified_tickers = list(qualified_stocks.keys())

    # ── PHASE 3: Cache macro indicators (fetch ONCE, reuse for all stocks)
    cached_macro = None
    if advanced:
        print("\nSTEP 3: Fetching macro & sentiment data...")
        cached_macro = get_cached_macro_indicators()

    # ── PHASE 4: Deep-analyze ONLY qualified stocks in parallel
    # Each stock still needs individual .info + .news calls, but now only for
    # qualified stocks (~200-300 instead of 672), with staggered delays
    print(f"\n📊 STEP 4: Deep-analyzing {len(qualified_tickers)} qualified stocks ({MAX_WORKERS} threads)...")
    print(f"  (Skipped {len(WATCHLIST) - len(qualified_tickers)} dead/illiquid stocks)\n")

    def _analyze_stock(ticker):
        """Worker function for parallel stock analysis"""
        stock_data = qualified_stocks.get(ticker)
        if stock_data is None:
            return None
        # Stagger API calls: random delay to avoid burst of .info/.news requests
        time.sleep(random.uniform(1.0, 3.0))
        return get_live_signal(
            ticker, DEFAULT_FAST_SMA, DEFAULT_SLOW_SMA,
            advanced=advanced, preloaded_data=stock_data,
            cached_macro=cached_macro
        )

    completed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ticker = {executor.submit(_analyze_stock, t): t for t in qualified_tickers}

        for future in as_completed(future_to_ticker):
            completed += 1
            ticker = future_to_ticker[future]
            try:
                signal_data = future.result()
                if signal_data:
                    signals.append(signal_data)
                    if advanced:
                        print(f"  [{completed}/{len(qualified_tickers)}] {ticker} ✓ (Score: {signal_data['composite_score']:.0f}/100)")
                    else:
                        print(f"  [{completed}/{len(qualified_tickers)}] {ticker} ✓")
                else:
                    failed += 1
                    print(f"  [{completed}/{len(qualified_tickers)}] {ticker} ✗ No data")
            except Exception:
                failed += 1
                print(f"  [{completed}/{len(qualified_tickers)}] {ticker} ✗ Error")

    print(f"\n  Analyzed: {len(signals)} successful, {failed} failed")

    elapsed = time.time() - start_time
    print(f"\nTotal analysis time: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")

    if not signals:
        print("\nCould not fetch any signals. Check your internet connection.")
        return

    # Print main signals table
    print("\n" + "="*100)
    if advanced:
        print("COMPOSITE TRADING SIGNALS (Multi-Factor Analysis)")
    else:
        print("TECHNICAL TRADING SIGNALS")
    print("="*100)

    # Define signal colors/emojis
    signal_emoji = {
        'STRONG BUY': '🟢🟢',
        'BUY': '🟢',
        'HOLD': '🟡',
        'SELL': '🔴',
        'STRONG SELL': '🔴🔴',
        'CAUTION': '🟠',
        'AVOID': '⚫',
        'WAIT': '⚪'
    }

    # Print header
    if advanced:
        print(f"{'Ticker':<10} {'Signal':<15} {'Score':<8} {'Price':<13} {'Change':<9} {'Tech':<6} {'Fund':<6} {'Vol':<6}")
        print("-"*100)

        # Sort by composite score (highest first)
        signals.sort(key=lambda x: x.get('composite_score', 0), reverse=True)

        # Print each signal
        for s in signals:
            composite_sig = s.get('composite_signal', s['signal'])
            emoji = signal_emoji.get(composite_sig, '⚪')
            ticker = s['ticker']
            signal = f"{emoji} {composite_sig}"
            score = f"{s.get('composite_score', 0):.0f}/100"
            price = f"IDR {s['price']:,.0f}"
            change = f"{s['daily_change']:+.2f}%"
            tech = f"{s.get('technical_score', 0):.0f}"
            fund = f"{s.get('fundamental_score', 0):.0f}"
            vol = f"{s.get('volume_score', 0):.0f}"

            print(f"{ticker:<10} {signal:<15} {score:<8} {price:<13} {change:<9} {tech:<6} {fund:<6} {vol:<6}")
    else:
        print(f"{'Ticker':<12} {'Signal':<12} {'Price':<13} {'Change':<10} {'RSI':<8} {'Trend':<15}")
        print("-"*100)

        # Sort by signal priority (BUY first)
        priority = {'BUY': 0, 'CAUTION': 1, 'HOLD': 2, 'AVOID': 3, 'SELL': 4, 'WAIT': 5}
        signals.sort(key=lambda x: priority.get(x['signal'], 99))

        # Print each signal
        for s in signals:
            emoji = signal_emoji.get(s['signal'], '⚪')
            ticker = s['ticker']
            signal = f"{emoji} {s['signal']}"
            price = f"IDR {s['price']:,.0f}"
            change = f"{s['daily_change']:+.2f}%"
            rsi = f"{s['rsi']:.1f}"
            mom = f"{s.get('momentum_persistence', 0):.0f}"
            rs = f"{s.get('avg_relative_strength', 0):+.1f}%"

            # Determine trend status
            if s['sma_fast'] > s['sma_slow']:
                trend = "UP"
            else:
                trend = "DOWN"

            print(f"{ticker:<12} {signal:<12} {price:<13} {change:<10} {rsi:<8} {trend:<6} Mom:{mom:<4} RS:{rs}")

    # Print detailed analysis for each stock
    print("\n" + "="*100)
    print("DETAILED MULTI-FACTOR ANALYSIS")
    print("="*100)

    for s in signals:
        composite_sig = s.get('composite_signal', s['signal'])
        emoji = signal_emoji.get(composite_sig, '⚪')

        print(f"\n{emoji} {s['ticker']} - {composite_sig if advanced else s['signal']}")
        print("-"*100)

        # Price info
        print(f"💰 PRICE: IDR {s['price']:,.0f} ({s['daily_change']:+.2f}% today) | Data: {s['date'].strftime('%Y-%m-%d')}")

        if advanced:
            print(f"📊 COMPOSITE SCORE: {s.get('composite_score', 0):.0f}/100")

        # Technical analysis
        print(f"\n📈 TECHNICAL ({s.get('technical_score', 0):.0f}/100):")
        print(f"   • Fast SMA: {s['sma_fast']:.2f} | Slow SMA: {s['sma_slow']:.2f}")
        print(f"   • RSI: {s['rsi']:.1f}")
        print(f"   • {s['reason']}")

        # Time series / momentum analysis
        print(f"\n📉 TIME SERIES / MOMENTUM ({s.get('momentum_persistence', 0):.0f}/100):")
        print(f"   • 5-day Return: {s.get('roc_5', 0):+.2f}% | 20-day: {s.get('roc_20', 0):+.2f}%")
        print(f"   • Trend Slope: {s.get('slope_pct', 0):+.3f}%/day | Accelerating: {'YES' if s.get('is_accelerating') else 'NO'}")
        print(f"   • vs IHSG: {s.get('avg_relative_strength', 0):+.1f}% ({'OUTPERFORMING' if s.get('is_outperforming') else 'UNDERPERFORMING'})")
        print(f"   • Smart Money (OBV): {s.get('obv_trend', 'N/A')}")

        if advanced:
            # Fundamental analysis
            print(f"\n💼 FUNDAMENTAL ({s.get('fundamental_score', 50):.0f}/100):")
            print(f"   • {s.get('fundamental_analysis', 'N/A')}")
            if s.get('fundamentals'):
                f = s['fundamentals']
                metrics = []
                if f.get('pe_ratio'):
                    metrics.append(f"P/E: {f['pe_ratio']:.2f}")
                if f.get('pb_ratio'):
                    metrics.append(f"P/B: {f['pb_ratio']:.2f}")
                if f.get('roe'):
                    metrics.append(f"ROE: {f['roe']*100:.1f}%")
                if metrics:
                    print(f"   • {' | '.join(metrics)}")

            # Volume analysis
            print(f"\n📊 VOLUME ({s.get('volume_score', 50):.0f}/100):")
            print(f"   • {s.get('volume_analysis', 'N/A')}")

            # Macro analysis
            print(f"\n🌍 MACRO ({s.get('macro_score', 50):.0f}/100):")
            print(f"   • {s.get('macro_analysis', 'N/A')}")
            if s.get('macro_data'):
                m = s['macro_data']
                macro_info = []
                if m.get('usd_idr'):
                    macro_info.append(f"USD/IDR: {m['usd_idr']:,.0f} ({m['usd_idr_change']:+.2f}%)")
                if m.get('oil_price'):
                    macro_info.append(f"Oil: ${m['oil_price']:.2f} ({m['oil_change']:+.2f}%)")
                if macro_info:
                    print(f"   • {' | '.join(macro_info)}")

            # Sentiment analysis
            print(f"\n📰 NEWS SENTIMENT ({s.get('sentiment_score', 50):.0f}/100):")
            print(f"   • {s.get('sentiment_analysis', 'N/A')}")
            if s.get('news_count', 0) > 0:
                print(f"   • Articles analyzed: {s.get('news_count', 0)}")

    # Summary and recommendations
    print("\n" + "="*100)
    print("PORTFOLIO RECOMMENDATIONS")
    print("="*100)

    if advanced:
        strong_buy = [s for s in signals if s.get('composite_signal') == 'STRONG BUY']
        buy = [s for s in signals if s.get('composite_signal') == 'BUY']
        hold = [s for s in signals if s.get('composite_signal') == 'HOLD']
        sell = [s for s in signals if s.get('composite_signal') == 'SELL']
        strong_sell = [s for s in signals if s.get('composite_signal') == 'STRONG SELL']

        if strong_buy:
            print(f"🟢🟢 STRONG BUY:   {len(strong_buy)} stocks - {[s['ticker'] for s in strong_buy]}")
        if buy:
            print(f"🟢   BUY:          {len(buy)} stocks - {[s['ticker'] for s in buy]}")
        if hold:
            print(f"🟡   HOLD:         {len(hold)} stocks - {[s['ticker'] for s in hold]}")
        if sell:
            print(f"🔴   SELL:         {len(sell)} stocks - {[s['ticker'] for s in sell]}")
        if strong_sell:
            print(f"🔴🔴 STRONG SELL:  {len(strong_sell)} stocks - {[s['ticker'] for s in strong_sell]}")

        print(f"\n💡 TOP PICK: {signals[0]['ticker']} (Score: {signals[0].get('composite_score', 0):.0f}/100)")
        print(f"⚠️  AVOID: {signals[-1]['ticker']} (Score: {signals[-1].get('composite_score', 0):.0f}/100)")
    else:
        buy_count = sum(1 for s in signals if s['signal'] == 'BUY')
        sell_count = sum(1 for s in signals if s['signal'] == 'SELL')
        print(f"🟢 BUY signals:    {buy_count}")
        print(f"🔴 SELL signals:   {sell_count}")

    print(f"\n📊 Total analyzed: {len(signals)} stocks")
    print("\n⚠️  DISCLAIMER: This is for educational purposes only. Not financial advice.")
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
    try:
        from kala.universe import UNIVERSE_IS_POINT_IN_TIME
        if not UNIVERSE_IS_POINT_IN_TIME:
            print("WARNING: universe is CURRENT DES membership -> backtests are\n         survivorship-biased (optimistic). Use point-in-time lists to fix.")
    except Exception:
        pass
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
    """Main entry point"""

    # Start logging to file
    dual_output, log_file, timestamp = start_logging()

    try:
        # ====================================================================
        # CHOOSE YOUR MODE - UNCOMMENT THE ONE YOU WANT
        # ====================================================================

        print("\n📊 KALA - SHARIA TRADING SYSTEM")
        print(f"{'='*100}")
        print(f"Analysis Date: {now().strftime('%A, %B %d, %Y at %H:%M:%S')} WIB")
        print(f"Total DES Stocks Available: {len(ALL_SHARIA_STOCKS)}")
        print(f"Currently analyzing: {len(WATCHLIST)} stocks")
        print(f"⏱️  Estimated time: ~{max(60, len(WATCHLIST) // MAX_WORKERS * 10 + 120)} seconds (batch download + {MAX_WORKERS}-thread parallel analysis)")
        print(f"{'='*100}\n")

        # MODE 1: 🔴 LIVE TRADING SIGNALS (Real-time with ADVANCED multi-factor analysis)
        # Analyzes ALL stocks in watchlist
        # Run time: ~3-5 minutes for Top 30 JII
        signals = live_trading_dashboard(advanced=True)

        # Save to CSV
        csv_file = None
        if signals:
            csv_file = save_to_csv(signals, timestamp)

        # ================================================================
        # PORTFOLIO OPTIMIZATION (HRP for composite strategy)
        # After identifying buy candidates, calculate exact lot sizes.
        # Uses composite_score for multi-factor ranking.
        # ================================================================
        if signals:
            try:
                from portfolio_optimizer import optimize_from_signals

                portfolio = optimize_from_signals(
                    signals,
                    total_capital=INITIAL_CAPITAL,
                    strategy='hrp',            # HRP balances risk across factors
                    top_n=10,                  # Top 10 stocks
                    min_score=60,              # Composite score >= 60
                    score_key='composite_score',
                )
            except ImportError:
                print("\n  [Portfolio Optimizer not available - pip install pypfopt]")
            except Exception as e:
                print(f"\n  [Portfolio optimization error: {e}]")

        # MODE 2: 🔴 QUICK TEST (Top 10 stocks only - for testing)
        # Temporarily override WATCHLIST for faster testing
        # global WATCHLIST
        # WATCHLIST = WATCHLIST[:10]  # Only first 10 stocks
        # signals = live_trading_dashboard(advanced=True)
        # if signals:
        #     csv_file = save_to_csv(signals, timestamp)

        # MODE 3: 🔴 LIVE TRADING SIGNALS (Technical analysis only - faster)
        # Run time: ~1-2 minutes for all stocks
        # signals = live_trading_dashboard(advanced=False)
        # if signals:
        #     csv_file = save_to_csv(signals, timestamp)

    # MODE 4: 📊 BACKTEST - Quick (no optimization)
    # Tests strategy on historical data with default parameters
    # Run time: ~2 minutes for all stocks
    # analyze_watchlist(optimize=False)

    # MODE 5: 🔬 BACKTEST - Full Optimization
    # Finds best parameters for each stock (slower but more accurate)
    # Run time: 2-3 minutes per stock × 36 stocks = ~2 hours
    # analyze_watchlist(optimize=True)

        # MODE 6: 🎯 Single Stock - Backtest (uncomment to use)
        # analyze_single_stock('BBRI.JK', optimize=False)

        # Success message
        print(f"\n{'='*100}")
        print("✅ ANALYSIS COMPLETE!")
        print(f"{'='*100}")
        print("\n📁 SAVED FILES:")
        print(f"   📄 Full Report (TXT): {os.path.basename(log_file)}")
        if signals and csv_file:
            print(f"   📊 Summary (CSV):     {os.path.basename(csv_file)}")
        print(f"\n💾 Location: {os.path.abspath('results')}")
        print("\n💡 TIP: Open the CSV file in Excel for easy sorting and filtering!")
        print(f"{'='*100}\n")

    except Exception as e:
        print(f"\n❌ ERROR OCCURRED: {str(e)}")
        print(f"📄 Partial results saved to: {log_file}")
        raise

    finally:
        # Close the log file
        dual_output.close()


if __name__ == '__main__':
    main()
