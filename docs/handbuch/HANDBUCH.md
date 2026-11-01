# Micro-Trader – Handbuch

Funktionen, Bedienung und Betrieb. Dieses Handbuch wird bei jedem Release automatisch als PDF neu erzeugt.

## 1. Überblick

Micro-Trader ist eine KI-unterstützte **Paper-Trading-Plattform**. Sie handelt ausschließlich mit virtuellem Geld. Echte Orders sind technisch gesperrt (Modus `PAPER_ONLY`, Kill-Switch in `live_system.py`).

Grundprinzip: **Die KI schlägt vor, deterministische Regeln entscheiden.** Jede Order läuft durch den zentralen Risiko-Controller (`risk_controller.py`). Er kann jeden KI-Vorschlag ablehnen oder verkleinern.

Micro-Trader läuft auf einem Linux-Server (z. B. VM oder Container) unter `/opt/micro-trader`, gesteuert über systemd. Der Code liegt öffentlich auf GitHub (`Goldi5/micro-trader-paper`).

## 2. Depotarten

| Depotart | Dateien | Trader | Inhalt |
|---|---|---|---|
| Aktien | `depot_<risk>_paper.json` | `batch_trader.py` | Risikoleiter mit 7 Stufen (Risk 10, 25, 40, 55, 70, 85, 95), Kandidaten aus dem Screener |
| ETF | `etf_<risk>_paper.json` | `etf_trader.py` | 10 Testdepots (Risk 0–90) à 200 €, ETF-Auswahl nach selbst berechnetem Beta |
| Spekulation | `spec_depots_paper/<TICKER>.json` | `spec_trader.py` | Ein Depot je Instrument (Start 100), Risikostufe aus der Kategorie |

Die Risikostufe (0–95) bestimmt Positionsgröße, maximale Positionsanzahl, erlaubte Tiers (Aktien, ETF, Hebel, Penny), Stop-Loss, Take-Profit und die Drawdown-Grenze.

## 3. Ablauf eines Handelslaufs

1. **Taktgeber:** Der Scheduler (`micro_trader_scheduler.py --loop`, Dienst `mt-scheduler`) läuft alle 15 Minuten.
2. **Pipeline** (`micro-trader-pipeline.py`):
   - `engine`: News, Spec-Watch, Marktdaten. Ohne KI.
   - `ki`/`full`: Spec-, ETF- und Aktien-Trader, Lernen und Reflexion. Nur bei offener US-Börse.
3. **Trader je Depot:**
   1. **Harte Ausstiege zuerst** (`exits.py`): Stop-Loss, Trailing-Stop und Take-Profit. Ein ausgelöster Ausstieg hat Vorrang vor der KI.
   2. **KI-Entscheidung:** ein gebündelter Aufruf für alle Depots, mit Kontext (Konzentration, Sektor, Fundamentaldaten, gelernte Regeln). Antworten werden 1 h zwischengespeichert. Gespeicherte Aktionen werden **nicht** erneut ausgeführt.
   3. **Earnings-Sperre** (`earnings.py`): kein Neukauf ≤ 2 Tage vor Quartalszahlen.
   4. **Risiko-Controller:** Kurs gültig, Drawdown-Sperre, Tier erlaubt, Positionslimit, Penny-Limit, Mindest-Score, Cash-Boden, Betragsgrenze (inkl. Hebel-Deckel).
   5. **Ausführung mit Handelskosten** (`handelskosten.py`): Gebühr und Slippage. Der Einstand enthält die Kosten.
4. **Protokoll:** Trades und Blockaden mit Grund in der Depot-Datei, Ereignisse in `logs/` (`mtlog`), KI-Aufrufe in `ki_aufrufe.jsonl`.

## 4. Risikomanagement

- **Zentrale Prüfung:** `risk_controller.pruefe_und_bremse()` ist der einzige Eintritt für Käufe. Jeder Zweig liefert einen Grund (z. B. `tier_gesperrt`, `positionslimit`, `betrag_ueber_limit`).
- **Kurs 0 ist kein Kurs:** Liefert die Kursquelle 0 (z. B. bei einem Rate-Limit), wird nicht gehandelt. Positionen werden dann zum Einstand bewertet, damit keine falsche Drawdown-Sperre entsteht.
- **Drawdown-Sperre:** Fällt ein Depot um mehr als die Grenze seiner Risikostufe unter sein Hoch, wird es eingefroren. Der Watchdog meldet das per ntfy.
- **Stop-Loss / Trailing-Stop:** Der Stop beginnt beim Faktor der Risikostufe (z. B. 0,92 = 8 % unter Einstand) und zieht mit dem Höchstkurs seit Kauf nach. Er sinkt nie.
- **Konzentrations-Bremse:** Ein Titel darf nur in begrenzt vielen Depots gleichzeitig liegen (`engine_bremsen.max_depot_pro_ticker`).

## 5. KI

- **Anbieter-Rotation** (`ki_provider.py`): Pool aus Free-Tier-Anbietern (u. a. OpenRouter, Nous, Zen) mit Round-Robin, Cooldown bei Fehlern und Fail-Fast.
- **Kennzahlen:** Jeder Aufruf wird in `ki_aufrufe.jsonl` protokolliert (Anbieter, Erfolg, Dauer). Der Tagesbericht zeigt Ausfallquote und Anbieter der letzten 24 h. Bei ≥ 50 % Ausfall in 2 h alarmiert der Watchdog.
- **Lernen:** `ki_learning.py` bewertet vergangene Entscheidungen und pflegt gewichtete Regeln (`learned_rules.json`).
- **Reflexion:** Der Wochenbericht (`ki_reflexion.py`) läuft sonntags einmal und schlägt neue Regeln vor (`pending_rules.json`).

## 6. Dashboard

- Das Dashboard läuft auf dem Port aus der systemd-Unit (Beispiel: 5300) und bindet aus Sicherheitsgründen nur an `127.0.0.1`. Zugriff von außen nur über einen Reverse-Proxy oder ein VPN (z. B. Tailscale), nie direkt ins Internet.
- Anmeldung mit Benutzer und Passwort, für Admins mit MFA (TOTP). Sitzungen laufen nach 30 min Inaktivität bzw. spätestens nach 8 h ab.
- Bereiche: Depots (Aktien/ETF/Spec), Potenzial, Börsenzeiten, KI-Log, Regeln, Ops-Center, Einstellungen, Admin.
- Einstellungen werden im Dashboard validiert. Werte außerhalb des empfohlenen Bereichs erzeugen eine Risikowarnung.

## 7. Tagesbericht

`report_pdf.py` erzeugt nach US-Börsenschluss einmal täglich ein PDF und versendet es per E-Mail (SMTP aus `.env`). Inhalt:

- Depotwerte je Kategorie, Top/Flop, Verlauf
- Performance & P&L inkl. Gebühren, Slippage und Netto-P&L
- **Benchmark:** alle Depots und je Kategorie gegen Buy & Hold SPY seit dem ersten Trade
- KI-Aufrufe der letzten 24 h, Risiko, Governance, Systemstatus

## 8. Einstellungen (`settings.json`)

Fehlende Abschnitte nutzen die Standardwerte aus dem Code.

| Abschnitt | Wichtige Felder | Standard |
|---|---|---|
| `ki` | `konfidenz_cap`, `min_konfidenz_kaufen`, `ki_temperatur` | 60 / 60 / 0,1 |
| `engine_bremsen` | `max_depot_pro_ticker`, `drawdown_sperre_prozent`, `wochenende_handel` | 8 / 30 / aus |
| `handelskosten` | `aktiv`, `gebuehr_fix`, `gebuehr_prozent`, `slippage_prozent`, `max_gebuehr_anteil_prozent` | an / 1,00 / 0 / ETF 0,05 · Aktie 0,10 · spekulativ 0,30 % / – |
| `trailing_stop` | `aktiv` | an |
| `earnings_sperre` | `aktiv`, `tage_vorher` | an / 2 |
| `kapital` | `gesamt_budget`, Anteile Aktien/ETF/Spec | 10000 / 40 · 30 · 30 |

Beispiel, um die Gebühr an einen Broker ohne Ordergebühr anzupassen:

```
"handelskosten": {"gebuehr_fix": 0.0}
```

## 9. Betrieb

### Installation

```
git clone https://github.com/Goldi5/micro-trader-paper.git /opt/micro-trader
cd /opt/micro-trader
python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

Danach `.env` mit den Zugangsdaten anlegen (KI-Anbieter, optional SMTP) und die Dienste einrichten. Vorlagen für systemd liegen in `deploy/systemd/` (Dashboard, Scheduler, Proxy, Watchdog, Screener, Datenbank-Aufräumen, Modell-Scout), siehe `deploy/systemd/README.md`.

Den Handel steuert allein der Scheduler (`mt-scheduler`). Er startet die Pipeline alle 15 Minuten, bei offener US-Börse abwechselnd als KI-Welle für einen der drei Trader. Kein zweiter Taktgeber parallel, sonst laufen Handelsläufe doppelt.

### Update einspielen

Änderungen kommen ausschließlich über GitHub:

1. Pull Request auf GitHub prüfen und mergen.
2. Auf dem Server:

```
cd /opt/micro-trader && ./deploy.sh
```

`deploy.sh` zeigt die neuen Commits und fragt nach. Danach spielt es den Stand per Fast-Forward ein und installiert geänderte Pakete. Anschließend prüft es Syntax und Offline-Tests und startet erst dann die Dienste neu. Dateien, die ein Update aus Git entfernt (Laufzeitdaten), werden vorher gesichert und danach wieder hingelegt (`~/mt-deploy-sicherung/`). Schlägt eine Prüfung fehl, bricht es **vor** dem Neustart ab.

**Nicht** `git pull` verwenden. Das würde Laufzeitdateien löschen, die Git verlassen.

### Tests

```
./run_tests.sh          # Offline-Tests in einer Wegwerf-Kopie (kein Netz, keine Live-Daten)
./run_tests.sh alle     # alle Tests mit einer Kopie der aktuellen Live-Daten
```

Die Tests liegen in `tests/` und laufen nie im Live-Ordner. GitHub führt bei jedem Push pyflakes (undefinierte Namen) und die Offline-Tests aus.

### Logs

- `journalctl -u mt-scheduler -u micro-trader -n 50`
- `cron_pipeline.log` (Pipeline), `watchdog.log`, `logs/` (strukturierte Ereignisse, `mtlog_query.py`)

## 10. Überwachung und Alarme

`mt_watchdog.py` prüft alle 30 Minuten und sendet bei Problemen eine Push-Nachricht über ntfy (Topic in `.watchdog_ntfy_topic`):

- Trader arbeitet während der Marktzeit nicht (keine KI-Entscheidung und kein Trade seit 48 h)
- `mt-scheduler` läuft nicht
- kaum Datenbank-Schreibvorgänge, Festplatte ≥ 85 %
- KI-Ausfallquote ≥ 50 % in 2 h
- Depot neu gesperrt (Drawdown)

Einrichten: die App „ntfy“ installieren, ein langes zufälliges Topic abonnieren und denselben Namen in `.watchdog_ntfy_topic` eintragen. Testen mit `python3 mt_watchdog.py --force-alarm`.

## 11. Sicherheit

- Geheimnisse liegen nur auf dem Server, nie in Git: `.env` (API-Keys, SMTP), `security_users.json`, `.session_secret`, `.csrf_secret`, `.watchdog_ntfy_topic`, `nous_auth.json`, `wol-verify-config.json`.
- **Secret erneuern:** Datei löschen und Dienst neu starten. Sie wird mit Rechten 0600 neu erzeugt.

```
rm /opt/micro-trader/.csrf_secret /opt/micro-trader/.session_secret && systemctl restart micro-trader
```

- Dashboard und Proxy binden an `127.0.0.1`. Alle Formulare sind CSRF-geschützt, SQL-Sortierungen über eine Whitelist abgesichert.

## 12. Fehlerbehebung

| Symptom | Prüfen |
|---|---|
| Keine Trades | Börse offen? `journalctl -u mt-scheduler`, `tail cron_pipeline.log`, KI-Ausfallquote im Tagesbericht |
| Depot gesperrt | Drawdown im Dashboard; die Sperre ist gewollt, Freigabe nur bewusst |
| Viele „kauf_blockiert“ | Grund in der Depot-Datei: Betragsgrenze, Tier, Gebühren-Anteil, Earnings-Sperre |
| Dashboard nicht erreichbar | `systemctl status micro-trader`, Port 5300, Proxy |
| `deploy.sh` bricht ab | Ausgabe lesen; Rücksprung mit dem angezeigten `git reset --keep <commit>` |

## 13. Releases und Handbuch

- Ein Release entsteht auf GitHub über „Releases → Draft a new release“ mit einem Tag wie `v2.60.0`.
- Die GitHub-Action **Handbuch** erzeugt daraus automatisch `Micro-Trader-Handbuch-<version>.pdf` und hängt es an das Release. Bei jedem Push auf `main` wird das PDF zusätzlich als Download-Artefakt gebaut.
- `deploy.sh` erzeugt das PDF auch lokal unter `docs/handbuch/Micro-Trader-Handbuch.pdf`.
- **Pflege:** Dieses Handbuch ist die Quelle (`docs/handbuch/HANDBUCH.md`). Wer eine Funktion ändert, passt den passenden Abschnitt im selben Pull Request an.
- **README-Stand:** Nach jedem Push auf `main` schreibt die Action **README-Stand** Version, Datum und die letzten Änderungen in den Abschnitt „Letzter Stand“ der README (`tools/stand_aktualisieren.py`). Die Version kommt aus dem letzten Release-Tag, ersatzweise aus `version.json`.

## 14. Lizenz und Rechtliches

- Lizenz des Projekts: **AGPL-3.0-or-later**, Copyright © 2026 Goldi5 (`LICENSE`). Wer eine veränderte Fassung weitergibt oder als Netzwerkdienst anbietet, muss deren Quellcode offenlegen.
- Lizenzen der verwendeten Pakete: `THIRD_PARTY_LICENSES.md`. Nach einer Änderung an `requirements.txt` neu erzeugen mit `venv/bin/python tools/lizenzen.py`.
- Haftungsausschluss (keine Anlageberatung), Datenquellen und deren Nutzungsbedingungen, Marken: `RECHTLICHES.md`.
- Persönliche Werte stehen nie im Code, sondern in git-ignorierten Dateien bzw. Umgebungsvariablen:

| Wert | Ort |
|---|---|
| SMTP-Zugang und Empfänger | `.env` (`SMTP_USER`, `SMTP_PASS`, optional `SMTP_TO`) |
| Zusätzliche vertrauenswürdige Hosts (z. B. eigene Tailscale-IP) | `.trusted_hosts` oder `MICRO_TRADER_TRUSTED_HOSTS` |
| Taildrop-Ziel für Alarme | `.watchdog_ts_target` oder `MT_TS_TARGET` |
| ntfy-Topic | `.watchdog_ntfy_topic` |
| PC-Erkennung (IP, MAC, WhatsApp-Ziel) | `wol-verify-config.json` (Vorlage: `wol-verify-config.example.json`) |
| Host für das Fernabfrage-Werkzeug `proxy/generate_pdf_report.py` | `MT_PROXMOX_HOST` |
