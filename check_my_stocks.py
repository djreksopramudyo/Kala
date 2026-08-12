"""
CHECK MY STOCKS - Simple Position Monitor v2.0
================================================

Just edit YOUR_POSITIONS below and run this file!

v2.0 Features:
- Suspension detection (won't recommend buying halted stocks)
- Market health check (warns if IHSG is bearish)
- ADX trend strength (warns about trendless stocks)
- ATR-based stop-loss (smarter than fixed %)
- Multi-timeframe confirmation

Usage:
    python check_my_stocks.py

That's it! The script will tell you what to do with each stock.
"""

from kala_daily_trader import check_exit_signals, check_market_health, now

# ============================================================================
# EDIT YOUR POSITIONS HERE - Replace with your actual stocks!
# ============================================================================

YOUR_POSITIONS = [
    # Format: {'ticker': 'STOCK.JK', 'entry_price': PRICE_YOU_PAID, 'shares': HOW_MANY_SHARES},

    # Example (REPLACE THESE WITH YOUR REAL STOCKS):
    {'ticker': 'ANTM.JK', 'entry_price': 4586.87, 'shares': 5200},


    # Add more stocks like this:
    # {'ticker': 'UNVR.JK', 'entry_price': 3800, 'shares': 300},
    # {'ticker': 'ICBP.JK', 'entry_price': 9500, 'shares': 100},
]

# ============================================================================
# NO NEED TO EDIT BELOW THIS LINE
# ============================================================================

def main():
    print("\n" + "="*80)
    print("CHECK YOUR STOCKS v2.0 (with Safety Checks)")
    print("="*80)
    print(f"Time: {now().strftime('%Y-%m-%d %H:%M:%S')} WIB (Indonesian Time)")
    print(f"Total positions: {len(YOUR_POSITIONS)}")
    print("="*80 + "\n")

    if not YOUR_POSITIONS:
        print("No positions found!")
        print("   Edit YOUR_POSITIONS at the top of this file.")
        print("   Add your stocks like:")
        print("   {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000},")
        return

    # Check market health first
    print("Checking overall market health (IHSG/JCI)...")
    mkt = check_market_health()
    print(f"\nMARKET STATUS: {mkt.get('status', 'UNKNOWN')}")
    if mkt.get('jci_price'):
        print(f"IHSG: {mkt['jci_price']:,.0f} | 5-day: {mkt['change_5d']:+.1f}% | 20-day: {mkt['change_20d']:+.1f}%")
    if mkt['status'] in ('BEARISH', 'MODERATE_BEAR'):
        print("*** WARNING: Market is BEARISH! Be extra careful with all positions. ***")
    print()

    # Check each position
    results = []
    for i, pos in enumerate(YOUR_POSITIONS, 1):
        ticker = pos['ticker']
        entry = pos['entry_price']
        shares = pos['shares']

        print(f"[{i}/{len(YOUR_POSITIONS)}] Analyzing {ticker}...", end=" ", flush=True)

        try:
            result = check_exit_signals(ticker, entry)
            if result:
                result['shares'] = shares
                result['total_profit'] = (result['current_price'] - entry) * shares
                results.append(result)

                # Show safety warnings inline
                td = result.get('technical_data', {})
                safety_info = ""
                if not td.get('is_safe', True):
                    safety_info = " [UNSAFE!]"
                elif td.get('adx', 25) < 20:
                    safety_info = " [weak trend]"

                print(f"done ({result['profit_pct']:+.1f}%){safety_info}")
            else:
                print("Failed to fetch data")
        except Exception as e:
            print(f"Error: {e}")

    if not results:
        print("\n⚠️  Could not analyze any positions. Check your internet connection.")
        return

    print("\n" + "="*80)
    print("📋 WHAT YOU NEED TO DO")
    print("="*80 + "\n")

    # Categorize positions
    urgent_sell = []
    consider_sell = []
    hold = []

    for r in results:
        if r['exit_signal'] and r['urgency'] == 'URGENT':
            urgent_sell.append(r)
        elif r['exit_signal']:
            consider_sell.append(r)
        else:
            hold.append(r)

    # Show urgent sells first (most important!)
    if urgent_sell:
        print("SELL THESE STOCKS NOW (URGENT!)")
        print("-" * 80)
        for r in urgent_sell:
            td = r.get('technical_data', {})
            print(f"\n{r['ticker']}")
            print(f"   Buy Price:     IDR {r['entry_price']:>10,}")
            print(f"   Current Price: IDR {r['current_price']:>10,.0f}")
            print(f"   Profit/Loss:   IDR {r['total_profit']:>10,.0f} ({r['profit_pct']:+.1f}%)")
            print(f"   Shares:        {r['shares']:>10,} shares")

            # Show new indicators
            if td:
                print(f"   ADX:           {td.get('adx', 0):>10.0f} ({'strong' if td.get('adx', 0) > 25 else 'WEAK!'})")
                print(f"   Score:         {td.get('technical_score', 0):>10.0f}/100")
                if not td.get('is_safe', True):
                    print("   SAFETY:        *** STOCK MAY BE SUSPENDED ***")

            print("\n   WHY SELL:")
            for reason in r['reasons']:
                print(f"   - {reason}")
            print()
    else:
        print("URGENT SELLS: None (good)")
        print()

    # Show consider sells
    if consider_sell:
        print("-" * 80)
        print("CONSIDER SELLING THESE")
        print("-" * 80)
        for r in consider_sell:
            td = r.get('technical_data', {})
            print(f"\n{r['ticker']}")
            print(f"   Buy Price:     IDR {r['entry_price']:>10,}")
            print(f"   Current Price: IDR {r['current_price']:>10,.0f}")
            print(f"   Profit/Loss:   IDR {r['total_profit']:>10,.0f} ({r['profit_pct']:+.1f}%)")
            print(f"   Shares:        {r['shares']:>10,} shares")

            if td:
                print(f"   ADX:           {td.get('adx', 0):>10.0f} ({'strong' if td.get('adx', 0) > 25 else 'WEAK!'})")
                print(f"   Weekly Trend:  {'UP' if td.get('weekly_trend') == 'UP' else 'DOWN'}")
                print(f"   Monthly Trend: {'UP' if td.get('monthly_trend') == 'UP' else 'DOWN'}")

            print("\n   WHY CONSIDER:")
            for reason in r['reasons']:
                print(f"   - {reason}")
            print()
    else:
        print("CONSIDER SELLS: None (good)")
        print()

    # Show holds
    if hold:
        print("-" * 80)
        print("KEEP HOLDING THESE (LOOKING GOOD)")
        print("-" * 80)
        for r in hold:
            td = r.get('technical_data', {})
            print(f"\n{r['ticker']}")
            print(f"   Buy Price:     IDR {r['entry_price']:>10,}")
            print(f"   Current Price: IDR {r['current_price']:>10,.0f}")
            print(f"   Profit/Loss:   IDR {r['total_profit']:>10,.0f} ({r['profit_pct']:+.1f}%)")
            print(f"   Shares:        {r['shares']:>10,} shares")

            if td:
                print(f"   ADX:           {td.get('adx', 0):>10.0f} ({'strong' if td.get('adx', 0) > 25 else 'weak'})")
                print(f"   Score:         {td.get('technical_score', 0):>10.0f}/100")
                print(f"   Stop-Loss:     IDR {td.get('stop_loss', 0):>10,.0f}")

            print("   Status:        No sell signals - keep holding")
        print()

    # Summary
    print("="*80)
    print("📊 SUMMARY")
    print("="*80)

    total_value = sum(r['current_price'] * r['shares'] for r in results)
    total_cost = sum(r['entry_price'] * r['shares'] for r in results)
    total_profit = total_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0

    print("\nTotal Portfolio:")
    print(f"   Cost Basis:    IDR {total_cost:>15,.0f}")
    print(f"   Current Value: IDR {total_value:>15,.0f}")
    print(f"   Profit/Loss:   IDR {total_profit:>15,.0f} ({total_profit_pct:+.1f}%)")

    print("\nAction Items:")
    print(f"   🔴 Sell Now:      {len(urgent_sell)} stocks")
    print(f"   🟡 Consider:      {len(consider_sell)} stocks")
    print(f"   🟢 Hold:          {len(hold)} stocks")

    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)

    if urgent_sell:
        print("\n1. URGENT: Sell these stocks TODAY:")
        for r in urgent_sell:
            td = r.get('technical_data', {})
            safe_status = " [SUSPENDED!]" if not td.get('is_safe', True) else ""
            print(f"   - {r['ticker']} - {r['shares']} shares{safe_status}")
        print("   -> Open your broker app and place sell orders NOW")

    if consider_sell:
        print("\n2. REVIEW: Check these stocks carefully:")
        for r in consider_sell:
            print(f"   - {r['ticker']} - Currently {r['profit_pct']:+.1f}%")
        print("   -> Decide if you want to take profits or keep holding")

    if hold:
        print("\n3. HOLD: These stocks are fine, keep them:")
        for r in hold:
            td = r.get('technical_data', {})
            print(f"   - {r['ticker']} - Currently {r['profit_pct']:+.1f}% (Stop-Loss: IDR {td.get('stop_loss', 0):,.0f})")

    if not urgent_sell and not consider_sell:
        print("\nGood news! No action needed right now.")
        print("   All your positions are looking good. Keep holding!")

    # Market context
    print("\n" + "="*80)
    print(f"MARKET CONTEXT: IHSG is {mkt.get('status', 'UNKNOWN')} (5d: {mkt.get('change_5d', 0):+.1f}%)")
    if mkt['status'] in ('BEARISH', 'MODERATE_BEAR'):
        print("   The overall market is weak. Consider tighter stop-losses.")
        print("   Reduce position sizes. Cash is a valid position.")

    print("\n" + "="*80)
    print("REMEMBER:")
    print("   - Check if a stock is SUSPENDED before placing orders")
    print("   - Use stop-loss orders (ATR-based levels shown above)")
    print("   - If ADX < 20, the stock has no trend - be cautious")
    print("   - If market is BEARISH, all stocks are riskier")
    print("   - Don't panic - stick to your strategy")
    print("="*80 + "\n")


if __name__ == '__main__':
    main()
