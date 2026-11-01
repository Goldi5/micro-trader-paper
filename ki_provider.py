#!/usr/bin/env python3
"""KI-Provider-Verwaltung mit automatischem Fallback.

ZWEI getrennte Provider-Ketten:
  A) CRON-Pool  (call_ki / call_ki_cron): VOLLE Rotation, deterministisch (temp=0.1).
     zen → zen-nemotron → nous-step → nous-hy3 → openrouter
  B) CHAT-Pool (call_ki_chat): KURZ + SCHNELL für User-Chat (temp=0.3).
     zen-nemotron → zen → openrouter
     Verbraucht bewusst NICHT die Nous-free-Quota, die der Cron braucht.

Bei 401/429/Timeout wird automatisch der nächste Provider versucht.
Der Nous-Zugang nutzt den Hermes-OAuth-Token (shared/nous_auth.json)
und refresht ihn bei Ablauf über das Nous Portal.

API:
    call_ki(messages, ...)              → Cron-Pool (abwärtskompatibel)
    call_ki_cron(messages, ...)         → Cron-Pool (explizit)
    call_ki_chat(messages, ...)         → Chat-Pool (User-Facing)
"""
import os, json, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
NOUS_AUTH = os.path.expanduser("~/AppData/Local/hermes/shared/nous_auth.json")
NOUS_DEFAULT_BASE = "https://inference-api.nousresearch.com/v1"
NOUS_DEFAULT_PORTAL = "https://portal.nousresearch.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ─── Env laden (Hermes-Config) ─────────────────────────────
def lade_env():
    for cand in [os.path.join(BASE, ".env"),
                 os.path.expanduser("~/AppData/Local/hermes/.env")]:
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip())
            except Exception:
                pass


lade_env()


# ─── Nous-OAuth (Hermes-Token + Refresh) ───────────────────
def _nous_creds():
    """Liest Nous-Credentials, refresht bei Ablauf. → (token, base_url)."""
    if not os.path.exists(NOUS_AUTH):
        return None, None
    try:
        with open(NOUS_AUTH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None, None
    token = d.get("access_token") or ""
    base = (d.get("inference_base_url") or NOUS_DEFAULT_BASE).rstrip("/")
    exp = d.get("expires_at")
    abgelaufen = False
    if exp:
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            abgelaufen = datetime.now(timezone.utc) >= exp_dt - timedelta(seconds=120)
        except Exception:
            abgelaufen = True
    if abgelaufen:
        neu = _nous_refresh(d)
        if neu:
            token = neu
        else:
            d["access_token"] = ""
            d["expires_at"] = "1970-01-01T00:00:00Z"
            try:
                with open(NOUS_AUTH, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
            except Exception:
                pass
    return token or None, base


def _nous_refresh(d):
    """Refresh-Token gegen das Nous Portal eintauschen. → neuer access_token."""
    portal = (d.get("portal_base_url") or NOUS_DEFAULT_PORTAL).rstrip("/")
    rt = d.get("refresh_token")
    cid = d.get("client_id") or "hermes-cli"
    if not rt:
        return None
    try:
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": cid,
        }).encode()
        req = urllib.request.Request(
            portal + "/api/oauth/token", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
        neu = payload.get("access_token")
        if neu:
            d["access_token"] = neu
            if payload.get("expires_at"):
                d["expires_at"] = payload["expires_at"]
            if payload.get("refresh_token"):
                d["refresh_token"] = payload["refresh_token"]
            try:
                with open(NOUS_AUTH, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
            except Exception:
                pass
        return neu
    except Exception:
        return None


# ─── Provider-Listen (Chat vs. Cron getrennt) ───────────────
_PROVIDER_LISTE = None
_PROVIDER_LISTE_CHAT = None


def _scout_pool():
    """Liest ki_pool.json (vom Modell-Scout, stündlich aktualisiert).
    -> Liste von dicts {"name","base_url","api_key","model"} oder [].
    Nur Modelle mit funktionierendem Key/Provider werden gemappt."""
    pfad = os.path.join(BASE, "ki_pool.json")
    if not os.path.exists(pfad):
        return []
    try:
        with open(pfad, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return []
    # Frisch genug? (max. 26h alt, sonst veraltet -> Fallback auf statisch)
    import datetime as _dt
    try:
        upd = _dt.datetime.fromisoformat(d.get("aktualisiert", "").replace("Z", "+00:00"))
        if _dt.datetime.now(_dt.timezone.utc) - upd > _dt.timedelta(hours=26):
            return []
    except Exception:
        return []
    key_map = {
        "groq": (os.environ.get("GROQ_API_KEY"),
                 os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")),
        "openrouter": (os.environ.get("OPENROUTER_API_KEY"),
                       "https://openrouter.ai/api/v1"),
        "zen": (os.environ.get("OPENCODE_ZEN_API_KEY"),
                os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")),
    }
    out = []
    seen = set()
    for m in d.get("modelle", []):
        prov, model = m.get("provider"), m.get("model")
        key, base = key_map.get(prov, (None, None))
        if not (key and base and model):
            continue
        name = f"{prov}-{model}"[:60]
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "base_url": base,
                    "api_key": key, "model": model})
    return out


def _baue_provider_liste_cron():
    """VOLLE Rotation fuer Batch/KI-Cron. Round-Robin ueber alle Free-Provider:
    Groq (14400 RPD) -> OpenRouter(:free) -> 6x Zen-Free -> 2x Nous.
    Die Rotation in _call_ki_with_pool startet bei jedem Call an einer
    anderen Position -> Rate-Limits werden entzerrt."""
    liste = []
    def add(name, base_url, api_key, model):
        if api_key:
            liste.append({"name": name, "base_url": base_url,
                          "api_key": api_key, "model": model})
    # DYNAMISCHER POOL aus Modell-Scout (ki_pool.json): bevorzugt verwenden.
    scout = _scout_pool()
    if scout:
        return scout
    # FALLBACK: statischer Pool (wenn Scout noch nie gelaufen ist / veraltet)
    # 0. GROQ (Primary-Qualitaet, 14400 RPD frei)
    groq_base = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    if os.environ.get("GROQ_API_KEY"):
        add("groq", groq_base,
            os.environ.get("GROQ_API_KEY"),
            os.environ.get("KI_MODEL_GROQ", "openai/gpt-oss-120b"))
    # 1. OpenRouter (:free-Tier)
    add("openrouter", "https://openrouter.ai/api/v1",
        os.environ.get("OPENROUTER_API_KEY"),
        os.environ.get("KI_MODEL_OPENROUTER", "nvidia/nemotron-3-nano-30b-a3b:free"))
    # 2. OpenCode Zen: 6 funktionierende FREE-Modelle (verifiziert 22.08.26,
    #    mit x-opencode-* Headern via get_client())
    zen_base = os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
    zen_key = os.environ.get("OPENCODE_ZEN_API_KEY")
    if zen_key:
        for m in ("nemotron-3-ultra-free",      # 1M ctx, zuverlaessig (14s)
                  "laguna-s-2.1-free",           # schnell (3s)
                  "hy3-free",                    # reasoning, braucht max_tokens>=1024
                  "mimo-v2.5-free",
                  "nemotron-3.5-lightning-free", # blitzschnell (1s), thinking-tokens
                  "x-preview-f-free"):
            add(f"zen-{m.replace('-free','')}", zen_base, zen_key, m)
    # 3. Nous-Hy3/Step (Token auto-refresh)
    ntoken, nbase = _nous_creds()
    if ntoken and nbase:
        add("nous-hy3", nbase, ntoken, "tencent/hy3:free")
        add("nous-step", nbase, ntoken, "stepfun/step-3.7-flash:free")
    return liste


def _baue_provider_liste_chat():
    """KURZE Kette fuer User-Chat: Groq (schnell+gut) -> Zen laguna -> OpenRouter."""
    liste = []
    def add(name, base_url, api_key, model):
        if api_key:
            liste.append({"name": name, "base_url": base_url,
                          "api_key": api_key, "model": model})
    groq_base = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    if os.environ.get("GROQ_API_KEY"):
        add("groq", groq_base,
            os.environ.get("GROQ_API_KEY"),
            os.environ.get("KI_MODEL_GROQ", "openai/gpt-oss-120b"))
    zen_base = os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
    zen_key = os.environ.get("OPENCODE_ZEN_API_KEY")
    if zen_key:
        add("zen-laguna", zen_base, zen_key, "laguna-s-2.1-free")
    add("openrouter", "https://openrouter.ai/api/v1",
        os.environ.get("OPENROUTER_API_KEY"),
        os.environ.get("KI_MODEL_OPENROUTER", "nvidia/nemotron-3-nano-30b-a3b:free"))
    return liste


def _baue_provider_liste():
    """Default = volle Cron-Liste (abwärtskompatibel zu call_ki())."""
    global _PROVIDER_LISTE
    _PROVIDER_LISTE = _baue_provider_liste_cron()


def provider_liste():
    global _PROVIDER_LISTE
    # Pool neu bauen, wenn ki_pool.json frischer als der Cache ist
    try:
        pool_mtime = os.path.getmtime(os.path.join(BASE, "ki_pool.json"))
    except OSError:
        pool_mtime = 0
    if _PROVIDER_LISTE is None or pool_mtime > getattr(provider_liste, "_mtime", 0):
        _PROVIDER_LISTE = None
        _baue_provider_liste()
        provider_liste._mtime = pool_mtime
    return _PROVIDER_LISTE


def provider_liste_chat():
    global _PROVIDER_LISTE_CHAT
    if _PROVIDER_LISTE_CHAT is None:
        _PROVIDER_LISTE_CHAT = _baue_provider_liste_chat()
    return _PROVIDER_LISTE_CHAT


_client_cache = {}


def get_client(provider):
    """Liefert OpenAI-Client für einen Provider (gecacht)."""
    name = provider["name"]
    if name not in _client_cache:
        from openai import OpenAI
        headers = {"User-Agent": UA}
        # OpenRouter braucht HTTP-Referer + X-Title, sonst leere Antworten
        if "openrouter" in provider["base_url"]:
            headers["HTTP-Referer"] = "https://micro-trader.local"
            headers["X-Title"] = "Micro-Trader"
        # OpenCode Zen verlangt x-opencode-*-Header, sonst 401/403
        if "opencode.ai/zen" in provider.get("base_url", ""):
            import uuid as _uuid
            headers["User-Agent"] = ("opencode/1.15.0 ai-sdk/provider-utils/4.0.23 "
                                     "runtime/bun/1.3.13")
            headers["x-opencode-client"] = "cli"
            headers["x-opencode-project"] = "global"
            headers["x-opencode-request"] = f"msg_{_uuid.uuid4().hex[:20]}"
            headers["x-opencode-session"] = f"ses_{_uuid.uuid4().hex[:20]}"
        _client_cache[name] = OpenAI(
            api_key=provider["api_key"], base_url=provider["base_url"],
            default_headers=headers)
    return _client_cache[name]


# ─── Circuit-Breaker: persistenter Provider-Cooldown ──────
# Verhindert Dauer-Ban: ein Provider, der 429/Timeout liefert, wird für
# COOLDOWN_SEK rausgenommen (nicht mehr angefragt). State bleibt über
# Cron-Runs hinweg erhalten (ki_cooldown.json), damit ein gesperrter
# Provider auch nach Neustart "kalt" bleibt.
import threading
import mtlog  # Zentrales Logsystem (Run-Kontext, Rotation)
# ─── Round-Robin-Rotation ─────────────────────────────────
# Zeiger dreht bei JEDEM Call weiter -> gleichmaessige Verteilung.
_RR_INDEX = [0]


def _rr_next(n):
    _RR_INDEX[0] = (_RR_INDEX[0] + 1) % max(n, 1)
    return _RR_INDEX[0]


_COOLDOWN_FILE = os.path.join(BASE, "ki_cooldown.json")
_COOLDOWN_LOCK = threading.Lock()
# Wie lange ein Provider nach Fehler "kalt" ist (Minuten).
COOLDOWN_MIN = {"rate_limit": 10, "timeout": 5, "auth": 30}
# Max. aufeinanderfolgende Fehler, bevor der ganze Run abbricht (Fail-Fast).
MAX_FEHLER_HINT = 3
# Per-Call-Timeout. 180s: Free-Provider + Reasoning-Modelle (hy3) brauchen
# oft >120s -> 120s liess alle Provider in Timeout-Cooldown fallen ->
# "ALLE_PROVIDER_KALT" -> keine Käufe. 180s gibt mehr Puffer.
CALL_TIMEOUT = 180
_cooldown_state = {}        # name -> {"bis": epoch, "grund": str}
_fehler_hintereinander = 0  # Fail-Fast-Zähler (pro Prozess-Lauf)
# FIX 27.09.2026: Fehler je Provider-GRUPPE zaehlen, nicht global.
# Ein Ausfall bei groq darf openrouter nicht den Versuch nehmen.
_gruppenfehler = {}


def _cooldown_laden():
    global _cooldown_state
    try:
        if os.path.exists(_COOLDOWN_FILE):
            # Schutz: sehr alte Cooldown-Datei (z.B. von Absturz/Modell-Wechsel
            # hängengeblieben) verwerfen -> sonst blockiert sie den Handel dauerhaft.
            import datetime as _dt
            age = time.time() - os.path.getmtime(_COOLDOWN_FILE)
            if age > 6 * 3600:  # älter als 6h -> ignorieren
                _cooldown_state = {}
                return
            with open(_COOLDOWN_FILE, encoding="utf-8") as f:
                _cooldown_state = json.load(f)
            jetzt = time.time()
            for name, entry in list(_cooldown_state.items()):
                bis = entry.get("bis", 0)
                # Filter: Einträge mit "bis" in weiter Zukunft (> 1 Jahr) -> Data corruption/Time-glitch
                if bis > jetzt + 365 * 24 * 3600:
                    del _cooldown_state[name]
                # Filter: Einträge die längst abgelaufen sind (< jetzt)
                elif bis < jetzt:
                    del _cooldown_state[name]
    except Exception:
        _cooldown_state = {}


def _cooldown_speichern():
    try:
        with open(_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(_cooldown_state, f)
    except Exception:
        pass


def _provider_kalt(name):
    eintrag = _cooldown_state.get(name)
    if not eintrag:
        return False
    if time.time() < eintrag.get("bis", 0):
        return True
    # abgelaufen -> entfernen
    _cooldown_state.pop(name, None)
    return False


def _setze_kalt(name, grund):
    dauer = COOLDOWN_MIN.get(grund, 10)
    _cooldown_state[name] = {"bis": time.time() + dauer * 60, "grund": grund}
    _cooldown_speichern()


def _fehler_klassifizieren(err_text):
    t = (err_text or "").lower()
    if "429" in t or "rate" in t or "too many" in t or "quota" in t:
        return "rate_limit"
    if "timeout" in t or "timed out" in t or "deadline" in t:
        return "timeout"
    if "401" in t or "403" in t or "unauthorized" in t or "auth" in t:
        return "auth"
    return "timeout"  # unbekannter Fehler -> kurzer Cooldown


_cooldown_laden()


def _ki_call(client, provider, messages, temperature, max_tokens, model):
    """Führt den KI-Call aus (chat/completions für alle Provider).
    Liefert (text, fehler) — text None bei Fehler.
    Robust gegen Reasoning-Modelle (hy3/step), die statt content oft
    nur reasoning_content liefern — beides wird akzeptiert.
    Reasoning-Modelle (nous-hy3, step-3.7) brauchen hohes max_tokens,
    sonst ist finish_reason='length' und content bleibt leer -> wir
    heben max_tokens für diese Modelle auf mind. 2048 an."""
    model_l = (model or "").lower()
    if "hy3" in model_l or "step" in model_l:
        max_tokens = max(max_tokens, 2048)
    try:
        r = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, timeout=CALL_TIMEOUT)
        msg = r.choices[0].message
        antwort = msg.content
        # Reasoning-Modelle (nous-hy3, step-3.7) geben ggf. nur reasoning_content
        if (not antwort or not antwort.strip()) and getattr(msg, "reasoning_content", None):
            antwort = msg.reasoning_content
        if antwort and antwort.strip():
            return antwort.strip(), None
        # leere Antwort bei Reasoning-Modell: nicht als harter Fehler werten
        # (passiert bei sehr kleinem max_tokens) -> trotzdem Cooldown vermeiden
        if not antwort:
            return None, "leere Antwort (Reasoning-Modell?)"
        return None, "leere Antwort"
    except Exception as e:
        return None, str(e)[:200]


def _call_ki_with_pool(messages, temperature, max_tokens, pool, model_hint=None):
    """Interne Rotation über eine gegebene Provider-Liste.
    Mit Circuit-Breaker: kalte Provider werden übersprungen; bei Fehler
    wird der Provider 'kalt' gesetzt. Fail-Fast nach MAX_FEHLER_HINT
    aufeinanderfolgenden Fehlern -> Run abbrechen (spart Quota/Tokens)."""
    global _fehler_hintereinander
    if not pool:
        return None, None
    with _COOLDOWN_LOCK:
        aktive = [p for p in pool if not _provider_kalt(p["name"])]
    if not aktive:
        # Alle Provider kalt -> sofort zurück, kein sinnloses Warten
        return None, "ALLE_PROVIDER_KALT"
    # ROUND-ROBIN: Startposition rotiert bei jedem Call -> Anfragen verteilen
    # sich gleichmaessig über alle Provider (entzerrt Rate-Limits).
    start = _rr_next(len(aktive))
    aktive = aktive[start:] + aktive[:start]
    for provider in aktive:
        try:
            client = get_client(provider)
            antwort, fehler = _ki_call(client, provider, messages, temperature,
                                       max_tokens, model_hint or provider["model"])
            if antwort:
                _fehler_hintereinander = 0  # Reset bei Erfolg
                _gruppenfehler.clear()     # FIX: auch Gruppenzaehler resetten
                return antwort, provider["name"]
        except Exception as e:
            fehler = str(e)[:200]
        # Fehler -> Provider kalt setzen (nur DIESEN, nicht die anderen)
        grund = _fehler_klassifizieren(fehler)
        with _COOLDOWN_LOCK:
            _setze_kalt(provider["name"], grund)
        _fehler_hintereinander += 1

        # FIX 27.09.2026: Fail-Fast hat den Lauf abgebrochen, BEVOR ein
        # funktionierender Provider erreicht wurde. Bei 16 im Pool
        # getesteten Modulen scheiterten die ersten drei (alle groq) mit
        # "timeout", darauf brach die Schleife ab - 13 funktionierende
        # Provider blieben ungenutzt.
        #
        # Korrekte Regel: einzelne Provider-Ausfaelle sind kein Grund,
        # die Kette zu beenden. Free-Tier-Limits sind pro Provider
        # unabhaengig. Abbrechen darf man nur, wenn dieselbe Provider-
        # GRUPPE mehrfach hintereinander scheitert, dann ist sie
        # tatsaechlich down.
        _gruppe = provider["name"].split("-")[0]
        _gruppenfehler[_gruppe] = _gruppenfehler.get(_gruppe, 0) + 1

        if _gruppenfehler[_gruppe] >= MAX_FEHLER_HINT:
            # Diese Gruppe ist tot -> ueberspringen, Rest weiter testen.
            _gruppenfehler.clear()
            continue

        if _fehler_hintereinander >= MAX_FEHLER_HINT * 3:
            # Auch ueber diverse Gruppen hinweg nichts bekommen ->
            # dann ist es ein Systemfehler, nicht ein Provider-Ausfall.
            return None, "FAIL_FAST"
        # Nous-Token evtl. abgelaufen -> einmal refreshen und erneut probieren
        if provider["name"].startswith("nous-"):
            global _PROVIDER_LISTE
            _PROVIDER_LISTE = None
            _baue_provider_liste()
            for p in provider_liste():
                if p["name"] == provider["name"]:
                    provider = p
                    break
            try:
                antwort, _ = _ki_call(get_client(provider), provider, messages,
                                      temperature, max_tokens, provider["model"])
                if antwort:
                    _fehler_hintereinander = 0
                    return antwort, provider["name"]
            except Exception:
                pass
    return None, "ALLE_PROVIDER_KALT"


# 01.11.2026: Ein Eintrag je KI-Aufruf (JSON-Zeilen) fuer die Kennzahlen im
# Tagesbericht: Erfolgsquote, Anbieter, Dauer. Laufzeitdatei, git-ignoriert,
# begrenzt auf ~2 MB (aeltere Haelfte wird verworfen).
AUFRUF_LOG = os.path.join(BASE, "ki_aufrufe.jsonl")
_AUFRUF_LOG_MAX = 2 * 1024 * 1024


def _protokolliere_aufruf(pool, t0, antwort, provider):
    try:
        eintrag = {"zeit": datetime.now().isoformat(timespec="seconds"),
                   "pool": pool, "ok": bool(antwort),
                   "provider": provider if antwort else None,
                   "fehler": None if antwort else (provider or "unbekannt"),
                   "sekunden": round(time.time() - t0, 2)}
        with open(AUFRUF_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        if os.path.getsize(AUFRUF_LOG) > _AUFRUF_LOG_MAX:
            with open(AUFRUF_LOG, encoding="utf-8") as f:
                zeilen = f.readlines()
            tmp = AUFRUF_LOG + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(zeilen[len(zeilen) // 2:])
            os.replace(tmp, AUFRUF_LOG)
    except Exception:
        pass  # Protokoll darf nie einen KI-Aufruf stoeren


def _mit_protokoll(pool, messages, temperature, max_tokens, liste, model_hint):
    t0 = time.time()
    antwort, provider = _call_ki_with_pool(messages, temperature, max_tokens,
                                           liste, model_hint)
    _protokolliere_aufruf(pool, t0, antwort, provider)
    return antwort, provider


def call_ki(messages, temperature=0.1, max_tokens=2048, model_hint=None):
    """Cron-Pool (abwärtskompatibel). Rotation über ALLE Provider."""
    return _mit_protokoll("cron", messages, temperature, max_tokens,
                          provider_liste(), model_hint)


def call_ki_cron(messages, temperature=0.1, max_tokens=2048, model_hint=None):
    """Explizit Cron-Pool: volle Rotation, deterministisch."""
    return _mit_protokoll("cron", messages, temperature, max_tokens,
                          provider_liste(), model_hint)


def call_ki_chat(messages, temperature=0.3, max_tokens=1024, model_hint=None):
    """Chat-Pool: kurze, schnelle Kette für User-Facing WhatsApp/Antworten."""
    return _mit_protokoll("chat", messages, temperature, max_tokens,
                          provider_liste_chat(), model_hint)


def ki_faehig():
    """True wenn mindestens ein Provider mit Key existiert."""
    return len(provider_liste()) > 0


def call_ki_batched(messages_liste, temperature=0.1, max_tokens=4096,
                    model_hint=None, reduzierungs_stufe=0):
    """BÜNDELN für MAX-OUTPUT / MIN-TOKENS.

    Statt N einzelner Calls (N Depots) werden alle Prompts in EINEM Call
    gesendet (max_tokens hoch). Liefert eine LISTE von Antworten (eine pro
    Eingabe-Prompt) oder None bei Fehler.

    reduzierungs_stufe:
      0 = alle Prompts auf einmal (maximal gebündelt)
      1 = in 2 Hälften teilen (falls ein Call zu groß)
      2 = einzeln (Fallback, teuer)

    Das spart Tokens: 1 Call mit 20 Depots << 20 Calls mit je 1 Depot,
    weil System-Prompt/Overhead nur einmal anfällt. Bei Rate-Limit wird
    automatisch eine höhere Stufe (kleinere Batches) probiert, bis ein Call
    durchgeht — nie Dauer-Ban, weil _call_ki_with_pool Cooldown nutzt.
    """
    if not messages_liste:
        return []
    if reduzierungs_stufe >= 2 or len(messages_liste) == 1:
        # Einzeln (teuerster Fall, aber zuverlässig)
        ergebnisse = []
        for msg in messages_liste:
            antwort, _ = _call_ki_with_pool(
                msg, temperature, max_tokens, provider_liste(), model_hint)
            ergebnisse.append(antwort)
        return ergebnisse

    # Batches bilden
    if reduzierungs_stufe == 0:
        batches = [messages_liste]  # alles in einem Call
    else:  # stufe == 1
        half = (len(messages_liste) + 1) // 2
        batches = [messages_liste[:half], messages_liste[half:]]

    ergebnisse = []
    for batch in batches:
        # Mehrere Depots in EINEM Prompt zusammenfassen
        kombi = []
        for i, msg in enumerate(batch):
            kombi.append(f"=== DEPOT {i+1} ===\n" + "\n".join(
                f"{m['role']}: {m['content']}" for m in msg))
        combined_msg = [{
            "role": "user",
            "content": "\n\n".join(kombi) + "\n\nAntworte für JEDES Depot mit "
                       "einem separaten JSON-Block, nummeriert als "
                       "[[DEPOT_1]] ... [[DEPOT_N]]."}]
        antwort, status = _call_ki_with_pool(
            combined_msg, temperature, max_tokens, provider_liste(), model_hint)
        if antwort:
            # Antwort aufteilen pro Depot (grobes Splitting nach Marker)
            teile = _split_batched_antwort(antwort, len(batch))
            ergebnisse.extend(teile)
        else:
            # Fehler bei Batch -> feiner aufteilen (reduzierte Stufe)
            if status in ("FAIL_FAST", "ALLE_PROVIDER_KALT"):
                # Alle Provider kalt -> nicht weiter versuchen, None füllen
                ergebnisse.extend([None] * len(batch))
            else:
                # Teil-Batches rekursiv mit höherer Stufe
                ergebnisse.extend(
                    call_ki_batched(batch, temperature, max_tokens,
                                     model_hint, reduzierungs_stufe + 1))
    return ergebnisse


def _split_batched_antwort(antwort, anzahl):
    """Teilt eine gebündelte Antwort in `anzahl` einzelne Antworten auf.
    Nutzt Marker [[DEPOT_N]] oder schlichte Aufteilung bei Fehlen."""
    import re
    marker = re.findall(r"\[\[DEPOT_(\d+)\]\](.*?)(?=\[\[DEPOT_\d+\]\]|\Z)",
                        antwort, re.DOTALL)
    if marker:
        geordnet = sorted(marker, key=lambda x: int(x[0]))
        return [m[1].strip() for m in geordnet[:anzahl]] + \
               [None] * max(0, anzahl - len(geordnet))
    # Kein Marker -> einfach die ganze Antwort dem ersten Depot geben,
    # Rest None (besserer Fallback als gar nichts)
    return [antwort.strip()] + [None] * (anzahl - 1)
    print("Cron-Kette:  ", " → ".join(p["name"] for p in provider_liste()))
    print("Chat-Kette:  ", " → ".join(p["name"] for p in provider_liste_chat()))
    antwort, provider = call_ki_cron(
        [{"role": "user", "content": "Antworte NUR mit JSON: {\"ok\": true}"}],
        max_tokens=50)
    print(f"Cron-Test via '{provider}':", (antwort or "FEHLER")[:120])
