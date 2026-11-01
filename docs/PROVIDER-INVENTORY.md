# KI-Provider-Inventar (Stand 2026-08-10, v2.51.0)

**Status:** ✅ KI-Provider-Pool repariert. Trading entscheidet wieder fundiert.

## Provider-Pool (Cron/Trader — `ki_provider.py`)

Reihenfolge der Rotation (Primary zuerst):

| # | Name | Modell | Endpoint | Status | Latenz | Bemerkung |
|---|---|---|---|---|---|---|
| 1 | **openrouter** | `nvidia/nemotron-3-nano-30b-a3b:free` | openrouter.ai/api/v1 | ✅ **Primary** | ~1–3s | Schnellster funktionierender Free-Provider |
| 2 | **nous-hy3** | `tencent/hy3:free` | inference-api.nousresearch.com/v1 | ✅ aktiv | ~6–9s | Reasoning-Modell, braucht `max_tokens≥2048` (auto-gehoben in `_ki_call`) |
| 3 | **nous-step** | `stepfun/step-3.7-flash:free` | inference-api.nousresearch.com/v1 | ✅ aktiv | ~4–5s | Reasoning-Modell, ebenfalls max_tokens-Lift |
| 4 | **zen** | `ling-3.0-flash-free` | opencode.ai/zen/v1 | ✅ Puffer | ~7s | deepseek tot (429), laguna-s 401 |
| 5 | **zen-nemotron** | `nemotron-3-ultra-free` | opencode.ai/zen/v1 | ⚠️ langsam | ~72s | Nur Notnagel, zu langsam für Trading-Loop |

## Getestete, aber tote Modelle (dieser Account)

| Provider | Modell | Fehler | Grund |
|---|---|---|---|
| zen (OpenCode) | `deepseek-v4-flash-free` | 429 `FreeUsageLimitError` | Quota leer (Free-Tier) |
| zen (OpenCode) | `laguna-s-2.1:free` / `poolside/laguna-s-2.1:free` | 401 `ModelError` | **Nicht in diesem Zen-Account autorisiert** (trotz öffentlicher Liste) |
| zen (OpenCode) | `mimo-v2.5-free`, `longcat-2.0-free` | 429 | Quota leer |
| zen (OpenCode) | `ling-3.0-tiny-free` | 503 | Server-Fehler |
| zen (OpenCode) | `north-mini-code-free` | 401 | Nicht autorisiert |
| OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | (78s Antwort) | Zu langsam → Timeout im Trader (daher umgestellt auf nano) |

## Root-Cause Fixes (v2.51.0)

1. **hy3/step leeres content:** Reasoning-Modelle liefern bei `max_tokens<2048`
   nur `finish_reason=length` (content leer). `_ki_call` hebt `max_tokens` für
   hy3/step jetzt automatisch auf `max(max_tokens, 2048)`.
2. **OpenRouter 78s:** `nemotron-3-ultra-550b` zu langsam → auf `nemotron-3-nano-30b`
   umgestellt (Primary).
3. **zen/deepseek 429:** Quota leer → zen auf `ling-3.0-flash-free` (funktioniert).
4. **ki_cooldown.json:** Circuit-Breaker sperrte alle Provider dauerhaft → gelöscht.
5. **OpenRouter-Header:** `HTTP-Referer`/`X-Title` in `get_client` ergänzt.

## Verifikation (ad-hoc, 8/8 PASS, 2026-08-10 21:1x)

```
openrouter  3.8s  OK  'OK'
nous-step   4.0s  OK  'OK'
nous-hy3    8.6s  OK  'OK'
zen(ling)   1.3s  OK  'Ja, ich verste...'
hy3/step max_tokens>=2048-Lift: aktiv
OR-Header: gesetzt
```

Live-`call_ki(max_tokens=1024)` → openrouter, 2.4s, fundierte JSON-Antwort.

## Letzter KI-Run

- **21:16:17** (2026-08-10) — 20/20 Spec mit Aktion, nur 4 Fallback (vorher 10).
- Trader-Prozesse: `spec_trader.py` (PID 25584) + `batch_trader.py` (PID 21360) laufen.
  `spec_watch.py` / `etf_trader.py` sind einmalige Scans (exit 0 nach Scan).
