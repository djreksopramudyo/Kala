# Deployment checklist — from research to an actually-funded portfolio

Everything else in this repo answers *"what should I do?"*. This file is the
short, boring list of what has to physically happen for any of it to matter,
in order, with the things that quietly go wrong called out.

**Why this exists**: after ~20 studies, the research was complete but the
portfolio was not funded, `/rebalance` had never been run against real
holdings, and it was unclear whether the VPS timers written for this project
had ever actually been installed. Analysis that never becomes a position is
just a hobby. This is the gap-closing list.

> Nothing here is financial advice. It is an operational checklist for
> executing a plan **you** have decided on. Every step is reversible except
> the ones that spend money — those are marked.

**Run `python preflight.py` first.** It automates the mechanical parts of
sections 1-2 below (leaked token, mistyped config keys, malformed positions,
stale ISSI list, uninstalled timers) and exits non-zero if anything failed.
Run it *on the machine that runs the bot* — checking your laptop tells you
nothing about your VPS. It is read-only: it never writes, sends or spends.
The judgement calls — is the plan still the plan, has the money moved — are
still yours and are not automatable.

---

## 0. Before anything: confirm the plan is still the plan

The evidence base has moved several times, including one reversal. Re-read the
"Results" sections of `PROJECT_STATUS.md` before funding anything, and check
these are still what you believe:

- [ ] Target mix in `runner_config.json` matches what you actually intend to hold
- [ ] Every ticker in it is still sharia-compliant (ISSI is revised ~May and ~Nov;
      `kala/universe.py`'s `UNIVERSE_UPDATED` tells you how stale the list is)
- [ ] You have read the survivorship caveat on the core-satellite result
      (`survivorship_study.py`) and are not sizing the sleeve on a hindsight artifact

## 1. Secrets hygiene (do this first — it is the only irreversible-if-skipped step)

- [ ] Telegram bot token **rotated** via @BotFather `/revoke`. It has appeared
      in plaintext in `runner_config.json` across exports of this project.
- [ ] New token lives ONLY in `/etc/kala/telegram.env` (mode 600, root-owned),
      never in `runner_config.json` — see `DEPLOY_VPS.md` step 6a
- [ ] `runner_config.json` on the server has `telegram_token`/`telegram_chat_id`
      blank or absent

## 2. Verify the VPS is actually running what you think

Written ≠ installed. Check, don't assume:

```bash
systemctl status kala-bot.service            # always-on Telegram bot
systemctl list-timers kala-daily.timer       # daily cycle, 17:00 WIB Mon-Sat
systemctl list-timers kala-fundamentals.timer  # monthly archive (the unblocking one)
```

- [ ] All three exist and show a sensible next-fire time
- [ ] If `kala-fundamentals.timer` is missing, install it (`DEPLOY_VPS.md` step 7).
      **This one matters for the future**: the fundamental-value factor is
      blocked purely on this archive accumulating calendar time. Every month it
      does not run is a month that lead stays blocked.
- [ ] `journalctl -u kala-daily.service -n 50` shows real runs, not silent failures

## 3. Fund and record the starting position — the money step

**This step spends money and is not reversible by software.**

1. [ ] Transfer capital to Stockbit
2. [ ] Decide deployment schedule. The evidence (`deployment_study.py`) for
       *this* basket: lump sum won 62% of historical start dates, but only 54%
       once idle cash earns a realistic ~4%/yr — close to a coin flip, with DCA
       holding a ~3pp better *typical* drawdown. Neither dominates; it is a
       behavioural choice about what keeps you invested through a bad first year.
3. [ ] Buy according to `target_allocation` (lot-aware: IDX trades 100-share lots)
4. [ ] Record **every** fill in the bot with `/buy TICKER shares price` —
       including the date if backdating. The bot's state is the only thing that
       makes `/report`, `/rebalance` and TWR meaningful; an unrecorded fill
       silently corrupts all three.
5. [ ] `/status` — confirm the recorded positions match the broker exactly

## 4. First real `/rebalance`

- [ ] Run `/rebalance` and read it as a *maintenance* suggestion, not a signal
- [ ] Expect it to be a no-op right after funding (you just bought to target)
- [ ] It is **read-only** — nothing executes. You trade in Stockbit, then record
      the result with `/buy` / `/sell`, same as step 3.4

## 5. The parts that are manual by necessity

- [ ] **Sukuk (15%)**: no yfinance ticker. Buy via e-SBN during an offering
      window, then record it so allocation drift stays honest
- [ ] **Gold**: hold in cash until the BEI sharia gold ETF lists (expected
      Aug 2026), then buy and record
- [ ] Note both of these mean `/report`'s allocation view is only as accurate as
      your manual recording

## 6. Ongoing rhythm (deliberately dull)

| cadence | action |
|---|---|
| daily | nothing required — the bot's daily cycle runs itself |
| monthly | glance at `/report`; confirm the fundamentals timer fired |
| quarterly | `/rebalance`, act only if drift is outside your band |
| ~May & ~Nov | refresh the ISSI list; re-check holdings are still compliant |
| yearly | re-read `PROJECT_STATUS.md`; revisit the time-blocked leads |

**The most common failure mode from here is not a bad trade — it is
forgetting to record one.** The second most common is quietly abandoning the
plan during a drawdown; the studies say the equity sleeve alone drew down
~-49% in the tested window, and that the multi-asset mix (sukuk/cash) is what
actually softens it, not any signal or weighting trick.

## 7. What would justify changing the plan

Not a bad quarter. Specifically:

- The fundamental archive matures (~a year of monthly snapshots) → the
  value/quality factor becomes testable for the first time
- The Ramadan effect accumulates enough independent years to stop being
  underpowered
- A structural change: a new sharia ETF, a broker that opens international
  access, a genuinely different data source

Anything else is noise, and this project has ~20 studies' worth of evidence
that chasing it costs money.
