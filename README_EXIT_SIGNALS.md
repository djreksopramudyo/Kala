# 🎯 Exit Signal System - Complete Guide

## 📌 Overview

Your `kala_daily_trader.py` now has **TWO main functions**:

1. **`live_trading_dashboard()`** - Find new stocks to BUY
2. **`monitor_portfolio()`** - Check when to SELL stocks you own ⭐ NEW!

---

## 🔴 When Should You SELL?

### 9 Exit Signals (Automated)

| # | Signal | Urgency | What It Means |
|---|--------|---------|---------------|
| 1 | **Stop-Loss (-5%)** | 🔴 URGENT | Position down 5%, cut losses NOW |
| 2 | **RSI Panic (< 25)** | 🔴 URGENT | Extreme selling, exit before crash |
| 3 | **Death Cross** | 🔴 URGENT | Trend reversed, sell immediately |
| 4 | **BB Breakdown** | 🔴 URGENT | Price collapsed below support |
| 5 | **Target Profit (+15%)** | 🟡 CONSIDER | Day trading target reached, take profits |
| 6 | **RSI Overbought (>75)** | 🟡 CONSIDER | Too high, likely to reverse |
| 7 | **MACD Bearish** | 🟡 CONSIDER | Momentum turning negative |
| 8 | **Volume Spike (Down)** | 🟡 CONSIDER | Smart money might be selling |
| 9 | **Tech Score < 35** | 🟡 CONSIDER | Overall weakness detected |

---

## 💻 Quick Start - 3 Ways to Use

### Method 1: Monitor Your Portfolio (Recommended)

**Step 1**: Edit `kala_daily_trader.py`

Find this section around line 1350:

```python
# MODE 2: MONITOR YOUR POSITIONS (Check when to sell stocks you own)
# Replace with your actual positions:
my_positions = [
    {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000},
    {'ticker': 'TLKM.JK', 'entry_price': 3500, 'shares': 500},
    {'ticker': 'ASII.JK', 'entry_price': 4800, 'shares': 200},
]
monitor_portfolio(my_positions)
```

**Step 2**: Uncomment those lines (remove the `#`)

**Step 3**: Replace with your actual positions:
- `ticker`: Stock code (e.g., 'BBRI.JK')
- `entry_price`: Price you bought at
- `shares`: Number of shares you own

**Step 4**: Comment out the original dashboard:

```python
# signals = live_trading_dashboard()  # Add # to disable this
```

**Step 5**: Run the script:

```bash
python kala_daily_trader.py
```

---

### Method 2: Use the Example Script

```bash
# Edit the positions in the file first
python example_monitor_positions.py
```

This gives you a clean, focused view of just your positions.

---

### Method 3: Interactive Python Shell

```python
from kala_daily_trader import check_exit_signals

# Check if you should sell BBRI that you bought at 5200
result = check_exit_signals('BBRI.JK', entry_price=5200)

if result['exit_signal']:
    print(f"SELL! Urgency: {result['urgency']}")
    print(f"P/L: {result['profit_pct']:+.2f}%")
    for reason in result['reasons']:
        print(f"  - {reason}")
else:
    print("HOLD - No exit signals")
```

---

## 📊 Example Output

```
================================================================================
PORTFOLIO EXIT MONITOR - Check positions for sell signals
================================================================================
Generated: 2026-02-04 14:30:00
Monitoring 3 positions
================================================================================

Checking BBRI.JK... ✓ (+2.5%)
Checking TLKM.JK... ✓ (-6.2%)
Checking ASII.JK... ✓ (+12.3%)

================================================================================
EXIT SIGNAL SUMMARY
================================================================================
Ticker       Entry      Current    P/L %      P/L IDR         Status          Action              
----------------------------------------------------------------------------------------------------
BBRI.JK      5,200      5,330      +2.50%     +130,000        🟢 HOLD         No exit signal
TLKM.JK      3,500      3,283      -6.20%     -108,500        🔴 EXIT NOW     STOP-LOSS HIT: Down -6.2%
ASII.JK      4,800      5,390      +12.29%    +118,000        🟡 CONSIDER     Target profit near +15%

================================================================================
🔴 URGENT EXITS - SELL IMMEDIATELY
================================================================================

TLKM.JK - SELL 500 shares @ IDR 3,283
   Entry: IDR 3,500 | P/L: -6.20% (IDR -108,500)
   REASONS:
      • STOP-LOSS HIT: Down -6.2% (limit: -5%)
      • DEATH CROSS: Trend reversed (Fast SMA < Slow SMA)
      • MACD BEARISH: Histogram -0.0523

================================================================================
🟡 CONSIDER EXITING - Review these positions
================================================================================

ASII.JK - Consider selling 200 shares
   Entry: IDR 4,800 | Current: IDR 5,390
   P/L: +12.29% (IDR +118,000)
   REASONS:
      • Near target profit of +15%
      • RSI showing strength at 68.5

================================================================================
🟢 HOLD - These positions look good
================================================================================
   BBRI.JK: +2.50% (IDR +130,000)

================================================================================
```

---

## 🎮 Daily Trading Workflow

### 1. Morning Routine (Before Market - 8:00 AM)

```bash
# Find new stocks to buy today
python kala_daily_trader.py
# (Uses default: live_trading_dashboard)
```

**Output**: List of stocks with BUY signals
**Action**: Pick top 3-5 to buy when market opens

---

### 2. After Buying (During Market - 9:00 AM onwards)

**Set Stop-Loss Immediately!**

For each position you buy:
- Entry: 5000
- Stop-Loss: 4750 (-5%)

Place a stop-loss order with your broker right after buying!

---

### 3. End of Day Check (After Market - 4:30 PM)

```bash
# Check if you should sell any positions
python example_monitor_positions.py
```

**Output**: Exit signals for your holdings
**Action**:
- 🔴 URGENT → Prepare to sell tomorrow morning
- 🟡 CONSIDER → Review and decide
- 🟢 HOLD → Keep the position

---

### 4. Next Morning (Before Market - 8:00 AM)

Execute any URGENT sell orders from yesterday's analysis.

---

## ⚙️ Customization Options

### Adjust Stop-Loss Percentage

Edit `check_exit_signals()` function:

```python
# Conservative (tight stop-loss)
if profit_pct <= -3.0:  # Sell at -3%

# Default
if profit_pct <= -5.0:  # Sell at -5%

# Aggressive (wide stop-loss)
if profit_pct <= -7.0:  # Sell at -7%
```

**Recommendation for beginners**: Start with -3%

---

### Adjust Profit Target

```python
# Conservative (take profits early)
if profit_pct >= 10.0:  # Sell at +10%

# Default
if profit_pct >= 15.0:  # Sell at +15%

# Aggressive (let profits run)
if profit_pct >= 20.0:  # Sell at +20%
```

**Recommendation**: Start with +10% for day trading

---

## 🧮 Position Sizing Calculator

**Rule**: Never risk more than 2-3% of capital per trade

```python
Capital = 100,000,000 IDR
Risk per trade = 2% = 2,000,000 IDR
Stop-loss = 5%

Maximum position size = Risk / Stop-loss %
                      = 2,000,000 / 0.05
                      = 40,000,000 IDR

If stock price = 5,000 IDR:
Max shares = 40,000,000 / 5,000 = 8,000 shares
```

This way, even if stop-loss hits, you only lose 2% (manageable!).

---

## ⚠️ Important Warnings

### 1. Always Check News!
Technical signals can be **instantly invalidated** by:
- Corporate announcements
- Economic data
- Political events
- Natural disasters

**Before selling**: Quick Google search for recent news!

### 2. Don't Ignore Stop-Loss
The #1 reason traders fail: **Not cutting losses**

If stop-loss triggers → SELL, no excuses!

### 3. Take Profits When Advised
Don't get greedy. If target hit → consider selling.

*"Bulls make money, bears make money, pigs get slaughtered"*

### 4. Max 3-5 Positions
Don't over-diversify in day trading. Stay focused.

### 5. This is HIGH RISK
Day trading is **NOT** suitable for:
- Beginners (learn first!)
- People who panic easily
- Those who can't afford losses

**Start with paper trading** (fake money) first!

---

## 📚 Files Created

1. **`kala_daily_trader.py`** - Main script (updated with exit functions)
2. **`EXIT_STRATEGY_GUIDE.md`** - Detailed exit strategy explanation
3. **`example_monitor_positions.py`** - Example script for monitoring
4. **`README_EXIT_SIGNALS.md`** - This file (complete guide)

---

## 🆘 Troubleshooting

### Problem: "Cannot fetch data"
**Solution**: Check internet connection, yfinance might be rate-limited

### Problem: Exit signals always say HOLD
**Solution**: Your entry price might be too close to current price, or position is performing well!

### Problem: Too many exit signals
**Solution**: You might have set stop-loss too tight, adjust to -5% or -7%

---

## 📖 Further Learning

**Books**:
- "The Disciplined Trader" by Mark Douglas
- "Reminiscences of a Stock Operator" by Edwin Lefèvre

**Key Concepts to Study**:
- Risk management
- Position sizing
- Psychology of trading
- Technical analysis patterns

---

## ✅ Checklist - Before You Start

- [ ] I understand all 9 exit signals
- [ ] I've edited `my_positions` with real data
- [ ] I have set stop-loss orders with my broker
- [ ] I will only risk 2-3% per trade
- [ ] I will check news before selling
- [ ] I understand this is high-risk trading
- [ ] I'm starting with small position sizes

---

## 🎯 Quick Reference Card

**SELL IMMEDIATELY IF**:
- ❌ Stop-loss hit (-5%)
- ❌ Death cross (SMA)
- ❌ RSI < 25
- ❌ BB breakdown

**CONSIDER SELLING IF**:
- ⚠️ Profit target (+15%)
- ⚠️ RSI > 75 + profit
- ⚠️ MACD bearish
- ⚠️ Tech score < 35

**KEEP HOLDING IF**:
- ✅ Tech score > 50
- ✅ Trend intact
- ✅ RSI 30-70
- ✅ Profit or small loss

---

**Remember**: *"Plan your trade, trade your plan."*

Good luck and trade safely! 🚀
