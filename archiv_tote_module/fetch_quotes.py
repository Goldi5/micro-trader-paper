#!/usr/bin/env python3
"""Fetch live quotes for tickers using yfinance.
Usage: python3 fetch_quotes.py <comma-separated-tickers>
Outputs JSON list of {symbol, price, change, changePct}.
Has retry logic, returns empty list on failure (never crashes proxy).
"""
import sys, json, yfinance as yf

def main():
    tickers_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    tickers = [t.strip().upper() for t in tickers_arg.split(',') if t.strip()]
    if not tickers:
        print("[]"); return

    max_retries = 3
    quotes = []
    for attempt in range(max_retries):
        try:
            data = yf.Tickers(' '.join(tickers))
            for symbol in tickers:
                tk = data.tickers.get(symbol)
                if tk is None:
                    quotes.append({"symbol": symbol, "price": None, "error": "not found"})
                    continue
                info = getattr(tk, 'info', {}) or {}
                price = info.get('regularMarketPrice') or info.get('previousClose') or None
                chg = info.get('regularMarketChange') or 0
                chg_pct = info.get('regularMarketChangePercent') or 0
                quotes.append({
                    "symbol": symbol,
                    "price": round(price, 2) if price is not None else None,
                    "change": round(chg, 2) if chg else None,
                    "changePct": round(chg_pct, 2) if chg_pct else None,
                })
            break
        except Exception as e:
            if attempt == max_retries - 1:
                # Return what partial data we have, mark rest as error
                symbols_covered = {q['symbol'] for q in quotes}
                for symbol in tickers:
                    if symbol not in symbols_covered:
                        quotes.append({"symbol": symbol, "price": None, "error": str(e)[:100]})
            continue
    print(json.dumps(quotes))

main()
