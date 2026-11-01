# Shadow -> Paper -> Live Governance (PHASE 6, v2.30.0)

> PHASE 6 des Mandanten-Ausbauauftrags (Sektion 9). Freigabe-Workflow Shadow -> Paper.

## Stufe A: Shadow (aktiv)
- Entscheidungen beobachten, kein Order, Lern/Audit.

## Stufe B: Paper (Freigabe via Eligibility-Check)
Voraussetzungen (paper_eligibility):
- Tenant aktiv
- Mindestanzahl KI-Entscheidungen (>= 20, konfigurierbar)
- Audit-Trail vollstaendig
- keine kritischen Fehler
- Regelstand reproduzierbar
- kein unaufgeloester Regelkonflikt

Bei Erfuellung: enter_paper() wechselt SHADOW -> PAPER (erzwingt Transition, schreibt Audit).
Paper erhaelt EIGENES virtuelles Portfolio (paper_portfolios/paper_positions) — nicht mit
Shadow-Depots vermischt.

## Stufe C-E: Live (spaeter, Phase 11/12)
- Live-Antrag (LIVE_REQUESTED) pro Tenant/Portfolio/Strategie/Broker/Risiko
- Live-Review (Mindestdauer Paper, Drawdown, Slippage, Broker-Sandbox)
- Live-Freigabe (vier-Augen, MFA, Limits) -> LIVE_ACTIVE
- Micro-Live (kleine Limits, Auto-Pause bei Ueberschreitung)
PAPER_ONLY bleibt bis Phase 17 aktiv.

## API
- GET  /api/paper/eligibility -> {eligible, gruende}
- POST /api/paper/enter       -> SHADOW->PAPER (TENANT_ADMIN)
