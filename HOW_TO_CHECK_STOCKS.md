# How to Check Your Stocks (Super Simple)

## 📝 Step 1: Edit Your Positions

Open `check_my_stocks.py` and find this section (around line 20):

```python
YOUR_POSITIONS = [
    # Replace these examples with YOUR stocks:
    {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000},
    {'ticker': 'TLKM.JK', 'entry_price': 3500, 'shares': 500},
]
```

**Change to your actual stocks!**

For each stock you own, add a line like:
```python
{'ticker': 'STOCK_CODE.JK', 'entry_price': PRICE_YOU_PAID, 'shares': HOW_MANY},
```

### Example:

If you bought:
- 1000 shares of Bank BRI at IDR 5,200
- 500 shares of Telkom at IDR 3,500
- 200 shares of Astra at IDR 4,800

Your file should look like:

```python
YOUR_POSITIONS = [
    {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000},
    {'ticker': 'TLKM.JK', 'entry_price': 3500, 'shares': 500},
    {'ticker': 'ASII.JK', 'entry_price': 4800, 'shares': 200},
]
```

---

## 🚀 Step 2: Run the Script

Open terminal/command prompt and run:

```bash
python check_my_stocks.py
```

**That's it!**

---

## 📊 Step 3: Read the Output

The script will tell you exactly what to do:

### 🔴 SELL THESE STOCKS NOW
- These need to be sold TODAY
- Stop-loss hit or major technical breakdown
- **Action**: Open your broker app and sell immediately

### 🟡 CONSIDER SELLING THESE
- These might be ready to take profits
- Or showing some weakness
- **Action**: Review carefully and decide

### 🟢 KEEP HOLDING THESE
- These stocks are fine
- No sell signals
- **Action**: Do nothing, keep them!

---

## 📋 Example Output

```
================================================================================
📊 CHECKING YOUR STOCKS
================================================================================
Time: 2026-02-04 14:30:00
Total positions: 3
================================================================================

[1/3] Analyzing BBRI.JK... ✓ (+2.5%)
[2/3] Analyzing TLKM.JK... ✓ (-6.2%)
[3/3] Analyzing ASII.JK... ✓ (+12.3%)

================================================================================
📋 WHAT YOU NEED TO DO
================================================================================

🔴 SELL THESE STOCKS NOW (URGENT!)
--------------------------------------------------------------------------------

TLKM.JK
   Buy Price:     IDR      3,500
   Current Price: IDR      3,283
   Profit/Loss:   IDR   -108,500 (-6.2%)
   Shares:              500 shares

   WHY SELL:
   • STOP-LOSS HIT: Down -6.2% (limit: -5%)
   • DEATH CROSS: Trend reversed (Fast SMA < Slow SMA)

--------------------------------------------------------------------------------
🟡 CONSIDER SELLING THESE
--------------------------------------------------------------------------------

ASII.JK
   Buy Price:     IDR      4,800
   Current Price: IDR      5,390
   Profit/Loss:   IDR   +118,000 (+12.3%)
   Shares:              200 shares

   WHY CONSIDER:
   • Near target profit of +15%

--------------------------------------------------------------------------------
🟢 KEEP HOLDING THESE (LOOKING GOOD)
--------------------------------------------------------------------------------

BBRI.JK
   Buy Price:     IDR      5,200
   Current Price: IDR      5,330
   Profit/Loss:   IDR   +130,000 (+2.5%)
   Shares:            1,000 shares
   Status:        No sell signals - keep holding ✓

================================================================================
📊 SUMMARY
================================================================================

Total Portfolio:
   Cost Basis:    IDR       7,760,000
   Current Value: IDR       7,799,500
   Profit/Loss:   IDR         +39,500 (+0.5%)

Action Items:
   🔴 Sell Now:      1 stocks
   🟡 Consider:      1 stocks
   🟢 Hold:          1 stocks

================================================================================
💡 NEXT STEPS
================================================================================

1. ❗ URGENT: Sell these stocks TODAY:
   • TLKM.JK - 500 shares
   → Open your broker app and place sell orders NOW

2. ⚠️  REVIEW: Check these stocks carefully:
   • ASII.JK - Currently +12.3%
   → Decide if you want to take profits or keep holding

3. ✅ HOLD: These stocks are fine, keep them:
   • BBRI.JK - Currently +2.5%

================================================================================
⚠️  REMEMBER:
   • Always check news before selling
   • Use stop-loss orders to protect yourself
   • Don't panic - stick to your strategy
================================================================================
```

---

## ⏰ When to Run This

### Daily Routine:

**End of trading day (4:30 PM)**
```bash
python check_my_stocks.py
```

This tells you what to do tomorrow morning.

---

## ❓ What If Nothing Shows Up?

If you see:
```
✗ Failed to fetch data
```

**Possible reasons:**
1. Wrong stock ticker (check it's correct, e.g., `BBRI.JK` not `BBRI`)
2. No internet connection
3. Stock market is closed (data not updating)
4. yfinance is rate-limited (wait 5 minutes and try again)

---

## 🔧 Quick Fixes

### "No positions found"
→ You forgot to edit `YOUR_POSITIONS` at the top of the file

### "Could not analyze any positions"
→ Check your internet connection

### "Import error"
→ Make sure `kala_daily_trader.py` is in the same folder

---

## 🎯 That's It!

This is the ONLY file you need to run to check your stocks.

1. Edit your positions (once)
2. Run the script (daily)
3. Follow the instructions (🔴 sell now, 🟡 consider, 🟢 hold)

**Simple!**
