"""
CHECK WATCHLIST - Fair-value dip alerts
=======================================

The other half of the value loop: `kala_fundamental_only.py` saves its
BUY-grade names (with intrinsic values) into `watchlist.json`; this script
checks today's prices and tells you which of those researched names are NOW
trading at a real discount to your saved fair value.

Usage:
    python check_watchlist.py            # alert at >= 15% discount (default)
    python check_watchlist.py 20         # alert at >= 20% discount

A dip alert is a signal to RE-CHECK the thesis (news first!), not a blind buy.
"""

import sys

import yfinance as yf

from kala.watchlist import WatchlistStore

WATCHLIST_PATH = "watchlist.json"
DEFAULT_MIN_DISCOUNT = 15.0


def fetch_prices(tickers):
    """Last close for each ticker; missing/suspended names are skipped."""
    prices = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period="5d")
            if len(h):
                prices[t] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return prices


def main():
    min_disc = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MIN_DISCOUNT

    wl = WatchlistStore.load(WATCHLIST_PATH)
    if len(wl) == 0:
        print("Watchlist is empty.")
        print("Run kala_fundamental_only.py first — its BUY-grade names")
        print(f"are saved to {WATCHLIST_PATH} automatically.")
        return

    print("=" * 70)
    print(f"WATCHLIST CHECK — {len(wl)} researched names, alerting at "
          f">= {min_disc:.0f}% below fair value")
    print("=" * 70)

    tickers = [item.ticker for item in wl]
    print(f"Fetching prices for {len(tickers)} tickers...")
    prices = fetch_prices(tickers)
    missing = [t for t in tickers if t not in prices]
    if missing:
        print(f"(no price for: {', '.join(missing)} — skipped)")

    alerts = wl.alerts(prices, min_discount_pct=min_disc)

    if not alerts:
        print("\nNo dip alerts today. Your researched names are all trading")
        print("above your discount threshold. Patience is the position.")
    else:
        print(f"\n{len(alerts)} DIP ALERT(S) — deepest discount first:\n")
        for a in alerts:
            print(f"  {a['ticker']}")
            print(f"     price IDR {a['price']:>10,.0f}  vs  fair IDR {a['fair_value']:>10,.0f}"
                  f"   -> {a['discount_pct']:.0f}% discount")
            if a.get("thesis"):
                print(f"     thesis: {a['thesis']}  (added {a['added']})")
            print()
        print("Before buying: re-check the news. A big discount can mean a")
        print("bargain OR a broken thesis — the price alone can't tell you which.")

    # context: names on the list but not (yet) at a discount
    quiet = [i for i in wl if i.ticker in prices
             and i.discount_pct(prices[i.ticker]) < min_disc]
    if quiet:
        print("-" * 70)
        print("Still waiting (below threshold):")
        for i in sorted(quiet, key=lambda x: -x.discount_pct(prices[x.ticker])):
            d = i.discount_pct(prices[i.ticker])
            print(f"  {i.ticker:<12} {d:+.0f}% vs fair value")


if __name__ == "__main__":
    main()
