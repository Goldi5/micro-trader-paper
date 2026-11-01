#!/bin/bash
base=/opt/micro-trader
echo "=== analysis_cache.json keys ==="
python3 -c "import json; d=json.load(open('$base/analysis_cache.json')); print(list(d.keys())[:20] if isinstance(d,dict) else type(d))" 2>/dev/null || echo "NO analysis_cache.json"
echo "=== depot trades sample ==="
python3 -c "
import json, glob
fs = glob.glob('$base/depot*.json')
f = fs[0]
d = json.load(open(f))
t = d.get('trades', [])
print('file:', f.split('/')[-1], '| trades:', len(t))
if t: print('sample:', json.dumps(t[-1])[:200])
" 2>/dev/null || echo "NO depot trades"
echo "=== files with history ==="
ls -1 $base/*.json 2>/dev/null | grep -iE "history|timeseries|chart|price|kline" | head
echo "=== price_cache / quotes? ==="
ls -1 $base/*.json 2>/dev/null | grep -iE "quote|price|tick" | head
