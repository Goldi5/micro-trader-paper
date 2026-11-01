import { createServer } from 'http';
import { exec } from 'child_process';
import { promisify } from 'util';
import { timingSafeEqual, randomBytes } from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';

const execAsync = promisify(exec);
const PORT = Number(process.env.MICRO_TRADER_PROXY_PORT || 8765);
// LUECKE 2 (2026-09-27): Bind auf Loopback. Vorher 0.0.0.0 -> im LAN und
// ueber Tailscale ohne jedes Credential erreichbar (ACAO: *).
const HOST = process.env.MICRO_TRADER_PROXY_HOST || '127.0.0.1';
const REMOTE_BASE = '/opt/micro-trader';

// ─── Authentifizierung ──────────────────────────────────────────────────────
// Token aus Env (z.B. via systemd EnvironmentFile) oder aus einer Datei mit
// Rechten 0600. Existiert keine, wird einmalig per CSPRNG erzeugt.
// NIE geraten, NIE im Klartext im Code, NIE im Log.
const TOKEN_FILE = process.env.MICRO_TRADER_PROXY_TOKEN_FILE
  || path.join(REMOTE_BASE, 'proxy_token');

function loadToken() {
  const fromEnv = process.env.MICRO_TRADER_PROXY_TOKEN;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  try {
    const v = fs.readFileSync(TOKEN_FILE, 'utf8').trim();
    if (v) return v;
  } catch {}
  const neu = randomBytes(32).toString('hex');
  try {
    fs.writeFileSync(TOKEN_FILE, neu + '\n', { mode: 0o600 });
    fs.chmodSync(TOKEN_FILE, 0o600);
    console.log(`Proxy-Token neu erzeugt: ${TOKEN_FILE} (0600). `
      + 'Nicht im Log ausgegeben.');
  } catch (e) {
    console.error(`KANN KEIN TOKEN-ABGESPEICHERT: ${e.message}. `
      + 'Setze MICRO_TRADER_PROXY_TOKEN in der Unit.');
  }
  return neu;
}

const TOKEN = loadToken();
const TOKEN_BUF = Buffer.from(TOKEN, 'utf8');

function tokenOk(req) {
  const h = (req.headers['authorization'] || '');
  const bearer = h.startsWith('Bearer ') ? h.slice(7).trim() : '';
  const alt = (req.headers['x-proxy-token'] || '');
  for (const kandidat of [bearer, String(alt).trim()]) {
    if (!kandidat) continue;
    const b = Buffer.from(kandidat, 'utf8');
    // timingSafeEqual braucht gleiche Laenge, sonst wirft es.
    if (b.length === TOKEN_BUF.length && timingSafeEqual(b, TOKEN_BUF)) return true;
  }
  return false;
}

// Ohne Auth: exakt 401, kein Body der interne Pfade verraet.
function unauthorized(res) {
  res.statusCode = 401;
  res.setHeader('WWW-Authenticate', 'Bearer realm="micro-trader-proxy"');
  res.end(JSON.stringify({ ok: false, error: 'unauthorized' }));
  return;
}

async function collectDepotsLocal() {
  const { stdout } = await execAsync(`bash ${REMOTE_BASE}/collect_depots.sh`, { maxBuffer: 32 * 1024 * 1024, timeout: 30000 });
  return parseDepotDump(stdout);
}

function parseDepotDump(text) {
  const parts = text.split('---FILE---').map((s) => s.trim()).filter(Boolean);
  const portfolios = [];
  let active = null;
  for (const part of parts) {
    if (part.includes('=== ACTIVE ===') && !part.includes('---FILE---')) {
      const m = part.match(/=== ACTIVE ===\s*(\{[^]*?\})\s*=== DEPOTS ===/);
      if (m) { try { active = JSON.parse(m[1]); } catch {} }
      continue;
    }
    const nl = part.indexOf('\n');
    const fname = part.slice(0, nl).trim();
    const jsonStr = part.slice(nl + 1).trim();
    try {
      const d = JSON.parse(jsonStr);
      const id = fname.split('/').pop().replace('.json', '');
      const positions = Object.entries(d.positions || {}).map(([ticker, pos]) => ({
        ticker, shares: pos.shares, avg: pos.avg_price, entry: pos.entry_price,
        stop_loss: pos.stop_loss, take_profit: pos.take_profit,
      }));
      const value = (d.bargeld || 0) + positions.reduce((s, x) => s + x.shares * x.avg, 0);
      portfolios.push({
        id, name: id.replace('depot_', 'Depot ').replace('_paper', ' (Paper)').replace('_shadow', ' (Shadow)'),
        mode: id.includes('paper') ? 'paper' : id.includes('shadow') ? 'shadow' : 'live',
        cash: d.bargeld || 0, startValue: d.start_wert || 0,
        value: Math.round(value * 100) / 100, positions: positions.length,
        holdings: positions, trades: d.trades || [],
      });
    } catch (e) {}
  }
  return { active: active?.aktiv, portfolios };
}

async function readJsonLocal(path) {
  try {
    const { stdout } = await execAsync(`cat ${REMOTE_BASE}/${path} 2>/dev/null`);
    return JSON.parse(stdout);
  } catch { return null; }
}

let quoteCache = [];
let quoteCacheTime = 0;

const server = createServer(async (req, res) => {
  // Kein ACAO: * mehr. Der Dienst ist loopback-gebunden; ein Wildcard-CORS
  // war fuer jede Webseite im LAN eine Leseberechtigung.
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;
  try {
    // /api/health bleibt ohne Token, gibt aber ausschliesslich {ok, ts} zurueck.
    if (p === '/api/health') return res.end(JSON.stringify({ ok: true, ts: Date.now() }));

    if (!tokenOk(req)) return unauthorized(res);

    if (p === '/api/portfolios' || p === '/api/depots') {
      const { active, portfolios } = await collectDepotsLocal();
      return res.end(JSON.stringify({ ok: true, active, portfolios }));
    }

    if (p === '/api/ki-pool' || p === '/api/providers') {
      const pool = await readJsonLocal('ki_pool.json');
      if (!pool) return res.end(JSON.stringify({ ok: false, error: 'no pool' }));
      const providers = {};
      for (const m of pool.modelle || []) {
        if (!providers[m.provider]) providers[m.provider] = { name: m.provider, models: 0, latency: m.latenz_s };
        providers[m.provider].models++;
      }
      return res.end(JSON.stringify({ ok: true, aktualisiert: pool.aktualisiert, anzahl: pool.anzahl, providers: Object.values(providers) }));
    }

    if (p === '/api/ki-decisions' || p === '/api/decisions') {
      const log = await readJsonLocal('ki_log.json');
      const decisions = Array.isArray(log) ? log : (log?.decisions || log?.entries || []);
      return res.end(JSON.stringify({ ok: true, count: decisions.length, decisions: decisions.slice(-50) }));
    }

    if (p === '/api/ki-rules' || p === '/api/rules') {
      const rules = await readJsonLocal('ki_regeln.json');
      return res.end(JSON.stringify({ ok: true, rules: rules || {} }));
    }

    if (p === '/api/news') {
      const news = await readJsonLocal('news_cache.json');
      const items = news?.headlines || news?.items || (Array.isArray(news) ? news : []);
      return res.end(JSON.stringify({ ok: true, items: items.slice(-40) }));
    }

    if (p === '/api/analysis') {
      const a = await readJsonLocal('analysis_cache.json');
      if (!a) return res.end(JSON.stringify({ ok: false, error: 'no analysis' }));
      const cats = ['aktien', 'etf', 'spekulation', 'risiko_aktien', 'risiko_etf', 'risiko_spekulation'];
      const rows = [];
      const summary = {};
      for (const cat of cats) {
        const block = a[cat];
        if (!block || typeof block !== 'object') continue;
        summary[cat] = {
          depots: block.depots, total_trades: block.total_trades,
          buys: block.buys, sells: block.sells, wert: block.wert, rendite: block.rendite,
        };
        const top = Array.isArray(block.top_ticker) ? block.top_ticker : [];
        for (const [ticker, stat] of top) {
          rows.push({ kategorie: cat, ticker, ...stat });
        }
      }
      return res.end(JSON.stringify({ ok: true, zeit: a.zeit, summary, topTickers: rows }));
    }

    if (p === '/api/system') {
      const { stdout } = await execAsync(`${REMOTE_BASE}/probe_system.sh`);
      const memLine = (stdout.match(/Mem:\s+(\d+)\s+(\d+)\s+(\d+)/) || [])[0];
      const diskLine = (stdout.match(/\/dev\/mapper\/[\w-]+\s+[\d.G]+\s+[\d.G]+\s+[\d.G]+\s+(\d+)%/) || [])[1];
      const load = (stdout.match(/load average:\s+([\d.]+)/) || [])[1];
      const up = (stdout.match(/up\s+(.+?),\s+\d+ users/) || [])[1];
      const svc = stdout.match(/micro-trader\.service\s+(\w+)/);
      return res.end(JSON.stringify({
        ok: true,
        uptime: up || null,
        load: load || null,
        memUsedMb: memLine ? parseInt(memLine.split(/\s+/)[2]) : null,
        memTotalMb: memLine ? parseInt(memLine.split(/\s+/)[1]) : null,
        diskUsePct: diskLine ? parseInt(diskLine) : null,
        serviceMicroTrader: svc ? svc[1] : 'unknown',
        raw: stdout,
      }));
    }

    const tsMatch = p.match(/^\/api\/timeseries\/(.+)$/);
    if (tsMatch) {
      const depotId = decodeURIComponent(tsMatch[1]);
      const depots = await collectDepotsLocal();
      const pf = depots.portfolios.find((x) => x.id === depotId);
      if (!pf) return res.end(JSON.stringify({ ok: false, error: 'depot not found', depot: depotId }));
      const fname = pf.id === 'depot' ? 'depot.json' : `depot_${pf.id.replace('depot_', '')}.json`;
      const { stdout } = await execAsync(`/opt/micro-trader/venv/bin/python3 timeseries.py ${fname}`, { cwd: '/opt/micro-trader', maxBuffer: 8 * 1024 * 1024, timeout: 25000 });
      try { const timeline = JSON.parse(stdout); return res.end(JSON.stringify({ ok: true, depot: pf.id, points: timeline })); }
      catch { return res.end(JSON.stringify({ ok: false, error: 'parse fail', raw: stdout.slice(0, 200) })); }
    }

    if (p === '/api/quotes') {
      if (quoteCache.length > 0 && Date.now() - quoteCacheTime < 60000) {
        return res.end(JSON.stringify({ ok: true, quotes: quoteCache, count: quoteCache.length, cached: true }));
      }
      const { portfolios } = await collectDepotsLocal();
      const tickers = new Set();
      for (const pf of portfolios) {
        for (const h of pf.holdings) tickers.add(h.ticker);
      }
      const list = Array.from(tickers).slice(0, 50).join(',');
      let quotes;
      try {
        const { stdout } = await execAsync(`/opt/micro-trader/venv/bin/python3 fetch_quotes.py ${list}`, { cwd: '/opt/micro-trader', maxBuffer: 8 * 1024 * 1024, timeout: 45000 });
        quotes = JSON.parse(stdout);
        quoteCache = Array.isArray(quotes) ? quotes : [];
        quoteCacheTime = Date.now();
      } catch (e) {
        if (quoteCache.length > 0 && Date.now() - quoteCacheTime < 120000) {
          quotes = quoteCache;
        } else {
          quotes = [];
        }
      }
      return res.end(JSON.stringify({ ok: true, quotes: Array.isArray(quotes) ? quotes : [], count: Array.isArray(quotes) ? quotes.length : 0, cached: quoteCache.length > 0 && quotes === quoteCache }));
    }

    if (p === '/api/report/pdf') {
      const url = new URL(req.url, `http://localhost:${PORT}`);
      const theme = url.searchParams.get('theme') || 'light';
      await new Promise((resolve, reject) => {
        let settled = false;
        const proc = exec(
          `/opt/micro-trader/venv/bin/python3 ${REMOTE_BASE}/proxy/generate_pdf_report.py ${theme}`,
          { maxBuffer: 64 * 1024 * 1024, timeout: 90000, env: { ...process.env } },
          (err, stdout, stderr) => {
            if (settled) return;
            settled = true;
            if (err) {
              const msg = (stderr || err.message || '').slice(-300);
              res.statusCode = 500;
              res.end(JSON.stringify({ ok: false, error: msg }));
              reject(msg);
              return;
            }
            const match = stdout.match(/SUCCESS: (.+?)(?: \([\d.]+ bytes\))??[\s\n]*$/);
            if (match) {
              const pdfPath = match[1].trim();
              res.setHeader('Content-Type', 'application/pdf');
              res.setHeader('Content-Disposition', `attachment; filename="microtrader-report-${theme}.pdf"`);
              const stream = fs.createReadStream(pdfPath);
              stream.on('error', (e) => {
                res.statusCode = 500;
                res.end(JSON.stringify({ ok: false, error: String(e) }));
                reject(e);
              });
              stream.pipe(res);
              resolve(null);
            } else {
              res.statusCode = 500;
              res.end(JSON.stringify({ ok: false, error: stdout.slice(-300) }));
              resolve(null);
            }
          }
        );
      });
      return;
    }

    res.statusCode = 404;
    res.end(JSON.stringify({ error: 'not found', path: p }));
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: String(e) }));
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Micro-Trader Read-Only Proxy auf http://${HOST}:${PORT} `
    + '(authpflichtig, ausser /api/health)');
});