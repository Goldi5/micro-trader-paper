# Beispiel-Units für systemd

Vorlagen, um Micro-Trader dauerhaft auf einem Linux-Server zu betreiben. Pfad `/opt/micro-trader`, Benutzer `microtrader`, Port 5300 sind Beispiele und müssen angepasst werden.

| Unit | Aufgabe |
|---|---|
| `micro-trader.service` | Dashboard (nur 127.0.0.1; Zugriff von außen über Reverse-Proxy/VPN) |
| `mt-scheduler.service` | Taktgeber für die Handelsläufe |
| `micro-trader-proxy.service` | Node-Proxy für Depot-Abfragen |
| `mt-watchdog.timer` | Überwachung und Alarme (alle 30 min) |
| `mt-screener.timer` | Kandidaten-Screener (sonntags) |
| `mt-retention.timer` | Datenbank aufräumen (täglich) |
| `modell-scout.timer` | verfügbare KI-Modelle prüfen (stündlich) |

Einrichten:

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now micro-trader mt-scheduler micro-trader-proxy
sudo systemctl enable --now mt-watchdog.timer mt-screener.timer mt-retention.timer modell-scout.timer
```

Den Handel steuert allein `mt-scheduler`. Keinen zweiten Taktgeber parallel einrichten (z. B. die Pipeline zusätzlich per Timer), sonst laufen Handelsläufe doppelt.
