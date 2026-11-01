#!/usr/bin/env python3
"""Compute cumulative portfolio value timeline from trades.
Usage: python3 timeseries.py <depot_json_name>
Outputs JSON list of {date, value} sorted by time.
"""
import json, sys, os

base = os.path.dirname(os.path.abspath(__file__))  # war fest "/opt/micro-trader" (01.11.2026)
depot_name = sys.argv[1] if len(sys.argv) > 1 else 'depot.json'
fpath = os.path.join(base, depot_name)

if not os.path.exists(fpath):
    print(json.dumps({"error": f"{depot_name} not found"}))
    sys.exit(0)

with open(fpath) as f:
    d = json.load(f)

trades = d.get('trades', [])
start_value = float(d.get('start_wert', d.get('start', 100)))

# Normalize trades
normalized = []
for t in trades:
    zeit = t.get('zeit', t.get('time', ''))
    ticker = t.get('ticker', t.get('symbol', ''))
    side = t.get('side', t.get('typ', ''))
    shares = abs(float(t.get('shares', t.get('menge', 0))))
    price = float(t.get('price', t.get('preis', 0)))
    value = abs(float(t.get('value', shares * price)))
    is_sell = (str(side).upper().startswith('S') or str(side).lower().startswith('v'))

    normalized.append({
        'zeit': zeit, 'ticker': ticker, 'is_sell': is_sell,
        'shares': shares, 'price': price, 'value': value,
    })

normalized.sort(key=lambda x: x['zeit'])

# Build timeline
timeline = []
cash = start_value
positions = {}  # ticker -> {shares, cost_basis}

for t in normalized:
    shares = t['shares']
    if t['is_sell']:
        cash += t['value']
        if t['ticker'] in positions:
            positions[t['ticker']]['shares'] = max(0, positions[t['ticker']]['shares'] - shares)
            if positions[t['ticker']]['shares'] < 0.0001:
                del positions[t['ticker']]
    else:
        cash -= t['value']
        if t['ticker'] not in positions:
            positions[t['ticker']] = {'shares': 0, 'cost': 0}
        positions[t['ticker']]['shares'] += shares
        positions[t['ticker']]['cost'] += t['value']

    # Mark-to-market: use THIS trade's price for the affected ticker,
    # previous latest prices for others
    # Reconstruct latest prices up to this point
    latest_prices = {}
    for prev in normalized:
        if prev['zeit'] <= t['zeit']:
            latest_prices[prev['ticker']] = prev['price']

    pos_value = sum(pos['shares'] * latest_prices.get(tk, 0) for tk, pos in positions.items())
    total = cash + pos_value
    timeline.append({"date": t['zeit'], "value": round(total, 2)})

print(json.dumps(timeline))
