#!/usr/bin/env python3
"""
Generate a styled PDF performance report from Micro-Trader data.
Uses WeasyPrint with HTML/CSS (Glassmorphism, Petrol + Orange accent).
Collects depot data directly via SSH (NOT via the proxy — avoids deadlock).
"""
import json, os, html, subprocess, sys, re
from datetime import datetime

import os
HOST = os.environ.get('MT_PROXMOX_HOST', 'proxmox.local')  # war feste LAN-IP (01.11.2026)
CT = '300'
REMOTE_BASE = '/opt/micro-trader'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report_output.pdf')

def ssh(cmd, timeout=30):
    """Run a command via SSH on the proxy host and execute on CT 300."""
    full_cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@{HOST} "pct exec {CT} -- bash -lc \'{cmd}\'"'
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()

def collect_depots():
    """Direct SSH call — same as proxy collectDepots()"""
    out = ssh(f'bash {REMOTE_BASE}/collect_depots.sh', timeout=45)
    return parse_depot_dump(out)

def parse_depot_dump(text):
    """Parse the depot dump format used by collect_depots.sh"""
    parts = [s.strip() for s in text.split('---FILE---') if s.strip()]
    portfolios = []
    active = None
    for part in parts:
        if '=== ACTIVE ===' in part and '---FILE---' not in part:
            m = re.search(r'=== ACTIVE ===\\s*(\\{.*?\\})\\s*=== DEPOTS ===', part, re.DOTALL)
            if m:
                try:
                    active = json.loads(m.group(1))
                except:
                    pass
            continue
        nl = part.find('\\n')
        if nl < 0: continue
        fname = part[:nl].strip()
        json_str = part[nl+1:].strip()
        try:
            d = json.loads(json_str)
            id = fname.split('/')[-1].replace('.json', '')
            positions = []
            for ticker, pos in (d.get('positions') or {}).items():
                positions.append({
                    'ticker': ticker, 'shares': pos.get('shares', 0),
                    'avg': pos.get('avg_price', 0), 'entry': pos.get('entry_price', 0),
                    'stop_loss': pos.get('stop_loss'), 'take_profit': pos.get('take_profit'),
                })
            value = (d.get('bargeld') or 0) + sum(p['shares'] * p['avg'] for p in positions)
            portfolios.append({
                'id': id,
                'name': id.replace('depot_', 'Depot ').replace('_paper', ' (Paper)').replace('_shadow', ' (Shadow)'),
                'mode': 'paper' if 'paper' in id else 'shadow' if 'shadow' in id else 'live',
                'cash': d.get('bargeld') or 0,
                'startValue': d.get('start_wert') or 0,
                'value': round(value * 100) / 100,
                'positions': len(positions),
                'holdings': positions,
                'trades': d.get('trades') or [],
            })
        except Exception as e:
            pass
    return {'active': active.get('aktiv') if active else None, 'portfolios': portfolios}

def esc(v):
    return html.escape(str(v)) if v is not None else ''

def fmt(n, d=2):
    if n is None: return '—'
    return f'{float(n):,.{d}f}'

def fmt_pct(n):
    if n is None: return '—'
    n = float(n)
    sign = '+' if n >= 0 else ''
    color = '#059669' if n >= 0 else '#dc2626'
    return f'<span style="color:{color}">{sign}{n:.1f}%</span>'

# All CSS braces are DOUBLED {{...}} so Python .format() doesn't interpret them
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<style>
  :root {{
    /* Light theme (default) */
    --bg: #f4f7fb;
    --bg-container: #ffffff;
    --text: #1e293b;
    --text-secondary: #64748b;
    --text-muted: #94a3b8;
    --border: #e2e8f0;
    --header-border: #e2e8f0;
    --table-header-bg: #f1f5f9;
    --table-header-text: #475569;
    --card-bg: rgba(255,255,255,0.85);
    --primary: #0d6efd;
    --accent: #ff6b35;
    --success: #059669;
    --danger: #dc2626;
    --warning: #d97706;
    --score-high-bg: rgba(5,150,105,0.13);
    --score-high-text: #059669;
    --score-mid-bg: rgba(245,158,11,0.13);
    --score-mid-text: #d97706;
    --score-low-bg: rgba(220,38,38,0.13);
    --score-low-text: #dc2626;
    --risk-ok-bg: rgba(5,150,105,0.10);
    --risk-ok-text: #059669;
    --risk-warn-bg: rgba(245,158,11,0.10);
    --risk-warn-text: #d97706;
    --risk-dng-bg: rgba(220,38,38,0.10);
    --risk-dng-text: #dc2626;
    --ticker-chip-bg: #f1f5f9;
    --footer-border: #e2e8f0;
    --footer-text: #94a3b8;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f172a;
      --bg-container: #1e293b;
      --text: #f1f5f9;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --border: #334155;
      --header-border: #334155;
      --table-header-bg: #1e293b;
      --table-header-text: #cbd5e1;
      --card-bg: rgba(30,41,59,0.85);
      --primary: #3b82f6;
      --accent: #fb923c;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --score-high-bg: rgba(16,185,129,0.15);
      --score-high-text: #10b981;
      --score-mid-bg: rgba(245,158,11,0.15);
      --score-mid-text: #f59e0b;
      --score-low-bg: rgba(239,68,68,0.15);
      --score-low-text: #ef4444;
      --risk-ok-bg: rgba(16,185,129,0.12);
      --risk-ok-text: #10b981;
      --risk-warn-bg: rgba(245,158,11,0.12);
      --risk-warn-text: #f59e0b;
      --risk-dng-bg: rgba(239,68,68,0.12);
      --risk-dng-text: #ef4444;
      --ticker-chip-bg: #1e293b;
      --footer-border: #334155;
      --footer-text: #64748b;
    }}
  }}
  /* Explicit theme override via data-theme attribute */
  html[data-theme="dark"] {{
    --bg: #0f172a;
    --bg-container: #1e293b;
    --text: #f1f5f9;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border: #334155;
    --header-border: #334155;
    --table-header-bg: #1e293b;
    --table-header-text: #cbd5e1;
    --card-bg: rgba(30,41,59,0.85);
    --primary: #3b82f6;
    --accent: #fb923c;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --score-high-bg: rgba(16,185,129,0.15);
    --score-high-text: #10b981;
    --score-mid-bg: rgba(245,158,11,0.15);
    --score-mid-text: #f59e0b;
    --score-low-bg: rgba(239,68,68,0.15);
    --score-low-text: #ef4444;
    --risk-ok-bg: rgba(16,185,129,0.12);
    --risk-ok-text: #10b981;
    --risk-warn-bg: rgba(245,158,11,0.12);
    --risk-warn-text: #f59e0b;
    --risk-dng-bg: rgba(239,68,68,0.12);
    --risk-dng-text: #ef4444;
    --ticker-chip-bg: #1e293b;
    --footer-border: #334155;
    --footer-text: #64748b;
  }}
  html[data-theme="light"] {{
    --bg: #f4f7fb;
    --bg-container: #ffffff;
    --text: #1e293b;
    --text-secondary: #64748b;
    --text-muted: #94a3b8;
    --border: #e2e8f0;
    --header-border: #e2e8f0;
    --table-header-bg: #f1f5f9;
    --table-header-text: #475569;
    --card-bg: rgba(255,255,255,0.85);
    --primary: #0d6efd;
    --accent: #ff6b35;
    --success: #059669;
    --danger: #dc2626;
    --warning: #d97706;
    --score-high-bg: rgba(5,150,105,0.13);
    --score-high-text: #059669;
    --score-mid-bg: rgba(245,158,11,0.13);
    --score-mid-text: #d97706;
    --score-low-bg: rgba(220,38,38,0.13);
    --score-low-text: #dc2626;
    --risk-ok-bg: rgba(5,150,105,0.10);
    --risk-ok-text: #059669;
    --risk-warn-bg: rgba(245,158,11,0.10);
    --risk-warn-text: #d97706;
    --risk-dng-bg: rgba(220,38,38,0.10);
    --risk-dng-text: #dc2626;
    --ticker-chip-bg: #f1f5f9;
    --footer-border: #e2e8f0;
    --footer-text: #94a3b8;
  }}
  @page {{
    size: A4;
    margin: 2.5cm;
    @top-left {{ content: "Micro-Trader"; font-size: 8pt; color: var(--text-muted); }}
    @top-right {{ content: "Performance-Bericht {{date}}"; font-size: 8pt; color: var(--text-muted); }}
    @bottom-center {{ content: "Seite " counter(page) " von " counter(pages); font-size: 8pt; color: var(--footer-text); }}
  }}
  body {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; line-height: 1.5; color: var(--text); background: var(--bg); }}
  .container {{ background: var(--bg-container); padding: 30px; border-radius: 14px; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; padding-bottom: 14px; border-bottom: 2px solid var(--header-border); }}
  .logo {{ display: flex; align-items: center; gap: 10px; }}
  .logo-icon {{ width: 36px; height: 36px; background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%); border-radius: 10px; display: flex; align-items: center; justify-content: center; color: white; font-weight: 700; }}
  .logo-text {{ font-size: 22px; font-weight: 700; color: var(--primary); }}
  .summary-grid {{ display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }}
  .summary-card {{ flex: 1; min-width: 140px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }}
  .summary-label {{ font-size: 9pt; text-transform: uppercase; letter-spacing: 0.5pt; color: var(--text-muted); margin-bottom: 6px; }}
  .summary-value {{ font-size: 18pt; font-weight: 700; }}
  .success {{ color: var(--success); }} .danger {{ color: var(--danger); }}
  table {{ width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 8.5pt; }}
  th {{ background: var(--table-header-bg); text-align: left; padding: 7px 9px; border-bottom: 2px solid var(--border); font-weight: 600; color: var(--table-header-text); }}
  td {{ padding: 7px 9px; border-bottom: 1px solid var(--border); }}
  tr.last-row td {{ border-bottom: none; }}
  .mono {{ font-family: 'Roboto Mono', monospace; }}
  .score-pill {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 8pt; font-weight: 700; font-family: monospace; }}
  .score-high {{ background: var(--score-high-bg); color: var(--score-high-text); }}
  .score-mid {{ background: var(--score-mid-bg); color: var(--score-mid-text); }}
  .score-low {{ background: var(--score-low-bg); color: var(--score-low-text); }}
  .risk-badge {{ display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 7.5pt; font-weight: 600; }}
  .risk-ok {{ background: var(--risk-ok-bg); color: var(--risk-ok-text); }}
  .risk-warn {{ background: var(--risk-warn-bg); color: var(--risk-warn-text); }}
  .risk-dng {{ background: var(--risk-dng-bg); color: var(--risk-dng-text); }}
  .ticker-chip {{ display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 7pt; font-family: monospace; background: var(--ticker-chip-bg); }}
  .mode-live {{ background: var(--success); color: white; }}
  .mode-paper {{ background: var(--primary); color: white; }}
  .mode-shadow {{ background: var(--warning); color: white; }}
  .footer {{ margin-top: 32px; padding-top: 14px; border-top: 1px solid var(--footer-border); font-size: 8.5pt; color: var(--footer-text); text-align: center; }}
  h2 {{ font-size: 14pt; color: var(--primary); margin: 24px 0 12px; page-break-after: avoid; }}
  table {{ page-break-inside: avoid; }} tr {{ page-break-inside: avoid; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="logo">
      <div class="logo-icon">📈</div>
      <div><div class="logo-text">Micro-Trader</div><div style="font-size:14px;color:var(--text)">Performance-Bericht</div></div>
    </div>
    <div style="font-size:8.5pt;color:var(--text-secondary)">Erstellt: {{date}}</div>
  </div>
  <div class="summary-grid">
    <div class="summary-card"><div class="summary-label">Gesamtwert</div><div class="summary-value">${{total_value}}</div></div>
    <div class="summary-card"><div class="summary-label">Ø Performance</div><div class="summary-value {{total_perf_color}}">{{total_perf}}%</div></div>
    <div class="summary-card"><div class="summary-label">Depots</div><div class="summary-value">{{count}}</div></div>
    <div class="summary-card"><div class="summary-label">Gesamt-Trades</div><div class="summary-value">{{total_trades}}</div></div>
    <div class="summary-card"><div class="summary-label">Ø Risiko</div><div class="summary-value">{{avg_risk}}/100</div></div>
  </div>
  <h2>Portfolio-Performance</h2>
  <table>
    <thead><tr><th>#</th><th>Depot</th><th>Modus</th><th align="right">Start ($)</th><th align="right">Wert ($)</th><th align="right">Perf.</th><th align="right">Trades</th><th align="right">Risiko</th><th>Status</th></tr></thead>
    <tbody>{{rows}}</tbody>
  </table>
  <h2>Risiko-Details</h2>
  <table>
    <thead><tr><th>Depot</th><th align="right">Score</th><th align="right">Max-DD</th><th align="right">Turnover</th><th align="right">Win-Rate</th><th>Max-Konzentration</th></tr></thead>
    <tbody>{{risk_rows}}</tbody>
  </table>
  <div class="footer">Micro-Trader PDF Report • {{date_full}}</div>
</div>
</body>
</html>"""

def compute_risks_inline(portfolios):
    """Compute basic risk inline — same logic as riskEngine.ts"""
    results = []
    for p in portfolios:
        start = p.get('startValue', 100)
        value = p.get('value', start)
        trades = p.get('trades', [])
        perf = ((value - start) / start * 100) if start > 0 else 0
        buys = [t for t in trades if str(t.get('side','') + t.get('typ','')).lower().startswith('b') or t.get('typ','').lower().startswith('kauf')]
        sells = [t for t in trades if t not in buys]
        total_val = sum(abs(t.get('value') or (t.get('shares') or 0) * (t.get('price') or t.get('preis') or 0)) for t in trades)
        turnover = total_val / start if start > 0 else 0
        pos_vals = {}
        for t in trades:
            tk = t.get('ticker', t.get('symbol',''))
            is_buy = t in buys
            sz = (t.get('shares') or 0)
            if not is_buy: sz = -sz
            price = t.get('price') or t.get('preis') or 0
            pos_vals[tk] = pos_vals.get(tk, 0) + sz * price
        max_pos = max(pos_vals.values()) / value * 100 if value > 0 and pos_vals else 0
        dd_proxy = max(0, -perf)
        dd_score = min(100, dd_proxy * 4)
        conc_score = min(100, max_pos * 3)
        turn_score = min(100, turnover * 10)
        score = round(dd_score*0.4 + conc_score*0.3 + turn_score*0.3)
        level = 'low' if score < 35 else 'medium' if score < 70 else 'high'
        win_rate = (len(sells) / len(trades) * 100) if trades else 0
        results.append({
            'depotId': p.get('id'), 'depotName': p.get('name', p.get('id')),
            'riskScore': score, 'riskLevel': level,
            'maxDrawdownPct': dd_proxy, 'turnoverRate': turnover,
            'winRate': win_rate,
            'positionRisk': [{'ticker': max(pos_vals, key=pos_vals.get) if pos_vals else '', 'weight': max_pos}],
        })
    return results

def generate(theme='light'):
    date_str = datetime.now().strftime('%d.%m.%Y, %H:%M')
    date_full = datetime.now().strftime('%d.%m.%Y %H:%M:%S')

    d = collect_depots()
    portfolios = d.get('portfolios', [])
    active = d.get('active')
    risks = compute_risks_inline(portfolios)
    risk_map = {r['depotId']: r for r in risks}

    total_value = sum(p.get('value', 0) for p in portfolios)
    total_start = sum(p.get('startValue', 0) for p in portfolios)
    total_perf = ((total_value - total_start) / total_start * 100) if total_start > 0 else 0
    total_trades = sum(len(p.get('trades', [])) for p in portfolios)
    total_perf_color = 'success' if total_perf >= 0 else 'danger'
    avg_risk = round(sum(r['riskScore'] for r in risks) / len(risks)) if risks else 0

    rows_html = []
    for i, p in enumerate(sorted(portfolios, key=lambda x: x.get('value',0), reverse=True)):
        perf = ((p.get('value',0) - p.get('startValue',0)) / p.get('startValue',1) * 100) if p.get('startValue',0) > 0 else 0
        r = risk_map.get(p.get('id'))
        risk_score = r['riskScore'] if r else 0
        risk_level = r['riskLevel'] if r else 'low'
        risk_color = 'score-high' if risk_score > 70 else 'score-mid' if risk_score > 35 else 'score-low'
        status_cls = 'risk-ok' if risk_level == 'low' else 'risk-warn' if risk_level == 'medium' else 'risk-dng'
        status_txt = {'low': 'Niedrig', 'medium': 'Mittel', 'high': 'Kritisch'}.get(risk_level, '—')
        rows_html.append(f'<tr class="last-row"><td class="mono">#{i+1}</td><td><strong>{esc(p.get("name", p.get("id")))}</strong> {esc("★" if p.get("id") == active else "")}</td><td><span class="ticker-chip mode-{esc(p.get("mode","live"))}">{esc(p.get("mode","live"))}</span></td><td align="right">{fmt(p.get("startValue",0))}</td><td align="right">{fmt(p.get("value",0))}</td><td align="right">{fmt_pct(perf)}</td><td align="right">{len(p.get("trades",[])) or 0}</td><td align="right"><span class="score-pill {risk_color}">{risk_score}/100</span></td><td><span class="risk-badge {status_cls}">{esc(status_txt)}</span></td></tr>')

    risk_rows_html = []
    for r in sorted(risks, key=lambda x: x['riskScore'], reverse=True):
        rc = 'score-high' if r['riskScore'] > 70 else 'score-mid' if r['riskScore'] > 35 else 'score-low'
        max_pos = r.get('positionRisk', [{}])[0]
        max_pos_str = f"{max_pos.get('weight',0):.1f}% ({max_pos.get('ticker')})" if max_pos.get('ticker') else '—'
        risk_rows_html.append(f'<tr class="last-row"><td><strong>{esc(r.get("depotName"))}</strong></td><td align="right"><span class="score-pill {rc}">{r["riskScore"]}/100</span></td><td align="right">{fmt_pct(-r.get("maxDrawdownPct",0))}</td><td align="right">{fmt(r.get("turnoverRate",0))}</td><td align="right">{fmt(r.get("winRate",0))}%</td><td>{esc(max_pos_str)}</td></tr>')

    # Inject theme via data-theme attribute on <html>
    html_content = HTML_TEMPLATE.replace('\n<html lang="de">', f'\n<html lang="de" data-theme="{theme}">').format(
        date=date_str, date_full=date_full,
        total_value=fmt(total_value),
        total_perf=fmt(total_perf, 1),
        total_perf_color=total_perf_color,
        count=len(portfolios), total_trades=total_trades, avg_risk=avg_risk,
        rows='\n'.join(rows_html),
        risk_rows='\n'.join(risk_rows_html),
    )

    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(OUT, presentational_hints=True)
        print(f'PDF report written to {OUT}')
        return OUT
    except Exception as e:
        print(f'WeasyPrint error: {e}', file=sys.stderr)
        html_out = OUT.replace('.pdf', '.html')
        with open(html_out, 'w') as f:
            f.write(html_content)
        print(f'PDF generation failed — wrote HTML to {html_out}')
        return html_out

if __name__ == '__main__':
    import sys
    theme = 'light'
    if len(sys.argv) > 1:
        if sys.argv[1] in ('dark', 'light'):
            theme = sys.argv[1]
        else:
            print(f'Usage: python3 {sys.argv[0]} [light|dark]')
            sys.exit(1)
    path = generate(theme=theme)
    if path and os.path.exists(path):
        print(f'SUCCESS: {path} ({os.path.getsize(path)} bytes)')
    else:
        print('FAILURE')
        sys.exit(1)