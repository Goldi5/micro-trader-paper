#!/usr/bin/env python3
import json, glob
files = sorted(glob.glob('depot*.json'))
for f in files[:3]:
    d = json.load(open(f))
    t = d.get('trades', [])
    print(f'=== {f} ===')
    print(f'trades: {len(t)}')
    if t:
        print('keys:', list(t[0].keys()))
        print('sample:', json.dumps(t[0], indent=1)[:400])
    print()
