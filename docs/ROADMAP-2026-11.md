# Micro-Trader – Review-Ergebnis und Roadmap (Stand 01.11.2026)

## 0. Umgesetzt am 01.11.2026 (zweiter PR)

| Idee | Modul | Einstellung in `settings.json` |
|---|---|---|
| Gebühren + Slippage (4.1) | `handelskosten.py` | `handelskosten`: `aktiv`, `gebuehr_fix` (1.00), `gebuehr_prozent`, `slippage_prozent`, `max_gebuehr_anteil_prozent` |
| Harte Stop-Loss/Take-Profit für Aktien-Depots + Trailing-Stop (4.7) | `exits.py` | `trailing_stop`: `aktiv` |
| Earnings-Sperre (4.8) | `earnings.py` | `earnings_sperre`: `aktiv`, `tage_vorher` (2) |
| Benchmark SPY + echte Gebühren im Tagesbericht (4.3) | `performance.py`, `report_pdf.py` | – |
| KI-Kennzahlen (4.5) | `ki_aufrufe.jsonl`, `performance.ki_kennzahlen()` | – |
| Alarm bei KI-Ausfall und gesperrten Depots (5) | `mt_watchdog.py` (ntfy) | Topic in `.watchdog_ntfy_topic` |

Alle Abschnitte fehlen in `settings.json` und nutzen die Standardwerte; zum Abschalten z. B.
`"handelskosten": {"aktiv": false}` eintragen.

## 1. Was im Review behoben wurde (PR „claude/stoic-babbage-hp7prx“)

| # | Befund | Wirkung bisher | Datei |
|---|---|---|---|
| 1 | KI-Aktionen aus dem 1-h-Cache wurden bei jedem weiteren Lauf **erneut ausgeführt**; im Pipeline-Modus `full` lief `batch_trader` zudem zweimal direkt hintereinander | Käufe/Verkäufe konnten doppelt gehandelt werden | `batch_trader.py`, `micro-trader-pipeline.py` |
| 2 | `rc`/`strategie_bt` nie importiert → Hebel-Erkennung fiel in `except: _hebel_c = True` | **Jeder** Kauf wurde wie ein Hebel-ETF um ~15 % verkleinert | `batch_trader.py` |
| 3 | `def selbst_statistik_text` fehlte → gemeinsamer Import scheiterte | KI-Prompt ohne Kontext-Block (Konzentration, Sektor, Fundamentals) | `ki_kontext.py` |
| 4 | Kurs 0 (Rate-Limit) zählte Positionen mit 0 € | Depotwert brach rechnerisch ein, **Drawdown-Sperre** konnte auslösen (Spec-Depots dauerhaft) | `engine.py`, `spec_trader.py`, `etf_trader.py` |
| 5 | Verkauf über Bestand schrieb Bargeld gut; KI-Verkauf bei Kurs 0 im Spec-Trader | Bargeld aus dem Nichts bzw. Position für 0 € weg | `engine.py`, `spec_trader.py` |
| 6 | Wochenbericht lief sonntags in jedem 15-min-Durchlauf | bis zu 96× Regelübernahme | `micro_trader_scheduler.py` |
| 7 | Liquiditätsfilter `MIN_ADV_MIO` griff nie (Ticker fehlte) | illiquide Titel nicht ausgefiltert | `depot_daten.py` |
| 8 | Jev-Gate las Variable vor Zuweisung | Gate wirkungslos (nur mit `MT_JEV_GATE=1`) | `batch_trader.py` |
| 9 | Weitere stille NameErrors | Dashboard-Routen `ops_news`, `live_status`, `live-requests` defekt; `regel_history.json` nie geschrieben | diverse |
| 10 | Depot-Dateien nicht atomar geschrieben | Abbruch = halbe JSON-Datei | `engine.py`, `spec_trader.py`, `etf_trader.py` |
| 11 | Tests arbeiteten auf Live-Daten (`/opt/micro-trader` fest) | Tests veränderten z. B. die echte `config.json` | 33 Tests, 10 Module |

Neu: `deploy.sh`, `run_tests.sh`, `requirements.txt`, GitHub Action (pyflakes + 24 Offline-Tests).

## 2. Nächste Schritte im Betrieb (brauchen den LXC)

1. **`mt-gate` prüfen.** Das Skript `micro-trader-scheduler-gate.py` ist für Windows geschrieben
   (`creationflags=CREATE_NEW_PROCESS_GROUP`, `BASE=~/projects/...`) und kann unter Linux keine Pipeline
   starten. Den Handel steuert ohnehin `mt-scheduler`. Prüfen mit
   `systemctl cat mt-gate.service` und `journalctl -u mt-gate -n 30`. Vermutlich sollte der Timer
   **deaktiviert** werden: `systemctl disable --now mt-gate.timer`.
   Achtung: Würde das Skript repariert, liefe die Pipeline doppelt (Gate + Scheduler).
2. **`mt-kiwatch`** startet alle 30 min `micro-trader-pipeline.py`. Falls ohne `--mode` (= `full`), läuft das **zusätzlich**
   zum Scheduler (der `ki_welle` startet). Mit Fix #1 wird nicht mehr doppelt gehandelt, aber es laufen
   unnötig viele KI-Calls. Entscheiden: kiwatch auf `--mode engine` umstellen oder abschalten.
3. **`PYTHONUNBUFFERED=1`** in den systemd-Units setzen, damit Log-Zeilen sofort mit korrekter Zeit im Journal stehen
   (die 52 Zeilen „in 10 Sekunden“ waren gepufferte Ausgabe).
4. **Laufzeitdateien aus Git nehmen** (eigener PR, *nachdem* das neue `deploy.sh` auf dem LXC liegt):
   `ki_regeln.json`, `learned_rules.json`, `pending_rules.json`, `.watchdog_state.json`,
   `.beta_stock_cache.json`, `screener_aktien_beta.json`, `konfidenz_stats.json`, `regel_history.json`,
   `reflexion_summary_*.md`, `audit/`. `deploy.sh` sichert und restauriert sie dabei automatisch.
5. **`./run_tests.sh alle`** einmal auf dem LXC laufen lassen und die 13 Tests mit Live-Daten bewerten.

## 3. Code-Qualität

- **230× `except …: pass`.** Genau dort haben sich die gefundenen Fehler versteckt. Schrittweise durch
  `except Exception as e: mtlog.warn(...)` ersetzen, beginnend in `batch_trader.py`, `engine.py`, `ki_decisions.py`.
- **`batch_trader.main()`** ist eine Funktion mit über 1000 Zeilen. In Schritte zerlegen
  (Kontext sammeln → KI fragen → Aktionen bauen → ausführen), dann ist jeder Schritt einzeln testbar.
- **`dashboard.py` (≈5000 Zeilen)** in Flask-Blueprints aufteilen (Depots, Ops, Security, Live).
- **Hartkodierte Pfade** in den restlichen Werkzeugen (`depot_bauen.py`, `leiter_hart.py`, …) wie in diesem PR
  auf „Ordner der Datei“ umstellen.
- **Gemeinsames `speichere_json_atomar()`** statt verteilter `json.dump(...)`-Aufrufe (91 Stellen, die meisten nicht atomar).
- **`version.json`** automatisch aus `git describe` erzeugen statt von Hand (steht noch auf 2.58.7 vom 14.08.).

## 4. Trading – Ideen mit dem größten Nutzen

1. **Gebühren und Slippage simulieren.** Aktuell nicht erhoben (Bericht: „n/a“). Bei 200-€-Depots und
   Positionen von 30–70 € kostet ein echter Broker mit ≈1 € je Order 1,5–3 % **pro Kauf**. Ohne diese
   Kosten sind alle Paper-Ergebnisse geschönt. Umsetzung: `kosten = max(min_gebuehr, betrag * satz)` +
   Slippage (z. B. 0,05 % ETF, 0,2 % Small Caps) zentral in `engine.ausfuehren()`/`spec_trader`/`etf_trader`.
2. **Währung.** Budgets sind in Euro, Kurse in US-Dollar. Es gibt keine Umrechnung. Entweder Depots
   konsequent in USD führen oder EURUSD (`EURUSD=X`) beim Kauf/Verkauf und in der Bewertung einrechnen.
   Das Währungsrisiko ist sonst unsichtbar.
3. **Benchmark im Tagesbericht.** `performance.benchmark_kennzahlen()` existiert schon. Jede Depotreihe gegen
   Buy & Hold (z. B. SPY oder MSCI World) stellen: Rendite, Sharpe, max. Drawdown. Erst damit lässt sich
   beantworten, ob die KI Mehrwert bringt.
4. **Backtest-Modus.** Die Engine und `risk_controller` mit historischen Kursen laufen lassen
   (`.kurs_cache_2y.json` ist vorhanden). Neue Regeln, `min_score` oder Positionsgrößen erst im Backtest
   bestätigen, dann in die Paper-Depots übernehmen.
5. **KI messbar machen.** Pro Provider/Modell: Fallback-Quote („halten“ wegen Ausfall), Trefferquote
   (Lerneffekt), Antwortzeit, Kosten. Als Kachel im Dashboard und Zeile im Tagesbericht.
6. **Kontrollgruppe.** Die Shadow-Depots als regelbasierte Kontrollgruppe ohne KI führen. Gleiche Kandidaten,
   gleiche Risiko-Regeln, nur ohne KI-Entscheidung. Der Unterschied ist der KI-Effekt.
7. **Trailing-Stop** statt festem Stop-Loss (z. B. 8 % unter dem Höchstkurs seit Kauf), damit Gewinne nicht
   wieder abgegeben werden.
8. **Earnings-Sperre.** Keine Neukäufe 2 Tage vor Quartalszahlen (Termine über `yfinance.Ticker.calendar`).

## 5. Betrieb und Überwachung

- **Push-Benachrichtigung** bei Fehlern (z. B. ntfy oder Telegram): Pipeline-Abbruch, Provider-Ausfall,
  Drawdown-Sperre, fehlende Kurse > 30 min.
- **Tägliches Backup** von `micro_trader.db` und den Depot-Dateien auf den Proxmox-Host
  (z. B. per `vzdump` des LXC oder `sqlite3 .backup`).
- **Health-Check-Seite** mit Status aller Timer und Dienste und dem Zeitpunkt des letzten erfolgreichen Laufs.

## 6. Später: Live-Handel

Erst sinnvoll, wenn Punkt 4.1–4.3 über mehrere Wochen ein positives Bild *nach Kosten* zeigen. Dann z. B.
ein Broker mit Paper-API (Alpaca) als Zwischenstufe. Kill-Switch und Freigabeprozess sind bereits vorbereitet.
