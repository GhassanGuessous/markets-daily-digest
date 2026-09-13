"""
Daily markets dashboard data builder for Ghassan.
Fetches oil, gold, major indexes, crypto (BTC, ETH), USD/MAD & EUR/MAD,
and MASI/MASI 20 (Casablanca), then writes docs/digest.json for the static
dashboard at docs/index.html to render. All prices are shown in USD with
their MAD equivalent alongside.

Run via GitHub Actions on a daily schedule (see .github/workflows/daily-digest.yml),
which commits the refreshed docs/digest.json so GitHub Pages serves the latest data.
"""

import json
import re
from datetime import datetime, timezone

import requests
import yfinance as yf
from bs4 import BeautifulSoup

DIGEST_JSON_PATH = "docs/digest.json"

# ---------------------------------------------------------------------------
# Config: tickers and sources
# ---------------------------------------------------------------------------

# name -> (ticker symbol, native currency of the quoted price)
YFINANCE_TICKERS = {
    "Brent Crude Oil": ("BZ=F", "USD"),
    "WTI Crude Oil": ("CL=F", "USD"),
    "Gold (per gram)": ("GC=F", "USD"),
    "Silver (per gram)": ("SI=F", "USD"),
    "S&P 500": ("^GSPC", "USD"),
    "CAC 40": ("^FCHI", "EUR"),
    "Bitcoin (BTC)": ("BTC-USD", "USD"),
    "Ethereum (ETH)": ("ETH-USD", "USD"),
}

# Gold/silver futures (GC=F, SI=F) quote USD per troy ounce; convert to grams.
PER_GRAM_TICKERS = {"Gold (per gram)", "Silver (per gram)"}
TROY_OUNCE_GRAMS = 31.1034768

FX_PAIRS = [("USD", "MAD"), ("EUR", "MAD")]


def to_usd_and_mad(value, currency, fx):
    """Convert a value in its native currency to (usd_value, mad_value)."""
    usdmad = fx.get("USD/MAD")
    eurmad = fx.get("EUR/MAD")
    if value is None or usdmad is None:
        return None, None
    if currency == "USD":
        return value, round(value * usdmad, 2)
    if currency == "EUR":
        if eurmad is None:
            return None, None
        mad = value * eurmad
        return round(mad / usdmad, 2), round(mad, 2)
    if currency == "MAD":
        return round(value / usdmad, 2), value
    raise ValueError(f"unsupported currency: {currency}")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_yfinance_quotes():
    """Return {name: (price, pct_change, currency)} for each configured ticker."""
    results = {}
    for name, (symbol, currency) in YFINANCE_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) < 2:
                results[name] = (None, None, currency)
                continue
            last_close = hist["Close"].iloc[-1]
            prev_close = hist["Close"].iloc[-2]
            pct = (last_close - prev_close) / prev_close * 100
            price = last_close / TROY_OUNCE_GRAMS if name in PER_GRAM_TICKERS else last_close
            results[name] = (round(price, 2), round(pct, 2), currency)
        except Exception as e:
            print(f"[warn] failed to fetch {name} ({symbol}): {e}")
            results[name] = (None, None, currency)
    return results


def fetch_fx_rates():
    """
    Return {'USD/MAD': rate, 'EUR/MAD': rate} using open.er-api.com (free, no key).

    Note: frankfurter.app (the previous source) is ECB-based and does not carry
    MAD at all, so it always failed for this pair — open.er-api.com does.
    """
    rates = {}
    for base, quote in FX_PAIRS:
        try:
            resp = requests.get(
                f"https://open.er-api.com/v6/latest/{base}",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") != "success":
                raise ValueError(data.get("error-type", "unknown error"))
            rates[f"{base}/{quote}"] = round(data["rates"][quote], 4)
        except Exception as e:
            print(f"[warn] failed to fetch {base}/{quote}: {e}")
            rates[f"{base}/{quote}"] = None
    return rates


MASI_INDEXES = ["MASI", "MASI 20"]


def fetch_masi_indexes():
    """
    Best-effort scrape of the MASI and MASI 20 indexes from Casablanca
    Bourse's public homepage. The old /bourseweb/en/index.aspx page is gone
    (410); these are now rendered server-side on the homepage as
    "data-block" widgets keyed by their exact title text.
    Site structure can change; if this breaks, the digest still sends with
    the affected index marked as unavailable rather than failing entirely.

    Returns {name: (value, pct_change)} — value in MAD points — with
    (None, None) for any index that couldn't be found.
    """
    results = {name: (None, None) for name in MASI_INDEXES}
    try:
        resp = requests.get(
            "https://www.casablanca-bourse.com/",
            timeout=10,
            headers={
                # The site's WAF rejects bare "Mozilla/5.0" user agents; it
                # needs a full, realistic browser-like header set.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for block in soup.select(".data-block"):
            title = block.select_one(".block-title")
            name = title.get_text(strip=True) if title else None
            if name not in results:
                continue
            value_el = block.select_one(".main-value")
            pct_el = block.select_one(".variation-value")
            if not value_el:
                continue
            value = float(re.sub(r"\s", "", value_el.get_text()).replace(",", "."))
            pct = None
            if pct_el:
                pct_text = re.sub(r"[^\d,.\-]", "", pct_el.get_text())
                if pct_text:
                    pct = float(pct_text.replace(",", "."))
            results[name] = (value, pct)
    except Exception as e:
        print(f"[warn] failed to fetch MASI indexes: {e}")
    return results


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_digest(quotes, fx, masi_indexes):
    today = datetime.now().strftime("%A, %d %B %Y")
    lines = [f"Daily Markets Digest — {today}", ""]

    lines.append("GLOBAL (USD, MAD equivalent)")
    for name, (price, pct, currency) in quotes.items():
        if price is None:
            lines.append(f"  {name}: data unavailable")
            continue
        usd, mad = to_usd_and_mad(price, currency, fx)
        if usd is None:
            lines.append(f"  {name}: {price} {currency}  (MAD conversion unavailable)")
            continue
        arrow = "▲" if pct >= 0 else "▼"
        lines.append(f"  {name}: ${usd:,.2f}  ({mad:,.2f} MAD)  ({arrow} {pct:+.2f}%)")

    lines.append("")
    lines.append("MOROCCO / FX")
    for pair, rate in fx.items():
        lines.append(f"  {pair}: {rate if rate is not None else 'data unavailable'}")

    for name, (value, pct) in masi_indexes.items():
        if value is None:
            lines.append(f"  {name} (Casablanca): unavailable — check casablanca-bourse.com")
            continue
        arrow = ""
        if pct is not None:
            arrow = f"  ({'▲' if pct >= 0 else '▼'} {pct:+.2f}%)"
        lines.append(f"  {name} (Casablanca): {value:,.2f} MAD{arrow}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dashboard data
# ---------------------------------------------------------------------------

def build_digest_data(quotes, fx, masi_indexes):
    """Build the JSON-serializable payload consumed by docs/index.html."""
    global_rows = []
    for name, (price, pct, currency) in quotes.items():
        usd, mad = to_usd_and_mad(price, currency, fx)
        global_rows.append(
            {
                "name": name,
                "price": price,
                "currency": currency,
                "usd": usd,
                "mad": mad,
                "pct": pct,
            }
        )

    masi_rows = [
        {"name": name, "mad": value, "pct": pct}
        for name, (value, pct) in masi_indexes.items()
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "global": global_rows,
        "fx": fx,
        "masi": masi_rows,
    }


def write_digest_json(data, path=DIGEST_JSON_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_previous_digest(path=DIGEST_JSON_PATH):
    """Load the last successfully written digest, if any, to fall back on."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fill_missing_from_previous(quotes, fx, masi_indexes, previous):
    """
    Carry forward the last known value for anything that failed to fetch this
    run, instead of showing it as unavailable.
    """
    if not previous:
        return

    prev_quotes = {row["name"]: row for row in previous.get("global", [])}
    for name, (price, _pct, currency) in quotes.items():
        prev = prev_quotes.get(name)
        if price is None and prev and prev.get("price") is not None:
            quotes[name] = (prev["price"], prev["pct"], currency)

    prev_fx = previous.get("fx", {})
    for pair, rate in fx.items():
        if rate is None and prev_fx.get(pair) is not None:
            fx[pair] = prev_fx[pair]

    prev_masi = {row["name"]: row for row in previous.get("masi", [])}
    for name, (value, _pct) in masi_indexes.items():
        prev = prev_masi.get(name)
        if value is None and prev and prev.get("mad") is not None:
            masi_indexes[name] = (prev["mad"], prev.get("pct"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    previous = load_previous_digest()

    quotes = fetch_yfinance_quotes()
    fx = fetch_fx_rates()
    masi_indexes = fetch_masi_indexes()

    fill_missing_from_previous(quotes, fx, masi_indexes, previous)

    print(format_digest(quotes, fx, masi_indexes))  # visible in GitHub Actions logs

    data = build_digest_data(quotes, fx, masi_indexes)
    write_digest_json(data)


if __name__ == "__main__":
    main()
