# OPS-NAVIGATION — Phase 2

> Phase 2: Operations-Navigation (Backend-Routen + Frontend-Tab).
> Stand: v2.58.0+. PAPER_ONLY (auth-guarded).

## Änderungen

- **Backend** (`dashboard.py`): 7 neue `/api/ops_*` Routen, alle auth-guarded
  (AUTHENTICATED bzw. ADMIN für staging):
  - `GET /api/ops_system` → `build_system_status()`
  - `GET /api/ops_news` → news_cache.json (headlines + feed_status)
  - `GET /api/ops_provider` → `build_provider_status()`
  - `GET /api/ops_release` → `build_release_status()`
  - `GET /api/ops_risk` → `build_portfolio_status()`
  - `GET /api/ops_recon` → `build_reconciliation_status()`
  - `POST /api/ops_staging` → `ops_staging.run_staging()` (Phase 11)
- **Frontend** (`dashboard.html`): "Operations"-Tab in Hauptnavigation +
  `#panel-operations` mit 6 Cockpit-Boxen (System/KPI, News, Risiko, Provider,
  Release, Recon) + Notfallbereich (Kill-Switch-Button, Staging-Button) +
  JS-Funktionen `showOperations()`, `renderOps*()`, `opsKillSwitch()`, `opsRunStaging()`.

## Verifikation (ad-hoc, PASS)

```bash
# alle Routen liefern 401 ohne Login (Auth-Guard OK)
GET /api/ops_system    -> HTTP 401
GET /api/ops_news      -> HTTP 401
GET  (staging POST)    -> HTTP 401
# JS-Syntax: node --check -> OK
```

## Hinweis

Die Cockpits (Phase 3-10) sind in diesem einen Navigation-Sprint als Panels
bereits sichtbar verdrahtet (System/News/Risiko/Provider/Release/Recon/Emergency).
Detail-Cockpits (Phasen 3-10) erweitern diese Panels bei Bedarf.

## Nächste Phase

**Phase 3-10:** Cockpits detaillieren (bereits basisverdrahtet) + **Phase 11:**
`ops_staging.py` (E2E-Staging-Modul).
