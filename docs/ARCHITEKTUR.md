# Micro-Trader — Architektur

## System-Überblick
```
┌─────────────────────────────────────────────────────────────┐
│ Cron (Hermes, alle 15min) → micro-trader-pipeline.py         │
│   ├─ ki_news.py          (News sammeln)                       │
│   ├─ if us_offen:                                             │
│   │   ├─ spec_trader.py    (48 Depots, KI via ki_provider)    │
│   │   └─ batch_trader.py   (20 Aktien, KI via ki_provider)    │
│   ├─ ki_learning.py       (Regeln aus Entscheidungen)         │
│   ├─ skill_sync.py        (Regeln → Skill)                    │
│   └─ if xetra_offen: etf_trader.py (20 ETF, regelbasiert)    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ Dashboard (Flask :5300)                                      │
│   ├─ dashboard.py  (API: /data, /search_ticker, ...)         │
│   └─ dashboard.html (Apple-Glass Optik, SVG-Charts)          │
└─────────────────────────────────────────────────────────────┘
```

## Order-Pfad (PHASE 13, v2.37.0)
```
KI-Entscheidung (kaufen/verkaufen)
   ↓
create_order_intent(...)            [security.py] 17 Pflichtfelder, UUID
   ↓
validate_order_intent(...)          [security.py] 15-Check-Liste (§11)
   ↓ allowed
PaperBrokerAdapter.place_order()    [security.py] Simulator: paper_orders + paper_positions
   ↓
Status "filled" / "blocked"         (LIVE_* wird hart geblockt, PAPER_ONLY)
```
- `BrokerProvider`-Interface definiert connect/disconnect/health_check/get_account/
  get_positions/get_quote/place_order/cancel_order/get_order_status/get_open_orders.
- Implementiert: nur `PaperBrokerAdapter` (Simulator). Kein Sandbox-/Live-Adapter.
- Vier-Augen-Freigabe: `four_eyes_required(action, requester, approver)`.
- Details: `docs/ORDER-RISK-CHECKLIST.md`, `docs/BROKER-CONNECTOR-SPECIFICATION.md`.

## KI-Provider-Fallback (ki_provider.py)
```python
call_ki(messages, temperature=0.1, max_tokens=2048) → (antwort, provider)
# Kette: zen → nous-step → nous-hy3 → openrouter
# OpenAI KOMPLETT RAUS (Konto leer, 429)
```
- `zen` = deepseek-v4-flash-free (opencode zen, free, schnell)
- `nous-step` = stepfun/step-3.7-flash:free (Nous OAuth)
- `nous-hy3` = tencent/hy3:free (Nous OAuth, aktuell genutzt)
- `openrouter` = nvidia/nemotron-3-ultra-550b-a55b:free

## Datenfluss: Verlaufsgraph
```
portfolio_verlauf(tage=7) [dashboard.py]
  → aggregiert historie-Arrays aller Depots
  → 4 Serien: gesamt / aktien / etf / spec
  → Rendite gegen Startkapital (8800$)
  → letzter Punkt = Live-Wert (v2.11.3)
       ↓
data() [dashboard.py] → portfolio_verlauf im Payload
       ↓
svgLineChart() [dashboard.html] → SVG-Render (36/32px)
```

## Datenfluss: Trade-Historie
```
kategorie_trade_historie(kat) [dashboard.py]
  → sammelt trades aus depot_*.json (oder spec_depots/)
  → mappt aktion→typ für Spec
  → sortiert neueste zuerst
       ↓
histTable() [dashboard.html] → typStyle() Farb-Tags
```

## Wichtige Konstanten
| Wert | Bedeutung |
|------|-----------|
| 8800$ | Startkapital (Aktien 2000 + ETF 2000 + Spec 4800) |
| 15:30–22:00 MEZ | NYSE/NASDAQ Handelszeit |
| 371s | Spec-Trader Laufzeit (max_workers=12) |
| 600s | Cron-Timeout spec_trader |
| ~8s | 1 KI-Call (nous-step) |

## Datei-Abhängigkeiten
- `batch_trader.py` importiert `ki_provider.call_ki` (v2.12.0)
- `spec_trader.py` importiert `ki_decisions.entscheide_spec_batch`
- `ki_decisions.py` importiert `ki_provider.call_ki` (v2.10.x)
- `learned_rules.py` filtert `nur_live=True` (Block 3 Vorbereitung)

## Bekannte Bugs (gelöst)
1. **OpenAI 429** → Fallback-Kette (v2.12.0)
2. **Spec-Trader TIMEOUT** → VIX-Cache + news_score (v2.10.3/4) + Workers/Timeout (v2.12.2)
3. **Spec-Depot start=0** → Reparatur (v2.10.2)
4. **Verlauf ≠ Rendite-Feld** → Live-Sync (v2.11.3)

---
*Stand: v2.12.2 (2026-08-03 22:45)*
