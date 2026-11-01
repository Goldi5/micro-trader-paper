# PROVIDER-INVENTORY.md

> **Provider-Bestandsaufnahme Micro-Trader** · Stand: 2026-08-08 · v2.25.1
> Erstellt im Rahmen von **PHASE 0** des Mandanten-Ausbauauftrags.

---

## 1. Übersicht

| Kategorie | Provider | Zweck | Global/User |
|-----------|----------|-------|-------------|
| Marktdaten | yfinance | Primärer Kursbezug (frei) | ⚠️ global |
| Marktdaten | Finnhub | Fallback bei yfinance-Drossel | ⚠️ global (Key) |
| Marktdaten | TwelveData | Fallback | ⚠️ global (Key) |
| Marktdaten | AlphaVantage | Fallback | ⚠️ global (Key) |
| KI | Nous (nous_auth) | KI-Entscheidungen | ⚠️ global |
| KI | OpenAI | KI-Entscheidungen (Fallback) | ⚠️ global |
| KI | Deepseek / opencode | KI-Entscheidungen (Rotation) | ⚠️ global |
| Broker/Execution | — | **Keiner vorhanden** | — |

**Kernbefund:** Alle Provider sind **global konfiguriert** — es gibt keine Connection-Tabelle,
keine user-/tenantbezogenen Verbindungen, keine Umgebungs-Trennung (DEMO/PAPER/SANDBOX/LIVE).

---

## 2. Marktdaten-Provider (`marktdaten.py`)

### 2.1 Datenfluss

```
hole_kurs(ticker, ...)
  → _yfinance_kurs (primär)
  → bei Fehler/Drossel: _finnhub_kurs → _twelvedata_kurs → _alphavantage_kurs
  → _gedrosselt/_setze_drossel (Rate-Limit-Schutz pro Provider)
  → scan_fallback_yfinance (Watchlist-Scan-Fallback)
```

### 2.2 Key-Verwaltung

| Key | Quelle | Speicherort | Git? |
|-----|--------|-------------|------|
| `FINNHUB_KEY` | `.env` → `os.environ` | `.env` (Zeile 23 marktdaten.py) | ❌ gitignored |
| `TWELVEDATA_KEY` | `.env` → `os.environ` | `.env` (Zeile 24) | ❌ gitignored |
| `ALPHAVANTAGE_KEY` | `.env` → `os.environ` | `.env` (Zeile 25) | ❌ gitignored |

- Keys werden **global** beim Import gelesen (`os.environ.get(...)`).
- **Kein Secret-Store**, keine Verschlüsselung, keine Rotation, keine Tenant-Trennung.

### 2.3 Rate-Limit / Drosselung
- `_gedrosselt`/`_setze_drossel`: pro Provider temporäre Drossel bei Fehlern (in-memory).
- Kein persistenter Rate-Limit-State, keine Quota pro User/Tenant.

---

## 3. KI-Provider (`ki_provider.py`)

### 3.1 Funktionen

| Funktion | Zweck |
|----------|-------|
| `call_ki(prompt, ...)` | Standard-KI-Call |
| `call_ki_batched(...)` | Batch-Verarbeitung (mehrere Antworten) |
| `call_ki_chat(...)` | Chat-Modus |
| `call_ki_cron(...)` | Cron-Pipeline-Call |
| `_call_ki_with_pool(...)` | Provider-Pool mit Fallback-Kette |
| `_baue_provider_liste*` | 3 Listen: chat / cron / batch (Rotation) |
| `_nous_creds` / `_nous_refresh` | Nous-Auth-Credentials + Refresh |
| `_cooldown_laden` / `_cooldown_speichern` | KI-Cooldown (`ki_cooldown.json`) |
| `_fehler_klassifizieren` | Fehlertyp (Rate-Limit/Auth/Timeout...) |
| `_provider_kalt` / `_setze_kalt` | Provider temporär kaltstellen |

### 3.2 Provider-Pool (Rotation)

| Provider | Typ | Credential-Quelle |
|----------|-----|-------------------|
| Nous (hermes) | chat/cron/batch | `nous_auth.json` (Hermes-Verbindung) |
| OpenAI | chat/cron | OpenAI-Key (Hermes/Config) |
| Deepseek (opencode) | chat/cron | opencode-Auth |
| Weitere Free-Modelle | Fallback-Kette | ki_provider-Config |

### 3.3 Bewertung
- ✅ Gute Fallback-Kette + Cooldown + Fehlerklassifikation (stabiler Betrieb)
- ⚠️ **Alle global** — kein userbezogener Provider, keine Modellwahl pro Tenant
- ⚠️ Keys teils in Hermes-Config (nous_auth.json), teils .env — **keine zentrale Secret-Verwaltung**

---

## 4. Broker / Execution

| Adapter | Status |
|---------|--------|
| Simulator/Paper | ✅ Intern (engine.py/trader.py/spec_trader.py simulieren Orders in SQLite `trades`) |
| Sandbox/Demo-Broker | ❌ Nicht vorhanden |
| Live-Adapter | ❌ Nicht vorhanden (gewollt — PAPER_ONLY) |

**Kein Broker-Code, keine Exchange-API-Keys, keine Order-Route nach außen.**

---

## 5. Weitere Dienste

| Dienst | Datei | Zweck |
|--------|-------|-------|
| WhatsApp | `whatsapp_config.json` | Benachrichtigungen (Bridge auf Port 3000) |
| Backup | `backup.py` | Backup-System (`.backup/`) |
| Watchdog | `whatsapp_watchdog.py` | Gateway-Reconnect (Autostart deaktiviert 08.08.) |
| Scheduler | `micro_trader_scheduler.py` | Pipeline-Scheduler (Autostart deaktiviert 08.08.) |

---

## 6. Ziel-Architektur (aus Auftrag §10-11)

Für Phase 5+ nötig:

```text
MarketDataProvider (Interface)
  ├── YahooAdapter
  ├── FinnhubAdapter
  ├── TwelveDataAdapter
  └── AlphaVantageAdapter

BrokerProvider / ExecutionProvider (Interface)
  ├── PaperSimulator (zuerst)
  ├── SandboxAdapter (danach)
  └── LiveAdapter (erst zuletzt, gated)

SecretStore (pro Tenant/User)
  ├── OS-Secret-Store / Vault (Priorität 1)
  ├── verschlüsselte DB (Priorität 2)
  └── NIEMALS Klartext in Git/JSON/Logs
```

Jede Verbindung braucht: `id, tenant_id, workspace_id, user_id, provider_type, provider_name,
environment (DEMO/PAPER/SANDBOX/LIVE), status, permissions, secret_reference, rate_limit, last_test_at, last_error`.

**Regeln:**
- LIVE-Verbindung nie automatisch in PAPER verwenden und umgekehrt
- API-Keys nie vollständig anzeigen (nur `••••ABCD`)
- Keys pro Tenant/User trennen — nie global teilen
- Kein Klartext in Audit-Logs

---

## 7. Offene Punkte / Empfehlung

| # | Punkt | Phase |
|---|-------|-------|
| 1 | Provider-Connection-Tabelle + Interface-Abstraktion | Phase 5 |
| 2 | Secret-Manager (mind. verschlüsselte JSON-Datei, ideal OS-Store) | Phase 5 |
| 3 | Umgebungs-Trennung DEMO/PAPER/SANDBOX/LIVE | Phase 5 |
| 4 | Paper-Simulator-Broker-Adapter | Phase 6/9 |
| 5 | Key-Rotation + Masking in UI | Phase 5/8 |
| 6 | Tenant-bezogene Providerwahl | Phase 5 |

**Harte Grenze:** Kein Live-Key, kein Live-Broker, keine echte Order — bis alle Phasen 1-17 abgeschlossen und getestet sind.
