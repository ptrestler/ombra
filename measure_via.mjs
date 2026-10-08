// Which fountain should "Route via one" bend a walk through? This scores the
// rule in web/template.html (routeVia) on random dry walks, so a change to it
// can be measured rather than assumed. Needs a build: `make`, then
//   node measure_via.mjs [k]        k = 1.2 Balanced (default), 4 Shadiest
//
// A walk counts as dry when the card would say so: no nasone within 40 m, or a
// stretch of 400 m or more without one. Walks are 0.8-2.5 km, at 14:00 on
// 15 July, between random nodes of the main network, from a fixed seed.
import { chromium } from 'playwright';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { existsSync } from 'node:fs';

const page_ = resolve(dirname(fileURLToPath(import.meta.url)), 'dist/ombra-roma.html');
if (!existsSync(page_)) { console.error('build it first: make'); process.exit(1); }
const k = parseFloat(process.argv[2] || '1.2');
const exe = process.env.PLAYWRIGHT_CHROMIUM_PATH;
const b = await chromium.launch(exe ? { executablePath: exe } : {});
const p = await b.newPage({ viewport: { width: 1200, height: 800 } });
await p.goto(pathToFileURL(page_).href);
await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                        { timeout: 60000 });
const out = await p.evaluate(k => {
  const o = window.ombra, st = o.st, H = o.head;
  st.mo = 6; st.day = 15; st.ti = 16; st.live = false; st.k = k; st.routing = true;
  let seed = 7;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const rows = []; let tv = 0;
  for (let tries = 0; rows.length < 300 && tries < 5000; tries++) {
    const a = Math.floor(rnd() * H.nnode), bb = Math.floor(rnd() * H.nnode);
    if (o.comp(a) !== o.bigc() || o.comp(bb) !== o.bigc()) continue;
    const [ax, ay] = o.nodeXY(a), [bx, by] = o.nodeXY(bb), d = Math.hypot(ax - bx, ay - by);
    if (d < 800 || d > 2500) continue;
    st.a = a; st.b = bb; st.via = false; o.recompute();
    const r = st.route;
    if (!r || !(r.naso.n === 0 || r.naso.gap >= 400)) continue;
    st.via = true;
    const t0 = performance.now(); o.recompute(); tv += performance.now() - t0;
    const v = st.route;
    rows.push({ add: v.len - r.len, gap0: r.naso.gap, gap1: v.naso.gap });
  }
  st.via = false;
  return { rows, ms: tv / rows.length };
}, k);
await b.close();

const r = out.rows;
const q = (xs, f) => { const s = xs.slice().sort((x, y) => x - y);
                       return Math.round(s[Math.floor(f * (s.length - 1))]); };
console.log(`${r.length} dry walks, k = ${k}, ${out.ms.toFixed(0)} ms per recompute with the stop`);
console.log(`metres added         p25 ${q(r.map(x => x.add), .25)}  median ${q(r.map(x => x.add), .5)}` +
            `  p75 ${q(r.map(x => x.add), .75)}  p90 ${q(r.map(x => x.add), .9)}`);
console.log(`longest dry stretch  median ${q(r.map(x => x.gap0), .5)} -> ${q(r.map(x => x.gap1), .5)}` +
            `   p90 ${q(r.map(x => x.gap0), .9)} -> ${q(r.map(x => x.gap1), .9)}`);
console.log(`cut by a quarter or more: ${Math.round(100 * r.filter(x => x.gap1 <= .75 * x.gap0).length / r.length)} %`);
