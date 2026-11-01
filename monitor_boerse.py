"""
Börse-Monitor für goldi5 (autonom, 2h).
Loggt alle 15 Min: Börsenstatus, Gesamtwert, Rendite, Cash, letzte KI-Trades.
"""
import time, json, os, datetime
import dashboard as dash

app = dash.app
app.config['TESTING'] = True
LOG = os.path.join(os.path.dirname(__file__), "boerse_monitor.log")
INTERVAL = 15 * 60  # 15 Min
RUNS = 8  # 8 * 15 = 120 Min

def snapshot():
    c = app.test_client()
    c.post('/', data={'username': 'goldi5', 'password': 'Goldi2026!'})
    r = c.get('/data')
    if r.status_code != 200:
        return f"\n=== {datetime.datetime.now().strftime('%H:%M:%S')} ===\nWARN: /data lieferte HTTP {r.status_code} (API temporär nicht erreichbar)"
    try:
        d = r.get_json()
    except Exception as e:
        return f"\n=== {datetime.datetime.now().strftime('%H:%M:%S')} ===\nWARN: JSON-Parse fehlgeschlagen: {e}"
    now = datetime.datetime.now().strftime('%H:%M:%S')
    lines = [f"\n=== {now} ==="]
    lines.append("Börsen: " + ', '.join(f"{b.get('name')}={b.get('status')}" for b in (d.get('boersen') or [])))
    lines.append(f"Gesamtwert: {round(d.get('ges_wert',0),2)} | Rendite: {round(d.get('ges_rendite',0),2)}%")
    lines.append(f"Aktien: {len(d.get('depots') or [])} | ETF: {len(d.get('etf_depots') or [])} | Spec: {len(d.get('spec_depots') or [])}")
    cash = sum((x.get('cash',0) or 0) for x in (d.get('depots') or []))
    lines.append(f"Aktien-Cash gesamt: {round(cash,2)}")
    ki = d.get('ki_log', [])
    if ki:
        lines.append("Letzte KI-Trades:")
        for e in ki[:5]:
            lines.append(f"  {str(e.get('zeit','?'))[11:19]} | {e.get('ticker')} | {e.get('aktion')} | {str(e.get('grund',''))[:50]}")
    return "\n".join(lines)

def main():
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"\n\n### MONITOR START {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} ###\n")
    for i in range(RUNS):
        try:
            snap = snapshot()
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(snap + "\n")
            print(snap)
        except Exception as e:
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(f"FEHLER: {e}\n")
        if i < RUNS - 1:
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
