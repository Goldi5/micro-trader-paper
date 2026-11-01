# Micro-Trader — Live-Roadmap & Strategie (4 Arbeitsstränge)

> **Status:** Strategie-Entwurf, Stand 2026-08-10
> **Quelle:** Handoff-V3.pdf (Live-Freigabeprozess) + eigene Ist-Analyse
> **Ziel:** Brücke von Paper-Only → verantwortbarer Live-Betrieb
> **Grundsatz:** PAPER_ONLY bleibt Pflicht bis Phase 6/7 vollständig grün

---

## 0. Ist-Zustand (verifiziert 2026-08-10)

| Bereich | Status | Befund |
|---|---|---|
| News-Pipeline | ⚠️ Teilweise | `news_monitor.py` (RSS, stündlich, Keyword-Match) + `news_evaluator.py` (KI, 2h-Zyklus, nutzt **alten** `OPENCODE_GO_API_KEY`) vorhanden. Keine Ticker-Zuordnung, keine P0/P1, keine Deduplizierung, kein strukturiertes JSON-Schema. |
| markt_daten | ❌ Leer | Tabelle existiert (db.py Z812) aber zur Laufzeit leer → blockiert Shadow→Paper-Übergang (paper_eligibility prüft `markt_daten < 3 Tage`). |
| Man. Depotsteuerung | ❌ Fehlt | Kein PAUSE/CANCEL/CLOSE-Portfolio-Endpunkt. Notfall-Kill-Switch fehlt komplett. |
| Broker-Abstraktion | ⚠️ Skelett | `BrokerProvider`-Interface nur als Konzept in security.py (Order-Intent). Kein `PaperBrokerAdapter` (trotz Handoff-Erwähnung), keine Sandbox/Live-Adapter. |
| Tenant-Isolation | ✅ Vorhanden | tenant_id in allen Depot-/Order-Tabellen. |
| Order-Intent | ✅ Vorhanden | `create_order_intent` + `validate_order_intent` (15-Check-Liste) existiert. |
| Risiko-Gates | ✅ Vorhanden | `enforce_approval`, `four_eyes_required` implementiert. |
| KI-Pool | ✅ Repariert | openrouter(nemotron-nano) Primary, nous-hy3/step, zen(ling) — alle live (Commit 7a9bcc1). |

**Kritisch:** `markt_daten` leer + News nicht strukturiert = die zwei größten Blocker für jeden Live-Schritt.

---

## 1. Vier Arbeitsstränge (aus Handoff-V3)

### Strang A — Professionelle News-Pipeline
- RSS/API-Ingestion (5–15 Min) → Normalisierung → Deduplizierung → Ticker-Mapping → Relevanz/Qualität-Filter → KI-Bewertung (P0–P3) → News-Impact in Trading-Prompt → Audit.
- **Quellen-Klassen:** A=Primär (SEC-EDGAR, Börsen, IR), B=sériös (RSS, GDELT als Discovery), C=Kontext (Blogs, Social — nur Hinweis, keine Order).
- **KI-Rhythmus:** Sammeln 5–10 Min (Börsenzeiten), Normal 15 Min, Event sofort bei P0/Score>85/Volatilität, Tagesabschluss post-close.
- **News-Prompt:** Neutrales JSON (relevance/credibility/urgency/event_type/direction/market_impact/confidence) — **keine** Kauf-/Verkauf-Empfehlung.

### Strang B — Manuelle Notfall- & Depotsteuerung (JETZT im Paper-Modus bauen!)
- Aktionen: `PAUSE`, `CANCEL_PENDING`, `CLOSE_POSITION`, `CLOSE_PORTFOLIO`, `CLOSE_ALL_TENANT_PORTFOLIOS`, `SUSPEND_TRADING`.
- Status-Modell: `OPEN → CLOSE_REQUESTED → CLOSING → PARTIALLY_CLOSED → CLOSED | CLOSE_FAILED | SUSPENDED`.
- UI: roter Button, Warnung, Betroffene-Positionen, Gegenwert, Marktzeit-Hinweis, MFA/2FA-Bestätigung, Grundfeld, Fortschritt, Ergebnisliste.
- Paper-Test sicher möglich (kein Echtgeld-Risiko).

### Strang C — Broker-/Trading-Plattform
- `BrokerProvider`-Interface: connect/disconnect/health/get_account/get_positions/get_open_orders/place_order/cancel_order/close_position/close_all_positions.
- Adapter-Hierarchie: `PaperBrokerAdapter` (simuliert) → `AlpacaSandboxAdapter` → `AlpacaLiveAdapter` (erst nach Freigabe).
- **Alpaca als Kandidat:** Trading API, Paper-Env, REST+Streaming, $0 Commission (US), FINRA/SIPC. **Aber:** EU-Verfügbarkeit + Wohnsitz (DE) prüfen! Gilt nicht automatisch für Privatkunden-EU.
- Keine Keys im Frontend (nur `••••ABCD` + Status).

### Strang D — Regulatorischer & technischer Live-Freigabeprozess
- Live-Antrag: Paper-Mindestdauer, Mindest-Trades, Drawdown-Limit, Datenqualität, Regelversion, Providerqualität, Sandbox-Test, User-MFA, Risiko-Review, Vier-Augen.
- Micro-Live nur mit: kleinste Order, Tages/Gesamt-Verlustlimit, auto-Pause, manuelle Sofortschließung, kein Hebel, keine 3x/Meme/Spekulation am Anfang, 1 Broker/1 Portfolio/1 Strategie.

---

## 2. Meine Ideen / Ergänzungen (basierend auf Ist-Analyse)

### 2.1 News-Pipeline: Bestehende Module erweitern, nicht neu bauen
- `news_monitor.py` schon da → **um Ticker-Mapping erweitern** (Ticker-Liste aus `spec_watch.json` + Aktien/ETF-Depots als Lookup).
- `news_evaluator.py` nutzt **veralteten** `OPENCODE_GO_API_KEY` → **auf reparierten `ki_provider.call_ki` umstellen** (Pool mit openrouter/hy3/step/zen).
- Deduplizierung: `duplicate_group` via Hash von (title+url+published_at).
- **News-Schema erweitern** (aus Handoff): news_id, source_type, event_type, relevance/credibility/novelty/market_impact/urgency/sentiment/confidence, duplicate_group, processed_by_model.
- **News→Trading-Brücke:** Strukturierter JSON-Kontext (nicht Rohtext) in `ki_decisions.entscheide_spec_batch()` injizieren.

### 2.2 markt_daten: ERSTER Fix (Blocker #1)
- `markt_daten` ist leer → `paper_eligibility` schlägt fehl → Shadow→Paper tot.
- **Lösung:** `monitor_boerse.py` (existiert schon!) schreibt Kurse → muss in `markt_daten` persistieren (nicht nur /data-Cache).
- Cron: alle 15 Min während Börsenzeiten. Snapshot-ID für KI-Entscheidung.

### 2.3 Man. Depotsteuerung: Kill-Switch Priorität
- **Wichtiger als Broker-Anbindung** (Notfall muss im Paper schon gehen).
- `CLOSE_ALL_TENANT_PORTFOLIOS` + `SUSPEND_TRADING` als erstes bauen (läuft über bestehende `engine.ausführen` im Paper-Modus).
- MFA-Pflicht für `SUSPEND_TRADING` (kritisch).

### 2.4 Broker: Alpaca EU-Reality-Check zuerst
- Bevor Code: **Prüfen ob Alpaca für DE-Wohnsitz verfügbar** (KYC/AML, Steuerreporting). Falls nein → Sandbox nur US-Paper, Live erst nach EU-Broker (z.B. CapTrader/InteractiveBrokers EU, Trade Republic API?).
- `PaperBrokerAdapter` zuerst voll funktionsfähig (Account/Position/Order-Sync simuliert) → Dashboard zeigt Broker-Ansicht schon mit Fake-Daten.

### 2.5 Datenqualität als Querschnitt
- `MarketSnapshot`-Objekt: einheitlicher Snapshot (preis/rsi/sma/volumen/zeitstempel/alter) pro Ticker.
- Datenalter-Gate: KI-Entscheidung nur mit `age < 3 Tage` (schon in paper_eligibility).

---

## 3. Empfohlene Reihenfolge (12 Schritte, aus Handoff + eigene Priorisierung)

| # | Schritt | Strang | Priorität | Status |
|---|---|---|---|---|
| 1 | `markt_daten`-Persistenz fixen (monitor→db) | C/3 | **P0 (Blocker)** | ✅ 2.52.0 (markt_daten_fuellen.py) |
| 2 | News-Pipeline technisch neu strukturieren (Ticker-Map, Dedup, Schema) | A | P0 | ✅ 2.54.0 |
| 3 | News-Prompt + 15-Min-Zyklus + P0-Eventweg | A | P1 | ✅ 2.54.0 (urgency/event_type/direction) |
| 4 | Man. Depot-Schließen im Paper-Modus (PAUSE/CANCEL/CLOSE/SUSPEND) | B | **P0 (Notfall)** | ✅ 2.53.0-2.54.0 (Pause/Verkaufen/Schließen/Löschen) |
| 5 | `MarketSnapshot` einführen + Snapshot-ID in KI | C/3 | P1 | ✅ 2.54.0 (market_snapshot.py) |
| 6 | Broker-Kandidat EU-Verfügbarkeit prüfen (Alpaca DE?) | C | P1 | ✅ 2.54.0 (Alpaca Europe, Xetra DE, B2B-Fokus) |
| 7 | `PaperBrokerAdapter` voll implementieren + Dashboard-Ansicht | C | P1 | ✅ (Adapter existiert, Broker-Tab 2.54.0) |
| 8 | Sandbox-Adapter anbinden (nur Paper/Sandbox) | C | P2 | ⬜ offen |
| 9 | Brokerdaten im Dashboard (Account/Position/Order/Sync) | C | P2 | 🔶 Basis-Tab da, Sync-Zustand fehlt |
| 10 | Order-Sync + Fehlerzustände (QUANTITY_MISMATCH etc.) | C | P2 | ⬜ offen |
| 11 | Live-Freigabeprozess testen (already scaffolded in live_requests) | D | P3 | ⬜ offen |
| 12 | Micro-Live vorbereiten (1 Portfolio, klein, kein Hebel) | D | P3 | ⬜ offen |

**Nicht direkt mit Echtgeld starten.** Brücke = News + man. Schließung + persistierte Marktdaten + Sandbox-Broker + Order-Sync.

---

## 4. Offene Fragen / Entscheidungen nötig

- [ ] **Alpaca für DE-Wohnsitz verfügbar?** (KYC/AML, Steuer) → sonst EU-Broker wählen.
- [ ] News-Quellen: SEC-EDGAR für US-Ticker ok (kein Key), aber EU-IR-Seiten?
- [ ] Wer darf `SUSPEND_TRADING` (nur superadmin + MFA)?
- [ ] News-KI: welcher Provider (openrouter nemotron-nano als Primary, wie Trader-Pool)?
- [ ] `markt_daten`: welche Ticker (nur Spec-Watchlist oder alle Aktien/ETF)?

---

## 5. Quellen (Handoff-V3 Referenzen)

- SEC EDGAR API: https://www.sec.gov/search-filings/edgar-application-programming-interfaces (kein Key, User-Agent nötig)
- GDELT: https://www.gdeltproject.org/data.html (free, Discovery-Quelle)
- Alpaca: https://alpaca.markets/ (Trading API, Paper, $0 Commission US)
- Micro-Trader-Handoff-V3.pdf (Original, S3-Link abgelaufen/AccessDenied)
