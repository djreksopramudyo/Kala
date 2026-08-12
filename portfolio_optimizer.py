"""
Kala - Portfolio Construction & Optimization Module
==========================================================

Transitions from "Stock Picking" to "Portfolio Management".
Instead of just Buy/Sell signals, this tells you EXACTLY how much to buy.

Strategies:
    1. HRP (Hierarchical Risk Parity) - For short-term / daily trading
       Allocates LESS capital to volatile stocks, keeping daily risk constant.

    2. Max Sharpe (Mean-Variance Optimization) - For long-term / value investing
       Mathematically optimal portfolio on the Efficient Frontier.

    3. Score-Weighted - Simple allocation proportional to signal scores.
       Fallback when there's insufficient price history for optimization.

Indonesia Rules:
    - 1 Lot = 100 Shares (IDX minimum trading unit)
    - All outputs in Lots (no fractional shares)
    - Uses pypfopt.DiscreteAllocation for lot-aware rounding
    - Total allocated amount never exceeds TOTAL_CAPITAL
    - Commission: 0.19% buy + 0.15% sell (standard IDX brokerage)

Usage:
    from portfolio_optimizer import optimize_portfolio_hrp, optimize_portfolio_sharpe

    # Short-term (daily trader) - HRP
    result = optimize_portfolio_hrp(buy_candidates, total_capital=50_000_000)

    # Long-term (value investor) - Max Sharpe
    result = optimize_portfolio_sharpe(buy_candidates, total_capital=100_000_000)

Dependencies:
    pip install pypfopt yfinance pandas numpy
"""

import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from pypfopt import DiscreteAllocation, EfficientFrontier, HRPOpt, expected_returns, risk_models

warnings.filterwarnings('ignore')

# ============================================================================
# CONSTANTS
# ============================================================================

SHARES_PER_LOT = 100          # IDX: 1 Lot = 100 Shares
BUY_COMMISSION = 0.0019       # 0.19% buy commission
SELL_COMMISSION = 0.0015      # 0.15% sell commission
MIN_HISTORY_DAYS = 252        # 1 year of trading days for covariance
MIN_WEIGHT = 0.02             # Minimum 2% weight per stock (avoid dust positions)
MAX_WEIGHT = 0.40             # Maximum 40% in any single stock


def _get_indonesian_time():
    """Get current time in WIB (UTC+7)."""
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=7)


# ============================================================================
# PRICE DATA FETCHER
# ============================================================================

def fetch_price_matrix(tickers: list, days: int = 400):
    """
    Download adjusted close prices for a list of tickers.
    Returns a DataFrame with dates as index and tickers as columns.

    Args:
        tickers: List of ticker symbols (e.g., ['BBRI.JK', 'TLKM.JK'])
        days: Number of calendar days of history to fetch

    Returns:
        pd.DataFrame of adjusted close prices, or None if failed
    """
    if not tickers:
        return None

    end_date = _get_indonesian_time().replace(tzinfo=None)
    start_date = end_date - timedelta(days=days)

    print(f"\n  Downloading price history for {len(tickers)} stocks ({days} days)...", end=" ", flush=True)

    try:
        raw = yf.download(
            tickers,
            start=start_date,
            end=end_date,
            progress=False,
            threads=True,
        )

        if raw.empty:
            print("FAILED (no data)")
            return None

        # Extract 'Close' prices
        if isinstance(raw.columns, pd.MultiIndex):
            prices = raw['Close'].copy()
        else:
            # Single ticker case
            prices = raw[['Close']].copy()
            prices.columns = [tickers[0]]

        # Drop tickers with too many NaNs (> 30% missing)
        threshold = len(prices) * 0.3
        prices = prices.dropna(axis=1, thresh=int(len(prices) - threshold))

        # Forward-fill remaining gaps, then drop any remaining NaN rows
        prices = prices.ffill().dropna()

        if prices.empty or len(prices) < 60:
            print(f"FAILED (only {len(prices)} trading days after cleaning)")
            return None

        print(f"OK ({len(prices)} trading days, {len(prices.columns)} tickers)")
        return prices

    except Exception as e:
        print(f"FAILED ({e})")
        return None


# ============================================================================
# STRATEGY 1: HRP - HIERARCHICAL RISK PARITY (Short-Term Trading)
# ============================================================================

def optimize_portfolio_hrp(
    buy_candidates: list,
    total_capital: float,
    price_history_days: int = 400,
    score_key: str = 'technical_score',
):
    """
    Hierarchical Risk Parity portfolio optimization.
    Best for SHORT-TERM / DAY TRADING.

    HRP allocates LESS capital to volatile stocks, keeping overall
    portfolio risk balanced. No need for expected returns estimation,
    which is unreliable for short time horizons.

    Args:
        buy_candidates: List of signal dicts from get_live_signal().
                        Each must have 'ticker' and 'price' keys.
        total_capital: Total budget in IDR (e.g., 50_000_000)
        price_history_days: Days of price history for covariance
        score_key: Key to use for score-based filtering

    Returns:
        dict with 'allocations' (DataFrame), 'summary', and 'remaining_cash'
    """
    print("\n" + "="*100)
    print("PORTFOLIO OPTIMIZER - HRP (Hierarchical Risk Parity)")
    print("Strategy: Allocate LESS to volatile stocks, keep risk balanced")
    print("Best for: Short-term trading (days to weeks)")
    print("="*100)
    print(f"Capital: IDR {total_capital:,.0f}")
    print(f"Candidates: {len(buy_candidates)} stocks")

    if not buy_candidates:
        print("No buy candidates provided.")
        return None

    # Extract tickers and latest prices
    tickers = [c['ticker'] for c in buy_candidates]
    latest_prices = pd.Series(
        {c['ticker']: c['price'] for c in buy_candidates}
    )

    # Fetch price history
    prices = fetch_price_matrix(tickers, days=price_history_days)

    if prices is None or prices.empty:
        print("\n  Falling back to score-weighted allocation...")
        return _score_weighted_allocation(buy_candidates, total_capital, score_key)

    # Only keep tickers that have price history
    valid_tickers = [t for t in tickers if t in prices.columns]
    if len(valid_tickers) < 2:
        print(f"\n  Only {len(valid_tickers)} ticker(s) with history. Need >= 2 for HRP.")
        print("  Falling back to score-weighted allocation...")
        return _score_weighted_allocation(buy_candidates, total_capital, score_key)

    prices = prices[valid_tickers]
    latest_prices = latest_prices[valid_tickers]

    # Calculate returns
    returns = prices.pct_change().dropna()

    print(f"\n  Running HRP optimization on {len(valid_tickers)} stocks...")

    try:
        # HRP optimization
        hrp = HRPOpt(returns)
        weights = hrp.optimize()
        cleaned_weights = hrp.clean_weights(cutoff=MIN_WEIGHT)

        # Enforce max weight
        cleaned_weights = _enforce_max_weight(cleaned_weights, MAX_WEIGHT)

        print("  HRP weights calculated successfully.")

    except Exception as e:
        print(f"  HRP failed ({e}). Falling back to score-weighted.")
        return _score_weighted_allocation(buy_candidates, total_capital, score_key)

    # Discrete allocation (Lots)
    return _discrete_allocate(
        cleaned_weights, latest_prices, total_capital,
        buy_candidates, score_key, strategy_name="HRP"
    )


# ============================================================================
# STRATEGY 2: MAX SHARPE - MEAN-VARIANCE OPTIMIZATION (Long-Term Investing)
# ============================================================================

def optimize_portfolio_sharpe(
    buy_candidates: list,
    total_capital: float,
    price_history_days: int = 500,
    score_key: str = 'value_score',
):
    """
    Mean-Variance Optimization targeting Maximum Sharpe Ratio.
    Best for LONG-TERM / VALUE INVESTING.

    Finds the mathematically optimal portfolio on the Efficient Frontier
    that maximizes risk-adjusted returns based on historical data.

    Args:
        buy_candidates: List of screening result dicts.
                        Each must have 'ticker' and 'current_price' keys.
        total_capital: Total budget in IDR
        price_history_days: Days of history (more is better for long-term)
        score_key: Key to use for score-based filtering

    Returns:
        dict with 'allocations' (DataFrame), 'summary', and 'remaining_cash'
    """
    print("\n" + "="*100)
    print("PORTFOLIO OPTIMIZER - MAX SHARPE (Mean-Variance Optimization)")
    print("Strategy: Maximize risk-adjusted return on the Efficient Frontier")
    print("Best for: Long-term investing (months to years)")
    print("="*100)
    print(f"Capital: IDR {total_capital:,.0f}")
    print(f"Candidates: {len(buy_candidates)} stocks")

    if not buy_candidates:
        print("No buy candidates provided.")
        return None

    # Extract tickers and latest prices
    # Handle both 'price' (daily_trader) and 'current_price' (fundamental) keys
    tickers = [c['ticker'] for c in buy_candidates]
    latest_prices = pd.Series({
        c['ticker']: c.get('price', c.get('current_price', 0))
        for c in buy_candidates
    })

    # Filter out zero prices
    latest_prices = latest_prices[latest_prices > 0]
    tickers = list(latest_prices.index)

    # Fetch price history
    prices = fetch_price_matrix(tickers, days=price_history_days)

    if prices is None or prices.empty:
        print("\n  Falling back to score-weighted allocation...")
        return _score_weighted_allocation(buy_candidates, total_capital, score_key)

    valid_tickers = [t for t in tickers if t in prices.columns]
    if len(valid_tickers) < 2:
        print(f"\n  Only {len(valid_tickers)} ticker(s) with history. Need >= 2.")
        print("  Falling back to score-weighted allocation...")
        return _score_weighted_allocation(buy_candidates, total_capital, score_key)

    prices = prices[valid_tickers]
    latest_prices = latest_prices[valid_tickers]

    print(f"\n  Running Max Sharpe optimization on {len(valid_tickers)} stocks...")

    try:
        # Calculate expected returns and covariance
        mu = expected_returns.mean_historical_return(prices)
        S = risk_models.sample_cov(prices)

        # Mean-Variance Optimization - Max Sharpe
        ef = EfficientFrontier(mu, S, weight_bounds=(MIN_WEIGHT, MAX_WEIGHT))
        weights = ef.max_sharpe(risk_free_rate=0.065)  # BI rate ~6.5%
        cleaned_weights = ef.clean_weights(cutoff=MIN_WEIGHT)

        # Get performance metrics
        perf = ef.portfolio_performance(verbose=False, risk_free_rate=0.065)
        print(f"  Expected Annual Return: {perf[0]*100:.1f}%")
        print(f"  Annual Volatility:      {perf[1]*100:.1f}%")
        print(f"  Sharpe Ratio:           {perf[2]:.2f}")

    except Exception as e:
        print(f"  Max Sharpe failed ({e}). Trying Min Volatility...")
        try:
            ef = EfficientFrontier(mu, S, weight_bounds=(MIN_WEIGHT, MAX_WEIGHT))
            weights = ef.min_volatility()
            cleaned_weights = ef.clean_weights(cutoff=MIN_WEIGHT)
        except Exception as e2:
            print(f"  Min Volatility also failed ({e2}). Falling back to score-weighted.")
            return _score_weighted_allocation(buy_candidates, total_capital, score_key)

    # Discrete allocation (Lots)
    return _discrete_allocate(
        cleaned_weights, latest_prices, total_capital,
        buy_candidates, score_key, strategy_name="Max Sharpe"
    )


# ============================================================================
# STRATEGY 3: SCORE-WEIGHTED (Fallback / Simple)
# ============================================================================

def _score_weighted_allocation(
    buy_candidates: list,
    total_capital: float,
    score_key: str = 'technical_score',
):
    """
    Simple allocation proportional to signal scores.
    Used as fallback when insufficient price history for optimization.

    Args:
        buy_candidates: List of signal dicts
        total_capital: Budget in IDR
        score_key: Which score to use for weighting

    Returns:
        dict with 'allocations' (DataFrame), 'summary', etc.
    """
    print(f"\n  Using Score-Weighted allocation (based on '{score_key}')...")

    # Build weights from scores
    scores = {}
    prices_dict = {}
    for c in buy_candidates:
        ticker = c['ticker']
        score = c.get(score_key, 50)
        price = c.get('price', c.get('current_price', 0))
        if score > 0 and price > 0:
            scores[ticker] = score
            prices_dict[ticker] = price

    if not scores:
        print("  No valid candidates with scores > 0.")
        return None

    total_score = sum(scores.values())
    raw_weights = {t: s / total_score for t, s in scores.items()}

    # Enforce max weight
    cleaned_weights = _enforce_max_weight(raw_weights, MAX_WEIGHT)

    latest_prices = pd.Series(prices_dict)
    latest_prices = latest_prices[list(cleaned_weights.keys())]

    return _discrete_allocate(
        cleaned_weights, latest_prices, total_capital,
        buy_candidates, score_key, strategy_name="Score-Weighted"
    )


# ============================================================================
# DISCRETE ALLOCATION (Lots-Aware)
# ============================================================================

def _discrete_allocate(
    weights: dict,
    latest_prices: pd.Series,
    total_capital: float,
    buy_candidates: list,
    score_key: str,
    strategy_name: str = "",
):
    """
    Convert continuous weights to discrete Lots using pypfopt.

    Args:
        weights: {ticker: weight} from optimizer
        latest_prices: pd.Series of current prices
        total_capital: Budget in IDR
        buy_candidates: Original signal list (for score lookup)
        score_key: Score key for display
        strategy_name: Name of the strategy for display

    Returns:
        dict with 'allocations' DataFrame, 'summary' dict, 'remaining_cash' float
    """
    # Filter out zero-weight tickers
    active_weights = {t: w for t, w in weights.items() if w > 0}
    if not active_weights:
        print("  No active allocations after optimization.")
        return None

    # Align prices with active weights
    active_tickers = list(active_weights.keys())
    prices_aligned = latest_prices.reindex(active_tickers).dropna()
    active_weights = {t: active_weights[t] for t in prices_aligned.index}

    # Account for buy commission in available capital
    effective_capital = total_capital / (1 + BUY_COMMISSION)

    # Convert per-share prices to per-lot prices for DiscreteAllocation
    # This ensures allocations come out in Lots, not shares
    lot_prices = prices_aligned * SHARES_PER_LOT

    # Discrete allocation
    try:
        da = DiscreteAllocation(
            active_weights,
            lot_prices,
            total_portfolio_value=effective_capital,
        )
        lot_allocation, leftover = da.greedy_portfolio()
    except Exception as e:
        print(f"  DiscreteAllocation failed ({e}). Using manual rounding.")
        lot_allocation, leftover = _manual_lot_allocation(
            active_weights, prices_aligned, effective_capital
        )

    if not lot_allocation:
        print("  No lots could be allocated (capital too small or prices too high).")
        return None

    # Build the score lookup
    score_lookup = {}
    for c in buy_candidates:
        score_lookup[c['ticker']] = c.get(score_key, 0)

    # Build results DataFrame
    rows = []
    total_invested = 0
    for ticker, lots in sorted(lot_allocation.items(), key=lambda x: -x[1]):
        if lots <= 0:
            continue
        shares = lots * SHARES_PER_LOT
        price = prices_aligned.get(ticker, 0)
        value = shares * price
        commission = value * BUY_COMMISSION
        total_cost = value + commission
        weight_pct = active_weights.get(ticker, 0) * 100
        score = score_lookup.get(ticker, 0)

        rows.append({
            'Ticker': ticker,
            'Score': f"{score:.0f}",
            'Weight_%': f"{weight_pct:.1f}",
            'Price_IDR': price,
            'Lots': lots,
            'Shares': shares,
            'Value_IDR': value,
            'Commission_IDR': commission,
            'Total_Cost_IDR': total_cost,
        })
        total_invested += total_cost

    df = pd.DataFrame(rows)
    remaining_cash = total_capital - total_invested

    # Print the allocation table
    _print_allocation_table(df, total_capital, total_invested, remaining_cash, strategy_name)

    return {
        'allocations': df,
        'weights': active_weights,
        'total_invested': total_invested,
        'remaining_cash': remaining_cash,
        'strategy': strategy_name,
    }


def _manual_lot_allocation(weights: dict, prices: pd.Series, capital: float):
    """Manual lot allocation fallback when DiscreteAllocation fails."""
    allocation = {}
    remaining = capital

    # Sort by weight descending
    sorted_tickers = sorted(weights.keys(), key=lambda t: -weights[t])

    for ticker in sorted_tickers:
        target_value = capital * weights[ticker]
        price_per_lot = prices[ticker] * SHARES_PER_LOT
        if price_per_lot <= 0:
            continue
        lots = int(target_value / price_per_lot)
        if lots > 0 and lots * price_per_lot <= remaining:
            allocation[ticker] = lots
            remaining -= lots * price_per_lot

    return allocation, remaining


# ============================================================================
# WEIGHT ENFORCEMENT
# ============================================================================

def _enforce_max_weight(weights: dict, max_w: float) -> dict:
    """Cap any weight at max_w and redistribute excess proportionally."""
    capped = {}
    excess = 0.0
    uncapped_total = 0.0

    for t, w in weights.items():
        if w > max_w:
            capped[t] = max_w
            excess += w - max_w
        else:
            capped[t] = w
            uncapped_total += w

    # Redistribute excess to uncapped stocks
    if excess > 0 and uncapped_total > 0:
        for t in capped:
            if capped[t] < max_w:
                capped[t] += excess * (capped[t] / uncapped_total)
                capped[t] = min(capped[t], max_w)

    # Renormalize
    total = sum(capped.values())
    if total > 0:
        capped = {t: w / total for t, w in capped.items()}

    return capped


# ============================================================================
# DISPLAY
# ============================================================================

def _print_allocation_table(
    df: pd.DataFrame,
    total_capital: float,
    total_invested: float,
    remaining_cash: float,
    strategy_name: str,
):
    """Print a formatted portfolio allocation table."""

    print(f"\n{'='*100}")
    print(f"PORTFOLIO ALLOCATION - {strategy_name}")
    print(f"{'='*100}")
    print(f"{'Ticker':<10} {'Score':<7} {'Weight':<8} {'Price':>12} {'Lots':>6} {'Shares':>8} {'Value (IDR)':>15} {'+ Commission':>14}")
    print("-"*100)

    for _, row in df.iterrows():
        print(
            f"{row['Ticker']:<10} "
            f"{row['Score']:<7} "
            f"{row['Weight_%']:>6}% "
            f"{row['Price_IDR']:>12,.0f} "
            f"{row['Lots']:>6,} "
            f"{row['Shares']:>8,} "
            f"{row['Value_IDR']:>15,.0f} "
            f"{row['Commission_IDR']:>14,.0f}"
        )

    print("-"*100)
    print(f"{'TOTAL':<10} {'':7} {'100.0':>6}% {'':>12} "
          f"{df['Lots'].sum():>6,} "
          f"{df['Shares'].sum():>8,} "
          f"{df['Value_IDR'].sum():>15,.0f} "
          f"{df['Commission_IDR'].sum():>14,.0f}")
    print(f"\n  Budget:         IDR {total_capital:>15,.0f}")
    print(f"  Total Invested: IDR {total_invested:>15,.0f}")
    print(f"  Commission:     IDR {df['Commission_IDR'].sum():>15,.0f}")
    print(f"  Remaining Cash: IDR {remaining_cash:>15,.0f}")
    utilization = (total_invested / total_capital * 100) if total_capital > 0 else 0
    print(f"  Utilization:    {utilization:.1f}%")
    print("="*100)

    # Actionable output
    print("\n  ACTION: Buy order summary (copy to your broker):")
    print(f"  {'Ticker':<10} {'Lots':>6}   {'~ Cost IDR':>15}")
    print(f"  {'-'*40}")
    for _, row in df.iterrows():
        print(f"  {row['Ticker']:<10} {row['Lots']:>6}   {row['Total_Cost_IDR']:>15,.0f}")
    print()


# ============================================================================
# CONVENIENCE WRAPPERS
# ============================================================================

def optimize_from_signals(
    signals: list,
    total_capital: float,
    strategy: str = 'hrp',
    top_n: int = 10,
    min_score: float = 65,
    score_key: str = 'technical_score',
):
    """
    One-liner to go from signal list to portfolio allocation.

    IMPORTANT: Only stocks with BUY or STRONG BUY signals are considered.
    Stocks are ranked strictly by score descending, so the portfolio always
    contains the highest-conviction picks from the ENTIRE universe.

    Args:
        signals: Full list of signal dicts from any of the 3 scripts
        total_capital: Budget in IDR
        strategy: 'hrp' (short-term) or 'sharpe' (long-term) or 'score' (simple)
        top_n: Maximum number of stocks to include
        min_score: Minimum score to qualify as buy candidate
        score_key: Which score to filter/sort on

    Returns:
        Allocation result dict, or None
    """
    # ------------------------------------------------------------------
    # STEP 0: Sort ALL signals by score descending FIRST
    # ------------------------------------------------------------------
    all_sorted = sorted(signals, key=lambda x: x.get(score_key, 0), reverse=True)

    print(f"\n  {'='*70}")
    print(f"  CANDIDATE SELECTION (from {len(signals)} total stocks)")
    print(f"  {'='*70}")

    # Score distribution summary
    all_scores = [s.get(score_key, 0) for s in signals]
    if all_scores:
        print(f"  Score range: {min(all_scores):.0f} - {max(all_scores):.0f} ({score_key})")
        above_80 = sum(1 for sc in all_scores if sc >= 80)
        above_65 = sum(1 for sc in all_scores if sc >= 65)
        above_50 = sum(1 for sc in all_scores if sc >= 50)
        print(f"  Distribution: {above_80} stocks ≥80 | {above_65} stocks ≥65 | {above_50} stocks ≥50")

    # ------------------------------------------------------------------
    # STEP 1: Strict filter - only BUY signals that are safe
    #         HOLD, SELL, STRONG SELL, AVOID are all excluded.
    # ------------------------------------------------------------------
    BUY_SIGNALS = ('BUY', 'STRONG BUY', 'STRONG_BUY')  # Only actual buy signals

    candidates = [
        s for s in all_sorted
        if s.get(score_key, 0) >= min_score
        and s.get('signal', s.get('decision', '')) in BUY_SIGNALS
        and s.get('is_safe', True)
    ]

    # Show what got filtered out and why
    filtered_by_score = [s for s in all_sorted if s.get(score_key, 0) < min_score]
    filtered_by_signal = [
        s for s in all_sorted
        if s.get(score_key, 0) >= min_score
        and s.get('signal', s.get('decision', '')) not in BUY_SIGNALS
    ]
    filtered_by_safety = [
        s for s in all_sorted
        if s.get(score_key, 0) >= min_score
        and s.get('signal', s.get('decision', '')) in BUY_SIGNALS
        and not s.get('is_safe', True)
    ]

    print(f"\n  Filter: {score_key} >= {min_score} AND signal = BUY/STRONG BUY AND safe")
    print(f"  Passed filter:          {len(candidates)} stocks")
    print(f"  Rejected (score < {min_score}): {len(filtered_by_score)} stocks")
    print(f"  Rejected (not BUY):     {len(filtered_by_signal)} stocks")
    if filtered_by_signal:
        # Show top stocks that had good scores but weren't BUY
        top_non_buy = sorted(filtered_by_signal, key=lambda x: x.get(score_key, 0), reverse=True)[:5]
        for s in top_non_buy:
            print(f"    → {s['ticker']}: Score={s.get(score_key,0):.0f} but Signal={s.get('signal', s.get('decision','?'))}")
    if filtered_by_safety:
        print(f"  Rejected (unsafe):      {len(filtered_by_safety)} stocks")

    # Take top N
    candidates = candidates[:top_n]

    if not candidates:
        print(f"\n  ⚠ No candidates passed the filter ({score_key} >= {min_score} + BUY signal).")
        print("  Top 5 stocks overall (regardless of signal):")
        for i, s in enumerate(all_sorted[:5], 1):
            sig = s.get('signal', s.get('decision', '?'))
            sc = s.get(score_key, 0)
            print(f"    #{i} {s['ticker']}: Score={sc:.0f}, Signal={sig}")
        print("\n  TIP: The market may be weak. Consider waiting for better conditions,")
        print(f"       or lower min_score (currently {min_score}) if you want to be more aggressive.")
        return None

    print(f"\n  ✅ TOP {len(candidates)} BUY CANDIDATES (ranked by {score_key}):")
    print(f"  {'Rank':<6} {'Ticker':<12} {'Score':>8} {'Signal':<12} {'Price (IDR)':>15}")
    print(f"  {'-'*55}")
    for rank, c in enumerate(candidates, 1):
        ticker = c['ticker']
        score = c.get(score_key, 0)
        signal = c.get('signal', c.get('decision', '?'))
        price = c.get('price', c.get('current_price', 0))
        print(f"  #{rank:<5} {ticker:<12} {score:>8.0f} {signal:<12} {price:>15,.0f}")
    print(f"  {'-'*55}")

    if strategy == 'hrp':
        return optimize_portfolio_hrp(candidates, total_capital, score_key=score_key)
    elif strategy == 'sharpe':
        return optimize_portfolio_sharpe(candidates, total_capital, score_key=score_key)
    elif strategy == 'score':
        return _score_weighted_allocation(candidates, total_capital, score_key=score_key)
    else:
        print(f"  Unknown strategy '{strategy}'. Using HRP.")
        return optimize_portfolio_hrp(candidates, total_capital, score_key=score_key)


# ============================================================================
# STANDALONE TEST
# ============================================================================

if __name__ == '__main__':
    print("="*100)
    print("Portfolio Optimizer Module - Standalone Test")
    print("="*100)
    print("\nThis module is designed to be imported by:")
    print("  - kala_daily_trader.py  (uses HRP strategy)")
    print("  - kala_fundamental_only.py  (uses Max Sharpe strategy)")
    print("  - kala_engine.py  (uses both)")
    print("\nExample usage:")
    print("  from portfolio_optimizer import optimize_from_signals")
    print("  result = optimize_from_signals(signals, total_capital=50_000_000, strategy='hrp')")
    print("\nTo run a quick test, importing from daily trader:")

    try:
        from kala_daily_trader import WATCHLIST, batch_download_prices, get_live_signal, now

        print(f"\nFetching live signals for test ({min(5, len(WATCHLIST))} stocks)...")
        test_tickers = WATCHLIST[:5]
        all_data = batch_download_prices(test_tickers, days=200)

        test_signals = []
        for t in test_tickers:
            data = all_data.get(t)
            if data is not None:
                sig = get_live_signal(t, preloaded_data=data)
                if sig:
                    test_signals.append(sig)

        if test_signals:
            print(f"\nGot {len(test_signals)} signals. Running HRP optimization...")
            result = optimize_from_signals(
                test_signals,
                total_capital=21_600_000,
                strategy='hrp',
                min_score=0,
                top_n=5,
            )
            if result:
                print("\nTest completed successfully!")
        else:
            print("Could not fetch test signals.")

    except ImportError:
        print("  (Skipping live test - run from the Kala directory)")
    except Exception as e:
        print(f"  Test error: {e}")
