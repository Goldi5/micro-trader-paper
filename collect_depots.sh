#!/bin/bash
# Collects all depot data from CT 300 and prints as a single JSON-less delimited dump
base=/opt/micro-trader
echo "=== ACTIVE ==="
cat $base/active_profile.json 2>/dev/null
echo ""
echo "=== DEPOTS ==="
for f in $base/depot*.json; do
  echo "---FILE--- $f"
  cat "$f" 2>/dev/null
  echo ""
done
