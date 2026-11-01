"""WOL-Verify-Cron: Prueft ob Micro-Trader PC wirklich aus ist.

Laeuft als no_agent-Script-Job auf HERMES (nicht auf dem PC!) -> ueberlebt PC-Shutdown.
Alle 5min:
  1. FritzBox 5690 Pro API (TR-064, GetSpecificHostEntry per MAC) abfragen
  2. Ist der PC noch im Netz? -> WARNUNG auf stdout (Cron liefert an WhatsApp)
  3. Fallback: TCP-Ping auf PC-IP
  4. Wenn NEIN (aus) -> LEERER stdout (Cron = silent, keine Nachricht)

WICHTIG (no_agent-Job): Der Cron liefert die stdout verbatim an WhatsApp.
  - PC aus  -> stdout LEER  -> kein Output (silent, keine Spam-Nachricht)
  - PC wach -> stdout WARN  -> WhatsApp-Warnung an User
  - Fehler  -> exit != 0    -> Cron liefert als Fehler-Alert (Misconfig erkennbar)
Daher: Warnung NICHT mehr selbst via 'hermes send' schicken (wuerde als
Duplicate unterdrueckt) -> nur auf stdout schreiben.

Konfiguration in wol-verify-config.json (pc_ip / pc_mac MUSS gesetzt sein,
sonst meldet das Skript KONFIG-FEHLER statt falsch "PC aus").
"""
import urllib.request, urllib.error, urllib.parse, json, socket, os, sys, hashlib
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "wol-verify-config.json")
FRITZBOX = "http://192.168.178.1"
WHATSAPP_TARGET = ""  # echtes Ziel nur in wol-verify-config.json (git-ignoriert)

DEFAULT_CONFIG = {
    "pc_ip": "192.168.178.XXX",      # << echte PC-IP eintragen
    "pc_mac": "XX:XX:XX:XX:XX:XX",   # << echte PC-MAC eintragen (fuer FritzBox-Check)
    "ping_port": 135,                # Windows RPC (immer offen wenn PC wach); alternativ 5300
    "fritzbox_user": "",             # FritzBox-Benutzer (leer = nur Ping-Fallback)
    "fritzbox_pass": "",             # FritzBox-Passwort
    "whatsapp_target": WHATSAPP_TARGET
}


def lade_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        # fehlende Schluessel ergaenzen
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)


def konfiguriert(cfg):
    """True wenn echte Werte gesetzt (keine Platzhalter)."""
    ip = (cfg.get("pc_ip") or "").strip()
    mac = (cfg.get("pc_mac") or "").strip()
    if "XXX" in ip or ip.startswith("192.168.178.XX"):
        return False
    if "XX:XX" in mac.upper():
        return False
    return True


def fritzbox_aktiv(cfg, mac):
    """TR-064: Hosts->GetSpecificHostEntry(NewMACAddress) -> NewActive.
    Mit User/Pass: Login + SOAP. OHNE Creds: Unauth-Lesefallback (FRITZ!OS
    erlaubt GetSpecificHostEntry haeufig ohne Login). Liefert None bei Fehler/unklar."""
    user = cfg.get("fritzbox_user") or ""
    pw = cfg.get("fritzbox_pass") or ""
    try:
        if user and pw:
            # MD5-Challenge (FRITZ!OS 8.25 API=MD5)
            chal_url = f"{FRITZBOX}/login_sid.lua?version=1"
            with urllib.request.urlopen(chal_url, timeout=8) as r:
                js = json.loads(r.read().decode("utf-8", "replace"))
            challenge = js.get("challenge")
            if not challenge:
                return None
            md5 = hashlib.md5()
            md5.update((challenge + "-" + pw).encode("utf-16-le"))
            response = challenge + "-" + md5.hexdigest()
            login_body = f"username={urllib.parse.quote(user)}&response={response}"
            req = urllib.request.Request(f"{FRITZBOX}/login_sid.lua?version=1",
                                         data=login_body.encode(), method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=8) as r:
                js = json.loads(r.read().decode("utf-8", "replace"))
            sid = js.get("sid")
            if not sid or sid == "0000000000000000":
                return None
            # SOAP GetSpecificHostEntry (mit SID)
            soap = (
                '<?xml version="1.0"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                '<s:Body>'
                '<u:GetSpecificHostEntry xmlns:u="urn:dslforum-org:service:Hosts:1">'
                f'<NewMACAddress>{mac}</NewMACAddress>'
                '</u:GetSpecificHostEntry>'
                '</s:Body></s:Envelope>'
            )
            req = urllib.request.Request(f"{FRITZBOX}:49000/upnp/control/hosts", data=soap.encode(), method="POST")
            req.add_header("Content-Type", 'text/xml; charset="utf-8"')
            req.add_header("SOAPAction", 'urn:dslforum-org:service:Hosts:1#GetSpecificHostEntry')
            req.add_header("Cookie", f"sid={sid}")
            with urllib.request.urlopen(req, timeout=8) as r:
                body = r.read().decode("utf-8", "replace")
            return "NewActive>1</" in body or "<NewActive>true</" in body.lower()
        # Unauth-Fallback: GetSpecificHostEntry direkt ohne Login (kein Pass noetig)
        soap = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body>'
            '<u:GetSpecificHostEntry xmlns:u="urn:dslforum-org:service:Hosts:1">'
            f'<NewMACAddress>{mac}</NewMACAddress>'
            '</u:GetSpecificHostEntry>'
            '</s:Body></s:Envelope>'
        )
        req = urllib.request.Request(f"{FRITZBOX}:49000/upnp/control/hosts", data=soap.encode(), method="POST")
        req.add_header("Content-Type", 'text/xml; charset="utf-8"')
        req.add_header("SOAPAction", 'urn:dslforum-org:service:Hosts:1#GetSpecificHostEntry')
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read().decode("utf-8", "replace")
        return "NewActive>1</" in body or "<NewActive>true</" in body.lower()
    except Exception:
        return None


def ping_pc(cfg):
    ip = cfg.get("pc_ip")
    port = int(cfg.get("ping_port") or 5300)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((ip, port))
        s.close()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    jetzt = datetime.now()
    cfg = lade_config()

    if not konfiguriert(cfg):
        # KEIN falsches "PC aus" melden -> laut warnen, Exit != 0 (Cron liefert als Fehler-Alert)
        print(f"[{jetzt:%H:%M}] KONFIG-FEHLER: pc_ip/pc_mac in "
              f"wol-verify-config.json nicht gesetzt -> Monitor INAKTIV!")
        sys.exit(2)

    im_netz = None
    mac = (cfg.get("pc_mac") or "").strip()
    if mac and "XX:XX" not in mac.upper():
        im_netz = fritzbox_aktiv(cfg, mac)
    if im_netz is None:
        im_netz = ping_pc(cfg)

    if im_netz:
        # stdout wird vom Cron verbatim an WhatsApp geliefert
        print(f"\u26a0\ufe0f PC noch wach ({jetzt:%H:%M})! Shutdown hat nicht "
              f"gekippt. Erneut versuchen: 'PC aus'")
    else:
        # LEERER stdout -> Cron silent (kein Output bei Erfolg / PC aus).
        # Debug-Hinweis nur auf stderr (wird bei Erfolg NICHT geliefert).
        sys.stderr.write(f"[{jetzt:%H:%M}] OK: PC aus (nicht im Netz)\n")
