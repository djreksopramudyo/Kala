"""
News scraping + sentiment — single owner.

Ported verbatim-in-behavior from ``kala_engine.py`` (which now delegates here),
so every entry point — the daily scheduler, the Telegram bot, and the legacy
dashboard — reads the SAME sources and computes the SAME sentiment number:
IDX official announcements, Yahoo Finance headlines, and five Indonesian
media outlets, translated to English and scored with TextBlob polarity.

ADVISORY ONLY — read this before wiring it anywhere new
--------------------------------------------------------
Sentiment must never feed the trading signal. There is no point-in-time
archive of what these scrapers would have returned on any historical date,
so a sentiment-weighted signal is UNBACKTESTABLE — it can never clear the
out-of-sample validation bar every other input to the live signal had to
clear. Consumers show it next to a recommendation; they do not add it to
the score. (The legacy ``kala_engine.py`` dashboard still blends it into its
own display-only composite — one reason that dashboard is not the live
signal path.)

Degradation contract: every function here returns something usable when a
website changes layout, the network is down, or the optional dependencies
(beautifulsoup4 / textblob / deep-translator) aren't installed — a neutral
score and an explicit "unavailable" label, never an exception. The core
package must import fine without any of those extras, hence the lazy
imports inside functions.
"""

from __future__ import annotations

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

NEUTRAL = (50.0, 0, "DEGRADED: sentiment source unavailable")


def _soup(html: str, parser: str):
    """BeautifulSoup, or None if bs4 (or the lxml parser) is unavailable."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, parser)
    except Exception:
        return None


def _polarity(text: str):
    """TextBlob polarity in [-1, 1], or None if textblob is unavailable."""
    try:
        from textblob import TextBlob
        return float(TextBlob(text).sentiment.polarity)
    except Exception:
        return None


def scrape_idx_announcements(ticker: str) -> list[tuple]:
    """Official IDX disclosures/corporate actions mentioning the stock.
    Returns up to 5 (text, source, date) tuples; [] on any failure."""
    announcements = []
    stock_code = ticker.replace(".JK", "")

    try:
        idx_url = (f"https://www.idx.co.id/en/listed-companies/company-information/"
                   f"?kodeEmiten={stock_code}")
        response = requests.get(idx_url, headers=_HEADERS, timeout=8)
        if response.status_code == 200:
            soup = _soup(response.text, "lxml")
            for row in (soup.find_all("tr", limit=5) if soup else []):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    text = " ".join(c.get_text(strip=True) for c in cells)
                    if stock_code in text.upper() and len(text) > 20:
                        announcements.append((text, "IDX Official", "Recent"))
    except Exception:
        pass

    try:
        news_url = "https://www.idx.co.id/en/news-announcement/news/"
        response = requests.get(news_url, headers=_HEADERS, timeout=8)
        if response.status_code == 200:
            soup = _soup(response.text, "lxml")
            for item in (soup.find_all(["h3", "h4", "h5"], limit=10) if soup else []):
                title = item.get_text(strip=True)
                if stock_code in title.upper() and len(title) > 15:
                    announcements.append((title, "IDX News", "Recent"))
    except Exception:
        pass

    try:
        ca_url = "https://www.idx.co.id/en/listed-companies/corporate-actions/"
        response = requests.get(ca_url, headers=_HEADERS, timeout=8)
        if response.status_code == 200:
            soup = _soup(response.text, "lxml")
            for table in (soup.find_all("table", limit=3) if soup else []):
                for row in table.find_all("tr"):
                    if stock_code in row.get_text(strip=True):
                        cells = row.find_all("td")
                        if len(cells) >= 3:
                            action = " - ".join(c.get_text(strip=True) for c in cells[:3])
                            if len(action) > 10:
                                announcements.append((action, "IDX Corporate Action", "Recent"))
                                break
    except Exception:
        pass

    return announcements[:5]


def scrape_indonesian_news(ticker: str, company_name: str | None = None) -> list[tuple]:
    """Headlines mentioning the stock from five Indonesian outlets.
    Returns (headline, source) tuples; [] on any failure."""
    news_items = []
    stock_code = ticker.replace(".JK", "")

    sources = [
        (f"https://www.cnbcindonesia.com/search?query={stock_code}&result_type=latest",
         "html.parser", "h2", None, 3, "CNBC Indonesia"),
        (f"https://www.kontan.co.id/search/?search={stock_code}&Button_search=",
         "html.parser", "h1", None, 3, "Kontan"),
        (f"https://search.bisnis.com/?q={stock_code}",
         "html.parser", "h2", None, 3, "Bisnis Indonesia"),
        (f"https://www.idxchannel.com/search?search={stock_code}",
         "lxml", ["h2", "h3", "h4"], None, 4, "IDX Channel"),
        (f"https://www.detik.com/search/searchall?query={stock_code}",
         "html.parser", "h3", "media__title", 3, "Detik Finance"),
    ]
    for url, parser, tags, cls, limit, label in sources:
        try:
            response = requests.get(url, headers=_HEADERS, timeout=5)
            if response.status_code != 200:
                continue
            soup = _soup(response.text, parser)
            if soup is None:
                continue
            found = (soup.find_all(tags, class_=cls, limit=limit) if cls
                     else soup.find_all(tags, limit=limit))
            for article in found:
                title = article.get_text(strip=True)
                if not title:
                    continue
                if label == "IDX Channel":
                    if len(title) > 15 and (stock_code in title.upper()
                                            or "saham" in title.lower()):
                        news_items.append((title, label))
                elif len(title) > 10:
                    news_items.append((title, label))
        except Exception:
            continue

    return news_items


def translate_to_english(text: str) -> str:
    """Indonesian -> English for sentiment scoring; the original text on any
    failure (including deep-translator not being installed)."""
    try:
        if any(w in text.lower() for w in ["the", "and", "to", "of", "in", "for"]):
            return text
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="id", target="en").translate(text)
    except Exception:
        return text


def get_news_sentiment(ticker: str) -> tuple:
    """(sentiment_score 0-100, article_count, description).

    Same contract the legacy dashboard always had. (50, 0, ...) whenever
    nothing could be fetched or scored — neutral, clearly labelled, never an
    exception.
    """
    all_headlines, all_sentiments, sources_used = [], [], []

    try:
        for announcement, source, _date in scrape_idx_announcements(ticker)[:2]:
            polarity = _polarity(translate_to_english(announcement))
            if polarity is None:
                continue
            all_headlines.append(f"{announcement[:60]}... ({source})")
            all_sentiments.append(polarity * 1.2)   # official news weighs more
            sources_used.append(source)

        try:
            import yfinance as yf
            for article in (yf.Ticker(ticker).news or [])[:3]:
                title = article.get("title", "")
                polarity = _polarity(title) if title else None
                if polarity is None:
                    continue
                all_headlines.append(title)
                all_sentiments.append(polarity)
                sources_used.append("Yahoo Finance")
        except Exception:
            pass

        for headline, source in scrape_indonesian_news(ticker)[:3]:
            polarity = _polarity(translate_to_english(headline))
            if polarity is None:
                continue
            all_headlines.append(f"{headline} ({source})")
            all_sentiments.append(polarity)
            sources_used.append(source)

        if not all_sentiments:
            return 50, 0, "No recent news found"

        avg = sum(all_sentiments) / len(all_sentiments)
        score = ((avg + 1.0) / 2.0) * 100.0
        label = "POSITIVE" if avg > 0.2 else "NEGATIVE" if avg < -0.2 else "NEUTRAL"
        srcs = ", ".join(sorted(set(sources_used)))
        top = all_headlines[0][:60] if all_headlines else "N/A"
        return score, len(all_headlines), (
            f"{label} ({len(all_headlines)} articles from {srcs}): {top}...")
    except Exception:
        return NEUTRAL


def news_brief(tickers: list[str], max_tickers: int = 6) -> list[str]:
    """One compact advisory line per ticker, for the daily Telegram message
    and /scan. Skips tickers with no scoreable news so the section stays
    short. NEVER feeds a signal — display only."""
    lines = []
    for t in tickers[:max_tickers]:
        try:
            score, n, desc = get_news_sentiment(t)
        except Exception:
            continue
        if n == 0:
            continue
        lines.append(f"• {t}: {desc}")
    return lines
