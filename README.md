# Micro-Trader

**KI-unterstützte Paper-Trading-Plattform mit deterministischem Risikomanagement.**

> **Die KI schlägt vor – deterministische Regeln entscheiden, was tatsächlich gehandelt wird.**

[![Tests](../../actions/workflows/tests.yml/badge.svg)](../../actions/workflows/tests.yml)

📘 **Handbuch** (Funktionen, Bedienung, Betrieb): [`docs/handbuch/HANDBUCH.md`](docs/handbuch/HANDBUCH.md).
Als PDF hängt es an jedem [Release](../../releases) und wird bei jedem Deploy unter `docs/handbuch/Micro-Trader-Handbuch.pdf` erzeugt.

> ⚠️ **Keine Anlageberatung.** Privates Paper-Trading-Projekt mit virtuellem Geld, ohne Gewährleistung. Details: [`RECHTLICHES.md`](RECHTLICHES.md).

<!-- STAND:START -->
## Letzter Stand

| Version | Stand | Commit |
|---|---|---|
| 2.60.0 | 01.11.2026 21:02 | `b9a13fc` |

Letzte Änderungen:

- 01.11.2026 – Micro-Trader v2.60.0 – erste öffentliche Fassung

_Dieser Abschnitt wird bei jedem Update automatisch erzeugt (`tools/stand_aktualisieren.py`)._
<!-- STAND:END -->

---

## Status

| Bereich | Stand |
|---|---|
| Paper-Trading | 🟢 aktiv (Aktien-, ETF- und Spekulations-Depots) |
| Live-Trading | 🔴 gesperrt (`PAPER_ONLY`, Kill-Switch) |
| Risiko-Controller | 🟢 zentrale Prüfung vor jedem Kauf |
| Stop-Loss / Trailing-Stop / Take-Profit | 🟢 in allen Depotarten (`exits.py`) |
| Handelskosten (Gebühr + Slippage) | 🟢 simuliert (`handelskosten.py`) |
| KI | 🟢 Anbieter-Rotation, Kennzahlen je Aufruf |
| KI-Lernen | 🟡 experimentell |
| Tests | 🟢 Offline-Tests + pyflakes in GitHub Actions |

Offene Punkte und Ideen: [`docs/ROADMAP-2026-11.md`](docs/ROADMAP-2026-11.md).

## So funktioniert es

```
Scheduler / Pipeline ──► Trader je Depotart
                           1. harte Ausstiege (Stop-Loss, Trailing-Stop, Take-Profit)
                           2. KI-Entscheidung (Kontext, gelernte Regeln)
                           3. Earnings-Sperre
                           4. Risiko-Controller (Tier, Positionen, Betrag, Drawdown …)
                           5. Ausführung mit Gebühr + Slippage (Paper)
                       ──► Depot-Dateien, SQLite, Logs ──► Tagesbericht (PDF) · Dashboard · Alarme
```

| Depotart | Trader | Depots |
|---|---|---|
| Aktien | `batch_trader.py` | Risikoleiter, 7 Stufen (Risk 10–95) |
| ETF | `etf_trader.py` | 10 Testdepots (Risk 0–90) |
| Spekulation | `spec_trader.py` | ein Depot je Instrument |

## Wichtige Dateien

| Datei | Aufgabe |
|---|---|
| `micro_trader_scheduler.py`, `micro-trader-pipeline.py` | Taktgeber und Ablauf |
| `engine.py` | Depot-Modell, Kauf/Verkauf, Bewertung |
| `risk_controller.py`, `risk_profile.py`, `strategie.py` | Risikoregeln je Stufe |
| `exits.py`, `handelskosten.py`, `earnings.py` | Ausstiege, Kosten, Earnings-Sperre |
| `ki_provider.py`, `ki_decisions.py`, `ki_learning.py`, `ki_reflexion.py` | KI-Anbindung, Entscheidungen, Lernen |
| `dashboard.py`, `security.py` | Web-Oberfläche, Login/MFA/CSRF |
| `report_pdf.py`, `performance.py` | Tagesbericht, Kennzahlen, Benchmark |
| `mt_watchdog.py` | Überwachung, ntfy-Alarme |
| `deploy.sh`, `run_tests.sh` | Update einspielen, Tests in Wegwerf-Kopie |
| `tools/handbuch_pdf.py` | Handbuch-PDF erzeugen |
| `settings.json` | Einstellungen (siehe Handbuch, Kapitel 8) |

Ordner: `tests/` (alle Tests), `tools/` (Hilfsskripte), `docs/` (Handbuch, Roadmap, Fachdokumente, `docs/historie/` = ältere Übergaben), `proxy/`, `static/`, `assets/`, `archiv/` (abgelegter Code, u. a. ungenutzte Einmal-Werkzeuge).

## Installation und Betrieb

```bash
git clone https://github.com/Goldi5/micro-trader-paper.git /opt/micro-trader
cd /opt/micro-trader
python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

- Zugangsdaten in `.env` eintragen, Dienste mit den Vorlagen aus [`deploy/systemd/`](deploy/systemd/) einrichten.
- Updates einspielen mit `./deploy.sh`: Es zeigt die Änderungen, testet und startet die Dienste erst danach neu. Laufzeitdaten bleiben erhalten.
- Tests mit `./run_tests.sh`: Sie laufen in einer Wegwerf-Kopie und fassen keine Live-Daten an.

Details: Handbuch, Kapitel 9–12.

## Entwicklung

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
./run_tests.sh
```

- Änderungen über Pull Requests; GitHub Actions prüft pyflakes und Offline-Tests.
- Neue Laufzeitdateien in `.gitignore` eintragen. Geheimnisse (`.env`, `*_secret`, `security_users.json`, `.watchdog_ntfy_topic`, `wol-verify-config.json`) gehören nie ins Repo.
- Wer eine Funktion ändert, passt das Handbuch (`docs/handbuch/HANDBUCH.md`) im selben Pull Request an.

## Releases

Auf GitHub „Releases → Draft a new release“, Tag z. B. `v2.60.0`. Die Action **Handbuch** hängt automatisch `Micro-Trader-Handbuch-<version>.pdf` an.

## Lizenz und Rechtliches

Copyright © 2026 Goldi5. Micro-Trader ist freie Software unter der **GNU Affero General Public License v3.0 oder später** (AGPL-3.0-or-later).
Kurz: Du darfst den Code nutzen, ändern und weitergeben. Wer eine veränderte Fassung weitergibt **oder als Dienst über ein Netzwerk anbietet** (z. B. ein Dashboard für andere), muss den Quellcode seiner Änderungen unter derselben Lizenz offenlegen.

- Lizenztext: [`LICENSE`](LICENSE)
- Verwendete Pakete und deren Lizenzen: [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) (erzeugt mit `tools/lizenzen.py`)
- Haftungsausschluss, Datenquellen, Marken: [`RECHTLICHES.md`](RECHTLICHES.md)
