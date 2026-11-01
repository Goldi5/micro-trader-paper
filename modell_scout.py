#!/usr/bin/env python3
"""
Modell-Scout: Prüft stündlich alle Free-Kataloge (Groq, OpenRouter, Zen),
testet jedes Modell mit einem Mini-Call und schreibt ki_pool.json.
Der Trader liest den Pool beim nächsten Lauf automatisch.

Nutzung:  python3 modell_scout.py          (einmalig)
Timer:    systemd modell-scout.timer (stündlich)
Output:   /opt/micro-trader/ki_pool.json
Log:      /opt/micro-trader/modell_scout.log
"""
import json, os, sys, time, uuid, urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))  # war fest "/opt/micro-trader" (01.11.2026)
LOG = os.path.join(BASE, "modell_scout.log")
POOL_FILE = os.path.join(BASE, "ki_pool.json")
UA = "micro-trader-scout/1.0"
ZEN_UA = "opencode/1.15.0 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.13"

def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def lade_env():
    for line in open(os.path.join(BASE, ".env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v

# ── Kataloge abfragen ──────────────────────────────────────────

def groq_modelle():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return []
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        # Nur Text-Chat-Modelle (kein whisper/guard/orpheus)
        skip = ("whisper", "guard", "orpheus", "tts", "prompt-guard")
        out = []
        for m in d.get("data", []):
            mid = m["id"]
            if not any(s in mid for s in skip):
                out.append(mid)
        return [("groq", mid) for mid in out]
    except Exception as e:
        log(f"Groq-Katalog FEHLER: {e}")
        return []

def openrouter_modelle():
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        out = []
        for m in d.get("data", []):
            if str(m.get("id", "")).endswith(":free"):
                # Grober Qualitätsfilter: Kontext >= 32k
                ctx = m.get("context_length") or 0
                if ctx >= 32768:
                    out.append(m["id"])
        return [("openrouter", mid) for mid in out]
    except Exception as e:
        log(f"OpenRouter-Katalog FEHLER: {e}")
        return []

def zen_modelle():
    key = os.environ.get("OPENCODE_ZEN_API_KEY")
    if not key:
        return []
    try:
        req = urllib.request.Request(
            "https://opencode.ai/zen/v1/models",
            headers={"Authorization": f"Bearer {key}",
                     "User-Agent": ZEN_UA,
                     "x-opencode-client": "cli",
                     "x-opencode-project": "global",
                     "x-opencode-request": f"msg_{uuid.uuid4().hex[:20]}",
                     "x-opencode-session": f"ses_{uuid.uuid4().hex[:20]}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        out = [m["id"] for m in d.get("data", []) if str(m.get("id", "")).endswith("-free")]
        return [("zen", mid) for mid in out]
    except Exception as e:
        log(f"Zen-Katalog FEHLER: {e}")
        return []

# ── Test-Call ──────────────────────────────────────────────────

def test_call(provider, model, key):
    """Mini-Call: antwortet das Modell vernünftig? -> (ok, latenz_s, notiz)."""
    base_urls = {
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "zen": os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1"),
    }
    base = base_urls[provider]
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if provider == "zen":
        headers.update({
            "Authorization": f"Bearer {key}",
            "User-Agent": ZEN_UA,
            "x-opencode-client": "cli",
            "x-opencode-project": "global",
            "x-opencode-request": f"msg_{uuid.uuid4().hex[:20]}",
            "x-opencode-session": f"ses_{uuid.uuid4().hex[:20]}",
        })
    elif provider == "openrouter":
        headers["Authorization"] = f"Bearer {key}"
        headers["HTTP-Referer"] = "https://micro-trader.local"
        headers["X-Title"] = "Micro-Trader"
    else:
        headers["Authorization"] = f"Bearer {key}"

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": 'Antworte NUR mit JSON: {"status":"ok"}'}],
        "max_tokens": 100,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        dt = time.time() - t0
        content = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if len(content.strip()) < 2:
            return False, dt, "leere Antwort"
        return True, dt, ""
    except Exception as e:
        dt = time.time() - t0
        msg = str(e)[:80]
        if hasattr(e, "read"):
            try:
                msg += " " + e.read().decode()[:80]
            except Exception:
                pass
        return False, dt, msg

# ── Hauptlogik ─────────────────────────────────────────────────

def main():
    lade_env()
    log("=== Modell-Scout gestartet ===")

    kandidaten = []
    kandidaten += groq_modelle()
    kandidaten += zen_modelle()
    or_liste = openrouter_modelle()
    # OpenRouter: max. 15 beste (nach Name heuristisch: bekannte starke Familien zuerst)
    prioritaet = ("nemotron", "deepseek", "llama", "qwen", "glm", "gemma", "mistral", "gpt-oss")
    or_liste.sort(key=lambda x: (0 if any(p in x[1].lower() for p in prioritaet) else 1, x[1]))
    kandidaten += or_liste[:15]

    log(f"{len(kandidaten)} Kandidaten aus Katalogen")

    key_map = {
        "groq": os.environ.get("GROQ_API_KEY"),
        "openrouter": os.environ.get("OPENROUTER_API_KEY"),
        "zen": os.environ.get("OPENCODE_ZEN_API_KEY"),
    }

    pool = []
    for provider, model in kandidaten:
        ok, dt, notiz = test_call(provider, model, key_map[provider])
        status = "OK " if ok else "-- "
        log(f"{status} [{provider}] {model} ({dt:.1f}s) {notiz}")
        if ok:
            pool.append({
                "provider": provider,
                "model": model,
                "latenz_s": round(dt, 2),
                "geprueft": datetime.now(timezone.utc).isoformat(),
            })

    # Sortieren: schnellste zuerst (der Trader rotiert eh, aber Reihenfolge als Gewichtung)
    pool.sort(key=lambda p: p["latenz_s"])

    ergebnis = {
        "aktualisiert": datetime.now(timezone.utc).isoformat(),
        "anzahl": len(pool),
        "modelle": pool,
    }
    tmp = POOL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, indent=1)
    os.replace(tmp, POOL_FILE)

    log(f"=== Fertig: {len(pool)}/{len(kandidaten)} Modelle im Pool -> ki_pool.json ===")

if __name__ == "__main__":
    main()
