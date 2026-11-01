# Micro-Trader — Tagesverifikation 06.08.2026 (21:35)

## Status: ✅ ALLES LÄUFT (mit bekanntem Free-Tier-Limit)

### Heute repariert (v2.18.1 → v2.18.2):

**1. KI-Trading war lahmgelegt (v2.18.1)**
- Root-Cause: Cooldown-Blockade (ki_cooldown.json) + Reasoning-Modell-Problem
- Fix: Cooldown-Datei >6h auto-verworfen, _ki_call robust gegen leere Antworten, hy3 wieder in Rotation
- Verifiziert: KI entscheidet echte kaufen/verkaufen

**2. Scheduler intelligent getaktet (v2.18.2)**
- Root-Cause: 26 volle KI-Laeufe/Tag x ~90 Calls = 2340 Calls -> zen Free-Tier 429 (Rate-Limit) voll
- Fix: Engine (Daten) alle 15min, KI-Trading nur alle 120min (MT_KI_INTERVAL=120)
  -> ~3 KI-Laeufe/Tag = ~270 Calls (weit unter Limit)
- Verifiziert: Scheduler laeuft (PID 776), startet Pipeline korrekt

**3. Integritaetspruefung (v2.18.2)**
- pruefe_pipeline_ergebnis() warnt bei: Cooldown-Blockade, 0-Kursen, nur-"halten"-Fallback, Timeouts
- Verifiziert: Logging funktioniert

**4. Analyse-Datenbank SQLite (v2.18.2)**
- micro_trader.db + db.py: spiegelt alle JSONs nach jedem Lauf
- Tabellen: trades (926), ki_decisions (123), depot_snapshot (534), markt_daten
- Pipeline sync't automatisch (DB-Sync OK im Log)
- Verifiziert: Schnelles Auslesen funktioniert (trades_nach_typ, ki_aktionen_vert)

**5. Provider-Rotation repariert (ki_provider.py)**
- Root-Cause: bei rate_limit eines Providers wurden ALLE als "timeout" gekuehlt (Blockade verschlimmert)
- Fix: nur den rate-limiteten Provider kuehlen, Rotation macht mit naechstem weiter
- Verifiziert: nous-step genutzt als zen rate-limited war

### Bekanntes Limit (kein Bug, sondern Free-Tier):
- zen (OpenCode Zen Free) ist haeufig rate-limited (429) -> KI-Trading manchmal
  fuer 10-30min blockiert, erholt sich aber. Andere Provider (nous-*, openrouter)
  springen ein.
- Bei haeufigem Ausfall: besserer Provider (bezahlter Key) noetig.

### Cron-Jobs (Hermes):
- 3 Jobs pausiert seit 05.08 (Fallback), Scheduler uebernimmt alles

### Naechste Schritte (optional):
- Wenn zen dauerhaft zu viel 429 -> OpenRouter-Paid-Key oder nous-hy3 als Primaer
- DB kann fuer Dashboard/Auswertungen genutzt werden (schneller als JSON-Parsing)
