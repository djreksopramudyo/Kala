"""
Kala - VALUE INVESTING SCREENER (Fundamental-Only Engine)
================================================================

Filosofi: "Harga saham hanyalah kebisingan sementara, 
           kinerja perusahaan adalah kebenaran jangka panjang."
           - Benjamin Graham

Tujuan: Menemukan saham yang SALAH HARGA (Undervalued)
Strategi: Value Investing - Beli murah, jual mahal
Timeline: Jangka Panjang (Hold 1-5 tahun)
Update: Quarterly (setiap rilis laporan keuangan)

Features:
    1. 📊 PURE FUNDAMENTAL ANALYSIS - No charts, no noise
    2. 💎 INTRINSIC VALUE CALCULATION - Graham Formula & DCF
    3. 🎯 MARGIN OF SAFETY - Risk-adjusted value scoring
    4. 🔍 VALUE TRAP DETECTION - Growth & quality filters
    5. 📈 RANKING SYSTEM - Find the best opportunities
    6. 💾 AUTO-SAVE RESULTS - Track your picks quarterly

Metrics Analyzed:
    - P/E Ratio (Price to Earnings)
    - P/B Ratio (Price to Book)
    - PEG Ratio (P/E to Growth)
    - ROE (Return on Equity)
    - ROA (Return on Assets)
    - Profit Margin
    - Debt/Equity Ratio
    - Current Ratio (Liquidity)
    - Dividend Yield
    - Earnings Growth
    - Book Value per Share
    - Free Cash Flow
    - Intrinsic Value
    - Margin of Safety

Decision Criteria:
    ✅ STRONG BUY  - Significantly undervalued (MoS > 30%)
    🟢 BUY         - Undervalued (MoS > 15%)
    🟡 HOLD        - Fair value (MoS -15% to 15%)
    🔴 AVOID       - Overvalued (MoS < -15%)
    ⚠️  VALUE TRAP - Cheap but declining business

Installation:
    pip install yfinance pandas numpy

Usage:
    python kala_fundamental_only.py

Author: Senior Python Quantitative Developer
Target: Long-term Indonesian value investors
"""

import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

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
# MOMENTUM TIMING FILTER - Don't catch falling knives!
# Even value stocks need good timing. This checks if the stock's
# momentum is turning positive before recommending a BUY.
# ============================================================================

def calculate_momentum_timing(ticker: str, preloaded_data=None):
    """
    Check if a fundamentally good stock has good TIMING to buy.
    
    Even Benjamin Graham wouldn't buy a stock that's in free-fall.
    This function checks if price momentum is turning positive.
    
    Args:
        ticker: Stock ticker symbol
        preloaded_data: Optional pre-downloaded DataFrame (avoids individual API call)
    
    Returns:
        dict with timing info, or None if insufficient data
    """
    try:
        if preloaded_data is not None:
            data = preloaded_data.copy()
        else:
            end_date = now().replace(tzinfo=None)
            start_date = end_date - timedelta(days=100)
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)

        if data.empty or len(data) < 20:
            return None

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        close = data['Close']
        current = close.iloc[-1]

        # Rate of Change
        roc_5 = ((current - close.iloc[-5]) / close.iloc[-5]) * 100 if len(close) >= 5 else 0
        roc_20 = ((current - close.iloc[-20]) / close.iloc[-20]) * 100 if len(close) >= 20 else 0

        # SMA positioning (via kala.indicators)
        from kala import indicators as _ind
        sma_20 = float(_ind.sma(close, 20).iloc[-1])
        sma_50 = float(_ind.sma(close, 50).iloc[-1]) if len(close) >= 50 else float(close.mean())

        # RSI (Wilder, not a simple rolling mean)
        rsi = float(_ind.rsi(close, 14).iloc[-1])

        # Linear regression slope
        recent_20 = close.tail(20).values
        slope = np.polyfit(np.arange(len(recent_20)), recent_20, 1)[0] if len(recent_20) >= 20 else 0
        slope_pct = (slope / recent_20[0]) * 100 if recent_20[0] != 0 else 0

        # OBV trend (vectorised, via kala.indicators)
        volume = data['Volume']
        obv = _ind.obv(close, volume)
        obv_trend = 'ACCUMULATION' if obv.iloc[-1] > obv.iloc[-10] else 'DISTRIBUTION'

        # Timing score (0-100)
        timing = 0

        # Price above SMA20 (+20) or below (-10)
        if current > sma_20:
            timing += 20
        elif current < sma_20 * 0.95:
            timing -= 10

        # Price above SMA50 (+15)
        if current > sma_50:
            timing += 15

        # Positive 5d momentum (+15)
        if roc_5 > 3:
            timing += 15
        elif roc_5 > 0:
            timing += 8

        # Positive 20d momentum (+15)
        if roc_20 > 5:
            timing += 15
        elif roc_20 > 0:
            timing += 8

        # Positive slope (+15)
        if slope_pct > 0.3:
            timing += 15
        elif slope_pct > 0:
            timing += 8

        # OBV accumulation (+10)
        if obv_trend == 'ACCUMULATION':
            timing += 10

        # RSI sweet spot (+10)
        if 40 < rsi < 65:
            timing += 10
        elif 30 < rsi < 70:
            timing += 5

        timing = max(0, min(100, timing))

        # Timing label
        if timing >= 70:
            label = 'GOOD TIMING'
        elif timing >= 45:
            label = 'NEUTRAL TIMING'
        elif timing >= 25:
            label = 'POOR TIMING'
        else:
            label = 'BAD TIMING (falling knife!)'

        return {
            'timing_score': timing,
            'timing_label': label,
            'roc_5': roc_5,
            'roc_20': roc_20,
            'rsi': rsi,
            'slope_pct': slope_pct,
            'obv_trend': obv_trend,
            'above_sma20': current > sma_20,
            'above_sma50': current > sma_50,
            'current_price': current,
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
        # Handle Unicode for Windows console
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            # Fallback: remove emojis for console, keep them in file
            safe_message = message.encode('ascii', 'ignore').decode('ascii')
            self.terminal.write(safe_message)

        # Always write full Unicode to file
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()
        sys.stdout = self.terminal


def start_logging():
    """Start logging output to file"""
    if not os.path.exists('results'):
        os.makedirs('results')

    # Create timestamped filename (Indonesian time)
    timestamp = now().strftime('%Y%m%d_%H%M%S')
    filename = f'results/fundamental_screening_{timestamp}.txt'

    dual_output = DualOutput(filename)
    sys.stdout = dual_output

    print(f"Results will be saved to: {filename}")
    print("="*100 + "\n")

    return dual_output, filename, timestamp


def save_to_watchlist(screening_results, path='watchlist.json'):
    """Persist BUY-grade names (with their intrinsic value as the thesis anchor)
    so check_watchlist.py can alert you when they later dip to a discount.
    This is the memory layer: research once, act when price cooperates."""
    try:
        from kala.watchlist import WatchlistItem, WatchlistStore
        wl = WatchlistStore.load(path)
        added = 0
        for r in screening_results:
            iv = r.get('intrinsic_value')
            decision = str(r.get('decision', ''))
            if not iv or iv <= 0 or 'BUY' not in decision.upper():
                continue
            mos = r.get('margin_of_safety')
            wl.add(WatchlistItem(
                ticker=r['ticker'],
                fair_value=float(iv),
                score=float(r['value_score']) if r.get('value_score') is not None else None,
                thesis=(f"{decision} | MoS {mos:.0f}%" if isinstance(mos, (int, float))
                        else decision),
                source='fundamental_screen',
            ))
            added += 1
        wl.save()
        print(f"Watchlist updated: {added} BUY-grade names saved to {path}")
        return added
    except Exception as e:
        print(f"(watchlist save skipped: {e})")
        return 0


def save_to_csv(screening_results, timestamp):
    """Save screening results to CSV"""
    if not screening_results:
        return None

    csv_file = f'results/fundamental_screening_{timestamp}.csv'

    data = []
    for r in screening_results:
        # Helper function to safely format numeric values
        def safe_format(value, format_str):
            if value is None:
                return 'N/A'
            if not isinstance(value, (int, float)):
                return 'N/A'
            try:
                return format_str.format(value)
            except:
                return 'N/A'

        # Helper function to remove emojis from text
        def remove_emojis(text):
            if not text:
                return text
            # Remove common emojis used in decisions
            emoji_map = {
                '✅': '',
                '🟢': '',
                '🟡': '',
                '🔴': '',
                '⚠️': '',
                '💎': '',
            }
            for emoji, replacement in emoji_map.items():
                text = text.replace(emoji, replacement)
            return text.strip()

        # Convert percentage fields (multiply by 100)
        roe_pct = r.get('roe') * 100 if r.get('roe') and isinstance(r.get('roe'), (int, float)) else None
        pm_pct = r.get('profit_margin') * 100 if r.get('profit_margin') and isinstance(r.get('profit_margin'), (int, float)) else None
        dy_pct = r.get('dividend_yield') * 100 if r.get('dividend_yield') and isinstance(r.get('dividend_yield'), (int, float)) else None

        row = {
            'Ticker': r['ticker'],
            'Company': r.get('company_name', 'N/A'),
            'Decision': remove_emojis(r['decision']),
            'Value_Score': safe_format(r.get('value_score'), "{:.0f}"),
            'Margin_of_Safety_%': safe_format(r.get('margin_of_safety'), "{:.1f}"),
            'Timing_Score': safe_format(r.get('timing_score'), "{:.0f}"),
            'Timing_Label': r.get('timing_label', 'N/A'),
            'Current_Price_IDR': safe_format(r.get('current_price'), "{:.0f}"),
            'Intrinsic_Value_IDR': safe_format(r.get('intrinsic_value'), "{:.0f}"),
            'P/E': safe_format(r.get('pe_ratio'), "{:.2f}"),
            'P/B': safe_format(r.get('pb_ratio'), "{:.2f}"),
            'ROE_%': safe_format(roe_pct, "{:.1f}"),
            'Debt/Equity_%': safe_format(r.get('debt_equity'), "{:.1f}"),
            'Profit_Margin_%': safe_format(pm_pct, "{:.1f}"),
            'Dividend_Yield_%': safe_format(dy_pct, "{:.2f}"),
            'Market_Cap_IDR': safe_format(r.get('market_cap'), "{:,.0f}"),
        }
        data.append(row)

    df = pd.DataFrame(data)
    df.to_csv(csv_file, index=False)

    return csv_file


# ============================================================================
# CONFIGURATION
# ============================================================================

INITIAL_CAPITAL = 5_000_000  # 5 Juta IDR (for portfolio optimization)

# WATCHLIST - Choose your universe
# --- universe extracted to the package (was 672 duplicated tickers) ---
from kala.universe import ALL_SHARIA_STOCKS

TOP_30_JII = [
    'ASII.JK', 'UNVR.JK', 'TLKM.JK', 'BBRI.JK', 'BMRI.JK', 'BBNI.JK', 'ICBP.JK', 'INDF.JK',
    'ADRO.JK', 'ANTM.JK', 'PTBA.JK', 'ITMG.JK', 'INCO.JK', 'UNTR.JK', 'KLBF.JK', 'MYOR.JK',
    'SMGR.JK', 'PGAS.JK', 'CPIN.JK', 'BSDE.JK', 'PWON.JK', 'MNCN.JK', 'EXCL.JK', 'ACES.JK',
    'WIKA.JK', 'PTPP.JK', 'WSKT.JK', 'TPIA.JK', 'ERAA.JK', 'SSMS.JK',
]

# SECTOR-SPECIFIC WATCHLISTS
BANKING = ['BBRI.JK', 'BMRI.JK', 'BBNI.JK', 'BBTN.JK', 'BRIS.JK', 'BTPS.JK', 'PNBS.JK', 'BANK.JK']
MINING = ['ADRO.JK', 'ANTM.JK', 'PTBA.JK', 'INCO.JK', 'ITMG.JK', 'GEMS.JK', 'MDKA.JK', 'TINS.JK', 'BYAN.JK']
CONSUMER = ['UNVR.JK', 'ICBP.JK', 'INDF.JK', 'KLBF.JK', 'MYOR.JK', 'ROTI.JK', 'SIDO.JK', 'CAMP.JK', 'GOOD.JK']
PROPERTY = ['BSDE.JK', 'PWON.JK', 'LPKR.JK', 'SMRA.JK', 'ASRI.JK', 'CTRA.JK', 'DILD.JK', 'APLN.JK']
TELCO = ['TLKM.JK', 'EXCL.JK', 'ISAT.JK', 'MTEL.JK', 'TOWR.JK', 'GHON.JK']
CONSTRUCTION = ['WIKA.JK', 'PTPP.JK', 'WSKT.JK', 'ADHI.JK', 'WTON.JK', 'WEGE.JK', 'JKON.JK']

# ============================================================================
# ACTIVE WATCHLIST - Choose which stocks to analyze
# ============================================================================

# ============================================================================
# ⚠️ IMPORTANT: Rate Limiting to Avoid API Blocks
# ============================================================================
# Yahoo Finance has rate limits (~2000 requests/hour)
# The script now waits 2 seconds between each stock to avoid getting blocked
# This means: 30 stocks = 1 minute, 100 stocks = 3.3 minutes, 672 stocks = 22 minutes

# OPTION 1: Top 30 Blue Chips (Recommended) - ~1 minute with rate limiting
# WATCHLIST = TOP_30_JII

# OPTION 2: Quick Test (5 stocks) - ~10 seconds
# WATCHLIST = TOP_30_JII[:5]

# OPTION 3: Full DES - ALL 672 stocks (now safe with Phase 1 batch download + pre-filter)
WATCHLIST = ALL_SHARIA_STOCKS

# OPTION 4: Sector-specific screening
# WATCHLIST = MINING + BANKING

# OPTION 5: Custom selection
# WATCHLIST = ['BBRI.JK', 'TLKM.JK', 'ANTM.JK', 'UNVR.JK', 'ICBP.JK']

# OPTION 6: Batch processing for full DES (recommended for large scans)
#           Run in batches to avoid prolonged API usage
# WATCHLIST = ALL_SHARIA_STOCKS[:100]  # First 100 stocks
# WATCHLIST = ALL_SHARIA_STOCKS[100:200]  # Next 100 stocks, etc.


# ============================================================================
# FUNDAMENTAL DATA FETCHER
# ============================================================================

def get_comprehensive_fundamentals(ticker: str, max_retries: int = 3):
    """
    Fetch ALL fundamental data for deep value analysis
    
    Args:
        ticker: Stock ticker symbol
        max_retries: Maximum number of retry attempts on rate limit errors
    
    Returns:
        Dictionary with comprehensive fundamental metrics
    """
    for attempt in range(max_retries):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            # Get historical data for price
            hist = stock.history(period='1d')
            current_price = hist['Close'].iloc[-1] if not hist.empty else info.get('currentPrice')

            fundamentals = {
            # Company Info
            'company_name': info.get('longName', ticker.replace('.JK', '')),
            'sector': info.get('sector', 'Unknown'),
            'industry': info.get('industry', 'Unknown'),

            # Price Data
            'current_price': current_price,
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),

            # Valuation Ratios
            'pe_ratio': info.get('trailingPE'),
            'forward_pe': info.get('forwardPE'),
            'pb_ratio': info.get('priceToBook'),
            'ps_ratio': info.get('priceToSalesTrailing12Months'),
            'peg_ratio': info.get('pegRatio'),

            # Profitability Metrics
            'roe': info.get('returnOnEquity'),
            'roa': info.get('returnOnAssets'),
            'profit_margin': info.get('profitMargins'),
            'operating_margin': info.get('operatingMargins'),
            'gross_margin': info.get('grossMargins'),

            # Financial Health
            'debt_equity': info.get('debtToEquity'),
            'current_ratio': info.get('currentRatio'),
            'quick_ratio': info.get('quickRatio'),
            'total_debt': info.get('totalDebt'),
            'total_cash': info.get('totalCash'),

            # Growth Metrics
            'earnings_growth': info.get('earningsGrowth'),
            'revenue_growth': info.get('revenueGrowth'),
            'earnings_quarterly_growth': info.get('earningsQuarterlyGrowth'),

            # Dividend Info
            'dividend_yield': info.get('dividendYield'),
            'dividend_rate': info.get('dividendRate'),
            'payout_ratio': info.get('payoutRatio'),

            # Book Value
            'book_value': info.get('bookValue'),
            'price_to_book': info.get('priceToBook'),

            # Market Data
            'market_cap': info.get('marketCap'),
            'enterprise_value': info.get('enterpriseValue'),
            'shares_outstanding': info.get('sharesOutstanding'),

            # Cash Flow
            'free_cash_flow': info.get('freeCashflow'),
            'operating_cashflow': info.get('operatingCashflow'),

            # Earnings
            'trailing_eps': info.get('trailingEps'),
            'forward_eps': info.get('forwardEps'),

                # Beta (volatility)
                'beta': info.get('beta'),
            }

            return fundamentals

        except Exception as e:
            error_msg = str(e)

            # Check if it's a rate limiting or auth error (Yahoo crumb/cookie issues)
            is_retryable = any(kw in error_msg for kw in [
                "Too Many Requests", "Rate limit", "429",
                "401", "Unauthorized", "Invalid Crumb",
                "unable to access", "NoneType"
            ])

            if is_retryable and attempt < max_retries - 1:
                # Exponential backoff: wait longer each retry
                wait_time = 8 * (2 ** attempt)  # 8s, 16s, 32s (longer waits)
                print(f"  ⚠️ Rate limit hit for {ticker}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            elif is_retryable:
                print(f"  ✗ Rate limit exceeded for {ticker} after {max_retries} attempts")
                return None
            else:
                # Other errors - don't retry
                print(f"  ⚠️ Error fetching {ticker}: {e}")
                return None

    return None  # If all retries failed


# ============================================================================
# INTRINSIC VALUE CALCULATORS
# ============================================================================

def calculate_graham_intrinsic_value(fundamentals: dict):
    """
    Benjamin Graham's Intrinsic Value Formula
    
    IV = √(22.5 × EPS × Book Value per Share)
    
    Where:
    - 22.5 = Graham's magic number (15 P/E × 1.5 P/B)
    - EPS = Earnings Per Share
    - BVPS = Book Value Per Share
    
    Args:
        fundamentals: Dictionary with fundamental data
    
    Returns:
        Intrinsic value or None
    """
    try:
        eps = fundamentals.get('trailing_eps')
        book_value = fundamentals.get('book_value')

        if eps and book_value and eps > 0 and book_value > 0:
            intrinsic_value = (22.5 * eps * book_value) ** 0.5
            return intrinsic_value
        return None
    except:
        return None


def calculate_dcf_simplified(fundamentals: dict):
    """
    Simplified Discounted Cash Flow (DCF) valuation
    
    Assumptions:
    - Growth rate = earnings growth (capped at 15%)
    - Discount rate = 12% (Indonesian risk-adjusted)
    - Terminal growth = 3%
    - Projection period = 5 years
    
    Args:
        fundamentals: Dictionary with fundamental data
    
    Returns:
        Intrinsic value per share or None
    """
    try:
        fcf = fundamentals.get('free_cash_flow')
        shares = fundamentals.get('shares_outstanding')
        growth = fundamentals.get('earnings_growth')

        if not fcf or not shares or fcf <= 0 or shares <= 0:
            return None

        # Cap growth rate at 15% (conservative)
        growth_rate = min(growth, 0.15) if growth and growth > 0 else 0.05
        discount_rate = 0.12
        terminal_growth = 0.03

        # Project 5 years of cash flows
        pv_sum = 0
        for year in range(1, 6):
            future_fcf = fcf * ((1 + growth_rate) ** year)
            discount_factor = (1 + discount_rate) ** year
            pv = future_fcf / discount_factor
            pv_sum += pv

        # Terminal value
        terminal_fcf = fcf * ((1 + growth_rate) ** 5) * (1 + terminal_growth)
        terminal_value = terminal_fcf / (discount_rate - terminal_growth)
        pv_terminal = terminal_value / ((1 + discount_rate) ** 5)

        # Enterprise value = PV of cash flows + terminal value
        enterprise_value = pv_sum + pv_terminal

        # Per share value
        intrinsic_value_per_share = enterprise_value / shares

        return intrinsic_value_per_share

    except:
        return None


def calculate_pe_based_value(fundamentals: dict):
    """
    P/E-based valuation using sector average
    
    Fair Value = EPS × Average P/E (typically 12-15 for IDX)
    
    Args:
        fundamentals: Dictionary with fundamental data
    
    Returns:
        Fair value or None
    """
    try:
        eps = fundamentals.get('trailing_eps')
        sector = fundamentals.get('sector', '')

        if not eps or eps <= 0:
            return None

        # Sector-specific fair P/E ratios for Indonesian market
        fair_pe_by_sector = {
            'Financial Services': 12,
            'Basic Materials': 10,
            'Energy': 8,
            'Consumer Cyclical': 15,
            'Consumer Defensive': 18,
            'Healthcare': 20,
            'Technology': 25,
            'Communication Services': 14,
            'Industrials': 13,
            'Real Estate': 10,
            'Utilities': 12,
        }

        fair_pe = fair_pe_by_sector.get(sector, 12)  # Default 12x
        fair_value = eps * fair_pe

        return fair_value

    except:
        return None


def calculate_composite_intrinsic_value(fundamentals: dict):
    """
    Composite intrinsic value using multiple methods
    
    Weights:
    - Graham Formula: 40%
    - DCF: 30%
    - P/E-based: 30%
    
    Args:
        fundamentals: Dictionary with fundamental data
    
    Returns:
        Weighted average intrinsic value
    """
    graham_value = calculate_graham_intrinsic_value(fundamentals)
    dcf_value = calculate_dcf_simplified(fundamentals)
    pe_value = calculate_pe_based_value(fundamentals)

    values = []
    weights = []

    if graham_value:
        values.append(graham_value)
        weights.append(0.4)

    if dcf_value:
        values.append(dcf_value)
        weights.append(0.3)

    if pe_value:
        values.append(pe_value)
        weights.append(0.3)

    if not values:
        return None

    # Normalize weights
    total_weight = sum(weights)
    normalized_weights = [w / total_weight for w in weights]

    # Weighted average
    intrinsic_value = sum(v * w for v, w in zip(values, normalized_weights))

    return intrinsic_value


# ============================================================================
# VALUE SCORING SYSTEM
# ============================================================================

def calculate_value_score(fundamentals: dict, intrinsic_value: float):
    """
    Calculate comprehensive value score (0-100)
    
    Components:
    1. Margin of Safety (30 points)
    2. Profitability Quality (25 points)
    3. Financial Health (20 points)
    4. Growth Potential (15 points)
    5. Dividend Yield (10 points)
    
    Args:
        fundamentals: Dictionary with fundamental data
        intrinsic_value: Calculated intrinsic value
    
    Returns:
        Score (0-100) and detailed breakdown
    """
    score = 0
    breakdown = []

    current_price = fundamentals.get('current_price')

    # 1. MARGIN OF SAFETY (30 points) - Most important!
    if current_price and intrinsic_value:
        margin_of_safety = ((intrinsic_value - current_price) / current_price) * 100

        if margin_of_safety > 40:
            score += 30
            breakdown.append("✓✓ Huge margin of safety (>40%)")
        elif margin_of_safety > 30:
            score += 25
            breakdown.append("✓ Strong margin (30-40%)")
        elif margin_of_safety > 15:
            score += 20
            breakdown.append("✓ Good margin (15-30%)")
        elif margin_of_safety > 0:
            score += 10
            breakdown.append("~ Slight margin (0-15%)")
        elif margin_of_safety > -15:
            score += 5
            breakdown.append("~ Near fair value")
        else:
            breakdown.append("✗ Overvalued (MoS < -15%)")
    else:
        breakdown.append("? Cannot calc margin")

    # 2. PROFITABILITY QUALITY (25 points)
    roe = fundamentals.get('roe')
    profit_margin = fundamentals.get('profit_margin')

    prof_score = 0
    if roe and roe > 0:
        if roe > 0.20:  # >20% ROE
            prof_score += 15
            breakdown.append(f"✓ Excellent ROE ({roe*100:.1f}%)")
        elif roe > 0.15:  # 15-20%
            prof_score += 12
            breakdown.append(f"✓ Strong ROE ({roe*100:.1f}%)")
        elif roe > 0.10:  # 10-15%
            prof_score += 8
            breakdown.append(f"~ Good ROE ({roe*100:.1f}%)")
        else:
            breakdown.append(f"✗ Weak ROE ({roe*100:.1f}%)")

    if profit_margin and profit_margin > 0:
        if profit_margin > 0.15:  # >15%
            prof_score += 10
            breakdown.append(f"✓ High margin ({profit_margin*100:.1f}%)")
        elif profit_margin > 0.05:  # 5-15%
            prof_score += 5
            breakdown.append(f"~ Good margin ({profit_margin*100:.1f}%)")
        else:
            breakdown.append(f"✗ Low margin ({profit_margin*100:.1f}%)")

    score += prof_score

    # 3. FINANCIAL HEALTH (20 points)
    debt_equity = fundamentals.get('debt_equity')
    current_ratio = fundamentals.get('current_ratio')

    health_score = 0
    if debt_equity is not None:
        if debt_equity < 50:
            health_score += 10
            breakdown.append(f"✓ Low debt ({debt_equity:.1f}%)")
        elif debt_equity < 100:
            health_score += 5
            breakdown.append(f"~ Moderate debt ({debt_equity:.1f}%)")
        else:
            breakdown.append(f"✗ High debt ({debt_equity:.1f}%)")

    if current_ratio:
        if current_ratio > 1.5:
            health_score += 10
            breakdown.append(f"✓ Strong liquidity ({current_ratio:.2f})")
        elif current_ratio > 1.0:
            health_score += 5
            breakdown.append(f"~ Adequate liquidity ({current_ratio:.2f})")
        else:
            breakdown.append(f"✗ Liquidity concern ({current_ratio:.2f})")

    score += health_score

    # 4. GROWTH POTENTIAL (15 points) - Avoid value traps!
    earnings_growth = fundamentals.get('earnings_growth')
    revenue_growth = fundamentals.get('revenue_growth')

    growth_score = 0
    if earnings_growth and earnings_growth > 0:
        if earnings_growth > 0.15:  # >15%
            growth_score += 10
            breakdown.append(f"✓ Strong growth ({earnings_growth*100:.1f}%)")
        elif earnings_growth > 0.05:  # 5-15%
            growth_score += 5
            breakdown.append(f"~ Moderate growth ({earnings_growth*100:.1f}%)")
        else:
            breakdown.append(f"? Slow growth ({earnings_growth*100:.1f}%)")
    elif earnings_growth and earnings_growth < -0.10:  # Declining >10%
        breakdown.append(f"⚠️ VALUE TRAP? Earnings declining ({earnings_growth*100:.1f}%)")

    if revenue_growth and revenue_growth > 0.05:
        growth_score += 5
        breakdown.append(f"✓ Revenue growing ({revenue_growth*100:.1f}%)")

    score += growth_score

    # 5. DIVIDEND YIELD (10 points) - Nice bonus!
    div_yield = fundamentals.get('dividend_yield')

    if div_yield and div_yield > 0:
        if div_yield > 0.05:  # >5%
            score += 10
            breakdown.append(f"✓ High dividend ({div_yield*100:.2f}%)")
        elif div_yield > 0.03:  # 3-5%
            score += 5
            breakdown.append(f"~ Good dividend ({div_yield*100:.2f}%)")
        else:
            breakdown.append(f"Low dividend ({div_yield*100:.2f}%)")

    return score, breakdown


def determine_investment_decision(value_score: float, margin_of_safety: float, fundamentals: dict):
    """
    Make final investment recommendation
    
    Args:
        value_score: Calculated value score (0-100)
        margin_of_safety: Margin of safety percentage
        fundamentals: Dictionary with fundamental data
    
    Returns:
        Decision string and confidence level
    """
    earnings_growth = fundamentals.get('earnings_growth')

    # Check for value trap (declining earnings)
    is_value_trap = earnings_growth and earnings_growth < -0.10

    if is_value_trap:
        return "⚠️ VALUE TRAP", "CAUTION - Cheap but declining business"

    # Decision based on score and margin of safety
    if value_score >= 75 and margin_of_safety > 30:
        return "✅ STRONG BUY", "High confidence - Excellent opportunity"
    elif value_score >= 60 and margin_of_safety > 15:
        return "🟢 BUY", "Good confidence - Undervalued"
    elif value_score >= 50 or (margin_of_safety > -15 and margin_of_safety < 15):
        return "🟡 HOLD", "Neutral - Fair value"
    else:
        return "🔴 AVOID", "Low confidence - Overvalued or poor quality"


# ============================================================================
# VALUE SCREENING ENGINE
# ============================================================================

def screen_stock(ticker: str, preloaded_price_data=None):
    """
    Perform comprehensive fundamental screening on a single stock
    
    Args:
        ticker: Stock ticker symbol
        preloaded_price_data: Optional pre-downloaded OHLCV DataFrame (avoids re-downloading)
    
    Returns:
        Dictionary with screening results
    """
    print(f"  → {ticker}...", end=" ", flush=True)

    # Fetch fundamentals (this still needs individual .info API call)
    fundamentals = get_comprehensive_fundamentals(ticker)

    if not fundamentals or not fundamentals.get('current_price'):
        print(" ✗ No data")
        return None

    # Calculate intrinsic value
    intrinsic_value = calculate_composite_intrinsic_value(fundamentals)

    if not intrinsic_value:
        print(" ✗ Cannot calculate value")
        return None

    # Calculate margin of safety
    current_price = fundamentals['current_price']
    margin_of_safety = ((intrinsic_value - current_price) / current_price) * 100

    # Calculate value score
    value_score, score_breakdown = calculate_value_score(fundamentals, intrinsic_value)

    # Make decision
    decision, confidence = determine_investment_decision(value_score, margin_of_safety, fundamentals)

    # Calculate momentum timing using pre-downloaded data (no extra API call)
    timing = calculate_momentum_timing(ticker, preloaded_data=preloaded_price_data)

    if timing:
        timing_label = timing['timing_label']
        timing_score = timing['timing_score']
    else:
        timing_label = 'N/A'
        timing_score = 50  # Assume neutral if can't calculate

    print(f" ✓ (Score: {value_score:.0f}, MoS: {margin_of_safety:+.1f}%, Timing: {timing_label})")

    # Compile results
    result = {
        'ticker': ticker,
        'company_name': fundamentals.get('company_name'),
        'sector': fundamentals.get('sector'),
        'current_price': current_price,
        'intrinsic_value': intrinsic_value,
        'margin_of_safety': margin_of_safety,
        'value_score': value_score,
        'score_breakdown': score_breakdown,
        'decision': decision,
        'confidence': confidence,

        # Momentum timing (NEW)
        'timing_score': timing_score,
        'timing_label': timing_label,
        'timing_data': timing,

        # Key metrics for display
        'pe_ratio': fundamentals.get('pe_ratio'),
        'pb_ratio': fundamentals.get('pb_ratio'),
        'roe': fundamentals.get('roe'),
        'debt_equity': fundamentals.get('debt_equity'),
        'profit_margin': fundamentals.get('profit_margin'),
        'dividend_yield': fundamentals.get('dividend_yield'),
        'earnings_growth': fundamentals.get('earnings_growth'),
        'market_cap': fundamentals.get('market_cap'),

        # Full fundamentals for detailed view
        'fundamentals': fundamentals,
    }

    return result


def _batch_download_prices(tickers: list, days: int = 200):
    """
    Phase 1: Batch download all OHLCV data at once.
    
    yf.download() with multiple tickers is a SINGLE API call per chunk,
    so 672 stocks = ~14 calls total (not 672 individual calls).
    This is the KEY to avoiding rate limits.
    """
    end_date = now().replace(tzinfo=None)
    start_date = end_date - timedelta(days=days)

    CHUNK_SIZE = 50
    all_data = {}

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
                    all_data[ticker] = raw_data.copy()
            else:
                for ticker in chunk:
                    try:
                        if ticker in raw_data.columns.get_level_values(0):
                            stock_df = raw_data[ticker].dropna(how='all')
                            if not stock_df.empty and len(stock_df) > 0:
                                all_data[ticker] = stock_df.copy()
                    except (KeyError, TypeError):
                        pass

            print(f"✓ ({len([t for t in chunk if t in all_data])}/{len(chunk)} OK)")

            if i + CHUNK_SIZE < len(tickers):
                time.sleep(2.0)

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
                        all_data[chunk[0]] = raw_data.copy()
                    else:
                        for ticker in chunk:
                            try:
                                if ticker in raw_data.columns.get_level_values(0):
                                    stock_df = raw_data[ticker].dropna(how='all')
                                    if not stock_df.empty:
                                        all_data[ticker] = stock_df.copy()
                            except (KeyError, TypeError):
                                pass
                    print("  ↳ Retry OK")
            except:
                print("  ↳ Retry failed, skipping chunk")

    return all_data


def _prefilter_stocks(all_price_data: dict, min_days: int = 30, min_avg_volume: int = 50000):
    """
    Phase 2: Pre-filter stocks using OHLCV data (no API calls needed).
    
    Eliminates dead, suspended, and illiquid stocks BEFORE making
    expensive individual .info API calls. This is what prevents rate limits.
    
    Criteria:
        - At least min_days trading days of data
        - Average daily volume > min_avg_volume
        - Traded within last 10 calendar days (not suspended)
        - Price > 0
    """
    qualified = {}
    skipped_reasons = {'no_data': 0, 'too_short': 0, 'low_volume': 0, 'suspended': 0}

    cutoff_date = (now().replace(tzinfo=None) - timedelta(days=10))

    for ticker, df in all_price_data.items():
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Must have enough history
        if len(df) < min_days:
            skipped_reasons['too_short'] += 1
            continue

        # Must have traded recently (not suspended)
        last_trade = df.index[-1]
        if hasattr(last_trade, 'tz') and last_trade.tz is not None:
            last_trade = last_trade.tz_localize(None)
        if last_trade < cutoff_date:
            skipped_reasons['suspended'] += 1
            continue

        # Must have decent volume (not illiquid)
        avg_vol = df['Volume'].tail(20).mean() if 'Volume' in df.columns else 0
        if avg_vol < min_avg_volume:
            skipped_reasons['low_volume'] += 1
            continue

        # Must have valid price
        last_close = df['Close'].iloc[-1] if 'Close' in df.columns else 0
        if last_close <= 0:
            skipped_reasons['no_data'] += 1
            continue

        qualified[ticker] = df

    print("\n  Pre-filter results:")
    print(f"    ✓ Qualified: {len(qualified)} stocks (will fetch fundamentals)")
    print(f"    ✗ Skipped: {sum(skipped_reasons.values())} stocks")
    print(f"      - Too short history (<{min_days}d): {skipped_reasons['too_short']}")
    print(f"      - Low volume (<{min_avg_volume:,}): {skipped_reasons['low_volume']}")
    print(f"      - Possibly suspended: {skipped_reasons['suspended']}")
    print(f"      - No valid price: {skipped_reasons['no_data']}")
    print(f"    → API calls saved: ~{sum(skipped_reasons.values()) * 2} individual requests avoided!\n")

    return qualified


def run_value_screening(watchlist):
    """
    Screen all stocks in watchlist using a TWO-PHASE approach:
    
    Phase 1: Batch download ALL OHLCV data at once (cheap - ~14 batch calls for 672 stocks)
    Phase 2: Pre-filter out dead/illiquid stocks using the downloaded data
    Phase 3: Only fetch expensive .info fundamentals for surviving stocks
    
    This approach lets you scan ALL 672 Sharia stocks without getting rate-limited.
    
    Args:
        watchlist: List of ticker symbols
    
    Returns:
        List of screening results
    """
    print("\n" + "="*100)
    print("VALUE INVESTING SCREENER - FUNDAMENTAL ANALYSIS")
    print("="*100)
    print(f"Generated: {now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print(f"Universe: {len(watchlist)} Sharia-compliant stocks")
    print("Philosophy: Buy undervalued quality companies, hold long-term")
    print("="*100)

    start_time = time.time()
    results = []

    # ── PHASE 1: Batch download all OHLCV data (fast, ~14 API calls total) ──
    print("\n📥 PHASE 1: Batch downloading all price data...")
    all_price_data = _batch_download_prices(watchlist)
    print(f"  Downloaded: {len(all_price_data)}/{len(watchlist)} stocks")

    # ── PHASE 2: Pre-filter (eliminates dead/illiquid stocks, zero API calls) ──
    print("\n🔍 PHASE 2: Pre-filtering stocks (eliminating dead/illiquid)...")
    qualified_stocks = _prefilter_stocks(all_price_data)

    if not qualified_stocks:
        print("\nNo stocks passed the pre-filter. Check internet connection.")
        return []

    # ── PHASE 3: Fetch fundamentals ONLY for qualified stocks ──
    qualified_tickers = list(qualified_stocks.keys())

    BATCH_SIZE = 3     # 3 concurrent workers per batch
    BATCH_DELAY = 5.0  # 5 seconds pause between batches

    total_batches = (len(qualified_tickers) + BATCH_SIZE - 1) // BATCH_SIZE
    estimated_minutes = total_batches * (BATCH_DELAY + 3) / 60

    print(f"📊 PHASE 3: Fetching fundamentals for {len(qualified_tickers)} qualified stocks...")
    print(f"  Batches: {total_batches} | Estimated time: ~{estimated_minutes:.1f} minutes")
    print(f"  (Saved ~{(len(watchlist) - len(qualified_tickers)) * 2} unnecessary API calls via pre-filter)\n")

    processed = 0

    for batch_idx in range(0, len(qualified_tickers), BATCH_SIZE):
        batch = qualified_tickers[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = (batch_idx // BATCH_SIZE) + 1

        # Process batch concurrently, passing pre-downloaded price data
        batch_results = {}
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            futures = {
                executor.submit(screen_stock, ticker, qualified_stocks.get(ticker)): ticker
                for ticker in batch
            }

            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    result = future.result()
                    if result:
                        batch_results[ticker] = result
                except Exception as e:
                    print(f"  ✗ {ticker}: Error - {e}")

        # Collect results
        for ticker in batch:
            if ticker in batch_results:
                results.append(batch_results[ticker])

        processed += len(batch)
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (len(qualified_tickers) - processed) / rate if rate > 0 else 0

        print(f"  [Batch {batch_num}/{total_batches}] {processed}/{len(qualified_tickers)} done | "
              f"{elapsed:.0f}s elapsed | ~{remaining:.0f}s remaining")

        # Pause between batches to respect API rate limits
        if batch_idx + BATCH_SIZE < len(qualified_tickers):
            time.sleep(BATCH_DELAY)

    total_time = time.time() - start_time
    print(f"\nScreening completed in {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
    print(f"Successfully analyzed: {len(results)}/{len(qualified_tickers)} qualified stocks")

    if not results:
        print("\nNo stocks could be analyzed. Check internet connection or try again later.")
        return []

    # Sort by value score (highest first)
    results.sort(key=lambda x: x['value_score'], reverse=True)

    return results


# ============================================================================
# RESULTS DISPLAY
# ============================================================================

def print_screening_results(results):
    """
    Print comprehensive screening results
    
    Args:
        results: List of screening results
    """
    if not results:
        return

    # 1. SUMMARY TABLE
    print("\n" + "="*100)
    print("VALUE SCREENING RESULTS v2.1 - RANKED BY OPPORTUNITY (with Momentum Timing)")
    print("="*120)
    print(f"{'Rank':<6} {'Ticker':<10} {'Decision':<20} {'Score':<8} {'MoS%':<10} {'Price':<12} {'IV':<12} {'P/E':<8} {'Timing':<18}")
    print("-"*120)

    for idx, r in enumerate(results, 1):
        rank = f"#{idx}"
        ticker = r['ticker']
        decision = r['decision']

        # Safely format numeric values
        try:
            score = f"{r['value_score']:.0f}/100"
        except:
            score = "N/A"

        try:
            mos = f"{r['margin_of_safety']:+.1f}%"
        except:
            mos = "N/A"

        try:
            price = f"IDR {r['current_price']:,.0f}"
        except:
            price = "N/A"

        try:
            iv = f"IDR {r['intrinsic_value']:,.0f}"
        except:
            iv = "N/A"

        pe = f"{r['pe_ratio']:.1f}" if r.get('pe_ratio') and isinstance(r['pe_ratio'], (int, float)) else "N/A"
        timing = r.get('timing_label', 'N/A')

        print(f"{rank:<6} {ticker:<10} {decision:<20} {score:<8} {mos:<10} {price:<12} {iv:<12} {pe:<8} {timing:<18}")

    # 2. CATEGORY BREAKDOWN
    print("\n" + "="*100)
    print("📋 INVESTMENT CATEGORIES")
    print("="*100)

    strong_buy = [r for r in results if "STRONG BUY" in r['decision']]
    buy = [r for r in results if r['decision'] == "🟢 BUY"]
    hold = [r for r in results if "HOLD" in r['decision']]
    avoid = [r for r in results if "AVOID" in r['decision']]
    value_trap = [r for r in results if "VALUE TRAP" in r['decision']]

    if strong_buy:
        print(f"\n✅ STRONG BUY ({len(strong_buy)} stocks) - Excellent opportunities:")
        for r in strong_buy[:5]:  # Top 5
            mos_str = f"{r['margin_of_safety']:+.1f}%" if isinstance(r.get('margin_of_safety'), (int, float)) else "N/A"
            print(f"   • {r['ticker']:<10} {r['company_name']:<40} Score: {r['value_score']:.0f}, MoS: {mos_str}")

    if buy:
        print(f"\n🟢 BUY ({len(buy)} stocks) - Good value:")
        for r in buy[:5]:
            mos_str = f"{r['margin_of_safety']:+.1f}%" if isinstance(r.get('margin_of_safety'), (int, float)) else "N/A"
            print(f"   • {r['ticker']:<10} {r['company_name']:<40} Score: {r['value_score']:.0f}, MoS: {mos_str}")

    if hold:
        print(f"\n🟡 HOLD ({len(hold)} stocks) - Fair value")

    if avoid:
        print(f"\n🔴 AVOID ({len(avoid)} stocks) - Overvalued or poor quality")

    if value_trap:
        print(f"\n⚠️ VALUE TRAP WARNING ({len(value_trap)} stocks) - Cheap but declining:")
        for r in value_trap:
            eg = r.get('earnings_growth')
            eg_str = f"{eg*100:+.1f}%" if eg and isinstance(eg, (int, float)) else "N/A"
            print(f"   • {r['ticker']:<10} {r['company_name']:<40} Earnings: {eg_str}")

    # 3. DETAILED ANALYSIS (Top 10)
    print("\n" + "="*100)
    print("🔬 DETAILED FUNDAMENTAL ANALYSIS (Top 10 Opportunities)")
    print("="*100)

    for r in results[:10]:
        print(f"\n{'='*100}")
        print(f"{r['decision']} - {r['ticker']} - {r['company_name']}")
        print(f"Sector: {r['sector']} | Confidence: {r['confidence']}")
        print(f"{'='*100}")

        # Valuation
        print("\n💰 VALUATION:")
        try:
            print(f"   • Current Price:   IDR {r['current_price']:>12,.0f}")
        except:
            print("   • Current Price:   N/A")

        try:
            print(f"   • Intrinsic Value: IDR {r['intrinsic_value']:>12,.0f}")
        except:
            print("   • Intrinsic Value: N/A")

        try:
            print(f"   • Margin of Safety: {r['margin_of_safety']:>11.1f}%")
        except:
            print("   • Margin of Safety: N/A")

        print(f"   • Value Score:      {r['value_score']:>11.0f}/100")

        # Momentum Timing (NEW)
        td = r.get('timing_data')
        if td:
            print(f"\n📉 MOMENTUM TIMING: {r.get('timing_label', 'N/A')} (Score: {r.get('timing_score', 0)}/100)")
            print(f"   • 5-day Return:  {td.get('roc_5', 0):+.2f}%")
            print(f"   • 20-day Return: {td.get('roc_20', 0):+.2f}%")
            print(f"   • Slope:         {td.get('slope_pct', 0):+.3f}%/day")
            print(f"   • Above SMA20:   {'YES' if td.get('above_sma20') else 'NO'}")
            print(f"   • OBV:           {td.get('obv_trend', 'N/A')}")

            if r.get('timing_score', 50) < 25:
                print("   *** WARNING: Falling knife! Wait for momentum to turn positive before buying. ***")
            elif r.get('timing_score', 50) >= 70:
                print("   *** GOOD: Momentum confirms the fundamental case. Good time to buy. ***")

        # Valuation Ratios
        print("\n📊 VALUATION RATIOS:")
        print(f"   • P/E Ratio:    {r['pe_ratio']:>8.2f}" if r.get('pe_ratio') else "   • P/E Ratio:    N/A")
        print(f"   • P/B Ratio:    {r['pb_ratio']:>8.2f}" if r.get('pb_ratio') else "   • P/B Ratio:    N/A")

        # Profitability
        print("\n💼 PROFITABILITY:")
        roe = r.get('roe')
        if roe and isinstance(roe, (int, float)):
            print(f"   • ROE:           {roe*100:>7.1f}%")

        pm = r.get('profit_margin')
        if pm and isinstance(pm, (int, float)):
            print(f"   • Profit Margin: {pm*100:>7.1f}%")

        eg = r.get('earnings_growth')
        if eg and isinstance(eg, (int, float)):
            print(f"   • Earnings Growth: {eg*100:>5.1f}%")

        # Financial Health
        print("\n🏥 FINANCIAL HEALTH:")
        de = r.get('debt_equity')
        if de is not None and isinstance(de, (int, float)):
            print(f"   • Debt/Equity:  {de:>8.1f}%")

        mc = r.get('market_cap')
        if mc and isinstance(mc, (int, float)):
            print(f"   • Market Cap:    IDR {mc:>12,.0f}")

        # Dividend
        dy = r.get('dividend_yield')
        if dy and isinstance(dy, (int, float)) and dy > 0:
            print("\n💵 DIVIDEND:")
            print(f"   • Yield:         {dy*100:>7.2f}%")

        # Score Breakdown
        print("\n🎯 SCORE BREAKDOWN:")
        for item in r['score_breakdown']:
            print(f"   {item}")

    # 4. PORTFOLIO RECOMMENDATIONS
    print("\n" + "="*100)
    print("🎯 PORTFOLIO CONSTRUCTION RECOMMENDATIONS")
    print("="*100)

    if strong_buy:
        print("\n💎 TOP PICKS (Allocate 60% here):")
        for i, r in enumerate(strong_buy[:3], 1):
            print(f"   {i}. {r['ticker']} - {r['company_name']}")
            try:
                cp = r['current_price']
                iv = r['intrinsic_value']
                mos = r['margin_of_safety']
                print(f"      Target: IDR {cp:,.0f} → IDR {iv:,.0f} ({mos:+.1f}% upside)")
            except:
                print("      Target: Check detailed analysis")

    if buy:
        print("\n🟢 SECONDARY PICKS (Allocate 30% here):")
        for i, r in enumerate(buy[:2], 1):
            print(f"   {i}. {r['ticker']} - {r['company_name']}")

    print("\n💰 KEEP 10% CASH for opportunities")

    # 5. RISK WARNINGS
    print("\n" + "="*100)
    print("⚠️  RISK WARNINGS & DISCLAIMERS")
    print("="*100)
    print("""
    1. VALUE TRAPS: Cheap stocks can stay cheap (or get cheaper) if business is declining
    2. TIMING: Value investing requires PATIENCE - hold 1-5 years minimum
    3. DIVERSIFICATION: Don't put all eggs in one basket - spread across 5-10 stocks
    4. QUARTERLY REVIEW: Re-run this screening every 3 months after earnings reports
    5. MACRO RISKS: Economic crisis, currency devaluation, political instability
    6. NOT FINANCIAL ADVICE: This is educational analysis only, DYOR!
    
    📚 Recommended Reading:
    - "The Intelligent Investor" by Benjamin Graham
    - "One Up on Wall Street" by Peter Lynch
    - "Common Stocks and Uncommon Profits" by Philip Fisher
    """)

    print("="*100)
    print(f"📊 Total stocks analyzed: {len(results)}")
    print(f"✅ Strong Buy opportunities: {len(strong_buy)}")
    print(f"🟢 Buy opportunities: {len(buy)}")
    print(f"⚠️  Value traps detected: {len(value_trap)}")
    print("="*100 + "\n")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main screening engine"""

    # Start logging
    dual_output, log_file, timestamp = start_logging()

    try:
        print(f"\n{'='*100}")
        print("💎 KALA - VALUE INVESTING SCREENER")
        print(f"{'='*100}")
        print(f"Date: {now().strftime('%A, %B %d, %Y at %H:%M:%S')} WIB")
        print(f"Stocks to screen: {len(WATCHLIST)}")
        print("Philosophy: Pure Fundamental Analysis - No Technical Noise")
        print("Goal: Find undervalued quality companies for long-term wealth")
        print(f"{'='*100}\n")

        # Run screening
        results = run_value_screening(WATCHLIST)

        # Print results
        if results:
            print_screening_results(results)

            # Save to CSV
            csv_file = save_to_csv(results, timestamp)
            save_to_watchlist(results)

            # ============================================================
            # PORTFOLIO OPTIMIZATION (Max Sharpe - Efficient Frontier)
            # Tells you EXACTLY how many lots of each stock to buy.
            # Optimal risk-adjusted allocation for long-term holding.
            # ============================================================
            try:
                from portfolio_optimizer import optimize_from_signals

                # Use optimize_from_signals for consistent ranking & filtering.
                # It sorts ALL results by value_score descending, filters to
                # BUY signals only, and selects the top N highest-scoring stocks.
                portfolio = optimize_from_signals(
                    results,
                    total_capital=INITIAL_CAPITAL,
                    strategy='sharpe',           # Max Sharpe for long-term
                    top_n=15,                    # Top 15 candidates max
                    min_score=60,                # value_score >= 60
                    score_key='value_score',
                )
            except ImportError:
                print("\n  [Portfolio Optimizer not available - pip install pypfopt]")
            except Exception as e:
                print(f"\n  [Portfolio optimization error: {e}]")

            # Success message
            print(f"\n{'='*100}")
            print("✅ SCREENING COMPLETE!")
            print(f"{'='*100}")
            print("\n📁 SAVED FILES:")
            print(f"   📄 Full Report (TXT): {os.path.basename(log_file)}")
            if csv_file:
                print(f"   📊 Summary (CSV):     {os.path.basename(csv_file)}")
            print(f"\n💾 Location: {os.path.abspath('results')}")
            print("\n💡 TIP: Open CSV in Excel, sort by 'Value_Score' descending!")
            print("💡 TIP: Re-run this screening every quarter after earnings reports")
            print(f"{'='*100}\n")
        else:
            print("\n❌ No stocks could be screened. Check internet connection.")

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        print(f"📄 Partial results saved to: {log_file}")
        raise

    finally:
        dual_output.close()


if __name__ == '__main__':
    main()
