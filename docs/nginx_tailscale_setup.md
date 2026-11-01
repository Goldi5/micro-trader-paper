# nginx + Tailscale-Funnel Konfiguration (Produktiv-Setup)

**Ziel:** Micro-Trader Dashboard sicher aus dem Internet erreichbar machen,
ohne den Flask-Server direkt zu exponieren.

**Architektur (aus HANDOFF-V3 §22):**
```
Internet → Tailscale Funnel (https://<ts-host>.ts.net)
         → nginx Reverse-Proxy (127.0.0.1:8080)
         → Flask (127.0.0.1:5300)
         → Authentication → Authorization → Tenant-Scope
```

## 1) nginx Reverse-Proxy (nginx.conf bzw. sites-available/micro-trader)

```nginx
server {
    listen 8080;
    server_name localhost;

    # Security-Headers (HSTS nur bei echtem HTTPS via Funnel)
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;

    location / {
        proxy_pass http://127.0.0.1:5300;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # WICHTIG für CSRF-Referer-Check (Phase 1 BUG-005):
        # Funnel/Proxy MUSS X-Forwarded-Host setzen, sonst CSRF blockt legitime Requests
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 60s;
    }

    # Static files direkt ausliefern (Performance)
    location /static/ {
        alias /opt/micro-trader/static/;
        expires 1d;
    }
}
```

**Wichtig:** `proxy_set_header X-Forwarded-Host $host;` ist PFLICHT, damit
`security.csrf_token_valid_for_request()` den lokalen Origin erkennt und
legitime Requests nicht mit 403 blockt (siehe BUG-005).

## 2) Tailscale Funnel aktivieren

```bash
# Auf dem Server:
sudo tailscale up --funnel 8080
# oder nur für die App:
sudo tailscale funnel 8080
```

Tailscale Funnel terminiert automatisch TLS (HTTPS) und leitet an
`127.0.0.1:8080` (nginx) weiter. Kein eigenes Zertifikat nötig.

## 3) Flask-Config (dashboard.py) — bleibt wie ist

```python
app.run(host="127.0.0.1", port=5300, debug=False, threaded=True)
```
Flask hört NUR auf localhost → nicht direkt im Internet erreichbar.
nginx/Tailscale machen den öffentlichen Teil.

## 4) CSRF beim Proxy (BUG-005 Update)

Da der Proxy `X-Forwarded-Host` setzt, erkennt `csrf_token_valid_for_request()`
die Requests als lokal. Fremd-Origin (kein X-Forwarded-Host vom Proxy) wird
weiterhin mit 403 blockiert. **Kein Code-Change nötig**, nur Header-Konfig.

## 5) HSTS (nach BUG-005-Doku)

Bei HTTPS via Funnel kann in nginx ergänzt werden:
```nginx
add_header Strict-Transport-Security "max-age=31536000" always;
```

## 6) Deployment am Sonntag (Server)

```bash
cd /opt/micro-trader
git pull origin main
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Scheduler als systemd-service starten (siehe micro-trader-scheduler.service)
sudo systemctl enable micro-trader-scheduler
sudo systemctl start micro-trader-scheduler
sudo nginx -t && sudo systemctl reload nginx
sudo tailscale up --funnel 8080
```

**Status:** Template fertig. Lokale Windows-Kiste braucht KEIN nginx (Dashboard
läuft direkt auf 127.0.0.1:5300). Erst auf dem Produktiv-Server installieren.
