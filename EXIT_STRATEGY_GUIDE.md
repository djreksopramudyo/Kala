# Exit Strategy Guide - Day Trading Edition

## 🎯 The Golden Rule
**"Cutting losses quickly and letting profits run is how day traders survive."**

## 📊 When to SELL (Exit Signals)

### 🔴 URGENT - Sell Immediately

1. **Stop-Loss Hit (-5%)**
   - Your position is down 5% from entry
   - **Action**: SELL NOW to prevent bigger losses
   - **Why**: Small losses are manageable, big losses destroy accounts

2. **Death Cross**
   - Fast SMA (10) crosses BELOW Slow SMA (50)
   - **Action**: SELL - the uptrend is over
   - **Why**: This signals trend reversal

3. **RSI Panic Zone (< 25)**
   - Extreme panic selling happening
   - **Action**: SELL before it gets worse
   - **Why**: Could drop much further

4. **Bollinger Band Breakdown**
   - Price closes below lower Bollinger Band
   - **Action**: SELL - breakdown confirmed
   - **Why**: Strong sell signal, more downside likely

### 🟡 CONSIDER EXITING - Review Carefully

5. **Target Profit (+15%)**
   - Your position is up 15%
   - **Action**: Consider taking profits
   - **Why**: Day trading typical target reached

6. **RSI Overbought (> 75) + In Profit**
   - Stock is very overbought and you're up
   - **Action**: Consider selling before reversal
   - **Why**: What goes up, must come down

7. **MACD Bearish Crossover**
   - MACD line crosses below signal line
   - **Action**: Consider exiting
   - **Why**: Momentum is turning negative

8. **Volume Spike on Red Day**
   - Big volume + price down > 2%
   - **Action**: Consider selling
   - **Why**: Smart money might be exiting

9. **Technical Score < 35**
   - Overall technical strength collapsed
   - **Action**: Consider exiting
   - **Why**: Multiple indicators turned bearish

### 🟢 HOLD - Keep the Position

- Technical Score > 50
- Trend still intact (Fast SMA > Slow SMA)
- RSI between 30-70 (healthy)
- Making profit or small loss only
- Volume normal

---

## 💻 How to Use the Exit Monitor

### Method 1: Monitor Your Portfolio

Edit `kala_daily_trader.py` and uncomment this section:

```python
# MODE 2: MONITOR YOUR POSITIONS
my_positions = [
    {'ticker': 'BBRI.JK', 'entry_price': 5200, 'shares': 1000},
    {'ticker': 'TLKM.JK', 'entry_price': 3500, 'shares': 500},
    {'ticker': 'ASII.JK', 'entry_price': 4800, 'shares': 200},
]
monitor_portfolio(my_positions)
```

Then run:
```bash
python kala_daily_trader.py
```

### Method 2: Check Single Stock

```python
# MODE 3: CHECK SINGLE STOCK EXIT SIGNAL
exit_signal = check_exit_signals('BBRI.JK', entry_price=5200)
if exit_signal['exit_signal']:
    print(f"SELL SIGNAL for {exit_signal['ticker']}!")
    print(f"P/L: {exit_signal['profit_pct']:+.2f}%")
    for reason in exit_signal['reasons']:
        print(f"• {reason}")
```

---

## 📋 Daily Trading Routine

### Morning (Before Market Opens - 8:30 AM)
1. Run `live_trading_dashboard()` - Find stocks to BUY today
2. Review signals, pick top 3-5 opportunities
3. Set buy orders with limit prices

### During Market Hours (9:00 AM - 4:00 PM)
1. Monitor positions every 30 minutes
2. Set stop-loss orders immediately after buying
3. Watch for URGENT exit signals
4. Don't panic - stick to your rules!

### End of Day (After Market Closes - 4:15 PM)
1. Run `monitor_portfolio()` with your positions
2. Review any exit signals for tomorrow
3. Update your trading journal
4. Calculate P/L for the day

---

## ⚙️ Adjust Stop-Loss Based on Risk Tolerance

In the code, you can change the stop-loss percentage:

```python
# Conservative trader (tighter stop-loss)
if profit_pct <= -3.0:  # Exit at -3%
    exit_signal = True
    
# Moderate trader (default)
if profit_pct <= -5.0:  # Exit at -5%
    exit_signal = True
    
# Aggressive trader (wider stop-loss)
if profit_pct <= -7.0:  # Exit at -7%
    exit_signal = True
```

**Recommendation**: Start with -3% if you're new to day trading!

---

## 🎓 Advanced: Trailing Stop-Loss

Once your position is up 10%+, move your stop-loss to **break-even** or higher:

```
Entry: 5000
Current: 5500 (+10%)
New Stop-Loss: 5000 (break-even) or 5250 (+5%)
```

This way you **lock in profits** and can't lose money even if it reverses!

---

## ⚠️ Critical Reminders

1. **ALWAYS use stop-losses** - No exceptions!
2. **Never average down** on losing trades
3. **Take profits when signals say so** - Don't get greedy
4. **News can invalidate technical signals** - Be ready to exit
5. **Max 3-5 positions at once** - Stay focused
6. **Never risk more than 2-3% of capital per trade**

---

## 📊 Exit Signal Priority

If multiple signals trigger, follow this order:

1. **URGENT signals** → Sell immediately
2. **CONSIDER signals** + Loss → Sell (cut losses)
3. **CONSIDER signals** + Big Profit (>10%) → Take profits
4. **CONSIDER signals** + Small Profit → Review, maybe hold

---

## 🧮 Position Sizing Example

Capital: IDR 100,000,000
Risk per trade: 2% = IDR 2,000,000
Stop-loss: -5%

```
Max loss per position = IDR 2,000,000
Stop-loss = 5%
Position size = 2,000,000 / 0.05 = IDR 40,000,000

If stock is IDR 5,000/share:
Shares = 40,000,000 / 5,000 = 8,000 shares
```

This way, even if stop-loss hits, you only lose 2% of capital!

---

## 📚 Further Reading

- **"Reminiscences of a Stock Operator"** by Edwin Lefèvre
- **"Market Wizards"** by Jack Schwager
- **"The Disciplined Trader"** by Mark Douglas

**Key Lesson**: *"It's not about being right. It's about making money."*

Cut losses fast. Let profits run. That's the secret.
