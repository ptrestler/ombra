// Does choosing the ORDER of a day's stops for shade beat walking a sensible
// order on shady streets? The answer decides whether a day planner is worth
// its UI. Needs a build: `make`, then
//   node measure_days.mjs [days] [stops] [start]   defaults 200 days, 5 stops, 9 (o'clock)
//
// A day: a start and N stops drawn from the page's own landmark shortlist,
// leaving at 09:00 (or the hour given) on 15 July, walking 75 m/min (the pace the route card
// quotes), 30 min at each stop, ending at the last stop. Every leg is
// routed at the half-hour it actually starts, so the sun moves as the day
// does. Three strategies over the same days:
//
//   A  shortest  the order that walks least, on the shortest routes
//   B  shady     that same order, each leg routed Balanced for its own
//                hour - what the app can already do, one leg at a time
//   C  planned   the order, of all N!, with the least shade-weighted cost
//                (the router's own currency) given each leg's hour, routed
//                the same way
//
// Scored on metres walked in the sun, metres walked, and the hour the day
// ends. C over B is the question; B over A is what already ships.
import { chromium } from 'playwright';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { existsSync } from 'node:fs';

const page_ = resolve(dirname(fileURLToPath(import.meta.url)), 'dist/ombra-roma.html');
if (!existsSync(page_)) { console.error('build it first: make'); process.exit(1); }
const DAYS = +(process.argv[2] || 200), STOPS = +(process.argv[3] || 5), HOUR = +(process.argv[4] || 9);
const exe = process.env.PLAYWRIGHT_CHROMIUM_PATH;
const b = await chromium.launch(exe ? { executablePath: exe } : {});
const p = await b.newPage({ viewport: { width: 1200, height: 800 } });
await p.goto(pathToFileURL(page_).href);
await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                        { timeout: 60000 });
const t0 = Date.now();
const out = await p.evaluate(([DAYS, STOPS, HOUR]) => {
  const o = window.ombra, st = o.st, H = o.head;
  st.live = false; st.today = null; st.mo = 6; st.day = 15; st.via = false; st.routing = true;
  const PACE = 75, DWELL = 30, START = HOUR * 60, K = 1.2;
  // the shortlist, as street nodes
  const nodes = [];
  for (const e of o.searchDest('')) {
    if (e.kind === 2) continue;                       // saved places are not landmarks
    const xy = o.entryXY(e); if (!xy) continue;
    const n = o.nearestNode(xy[0], xy[1]);
    if (n >= 0 && !nodes.includes(n)) nodes.push(n);
  }
  // one leg at one hour, cached: {len, sun, cost}
  const cache = new Map();
  const leg = (a, b, minute, k) => {
    const slot = Math.max(0, Math.min(31, Math.round((minute - 360) / 30)));
    const key = a + '|' + b + '|' + slot + '|' + k;
    let r = cache.get(key);
    if (!r) {
      st.a = a; st.b = b; st.k = k; st.ti = slot; o.recompute();
      const R = st.route;
      r = R ? { len: R.len, sun: R.len * (1 - R.shade / 100), cost: R.len * (1 + k * (1 - R.shade / 100)) }
            : { len: 1e9, sun: 1e9, cost: 1e9 };
      cache.set(key, r);
    }
    return r;
  };
  const walk = (order, k) => {
    let t = START, len = 0, sun = 0, cost = 0;
    for (let i = 1; i < order.length; i++) {
      const r = leg(order[i - 1], order[i], t, k);
      len += r.len; sun += r.sun; cost += r.cost;
      t += r.len / PACE + (i < order.length - 1 ? DWELL : 0);
    }
    return { len, sun, cost, end: t };
  };
  const perms = arr => arr.length <= 1 ? [arr] :
    arr.flatMap((x, i) => perms([...arr.slice(0, i), ...arr.slice(i + 1)]).map(r => [x, ...r]));
  let seed = 11;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const rows = [];
  for (let d = 0; d < DAYS; d++) {
    const pick = [];
    while (pick.length < STOPS + 1) {
      const n = nodes[Math.floor(rnd() * nodes.length)];
      if (!pick.includes(n)) pick.push(n);
    }
    const [s, ...stops] = pick;
    const orders = perms(stops).map(q => [s, ...q]);
    // A: least walking (distance does not depend on the hour, so the k=0 route at 09:00 will do)
    let A = null, bestLen = Infinity;
    for (const q of orders) { const w = walk(q, 0); if (w.len < bestLen) { bestLen = w.len; A = q; } }
    // C: least shade-weighted cost, every leg at its own hour
    let C = null, bestCost = Infinity;
    for (const q of orders) { const w = walk(q, K); if (w.cost < bestCost) { bestCost = w.cost; C = q; } }
    const a = walk(A, 0), bb = walk(A, K), c = walk(C, K);
    rows.push({ a, b: bb, c, same: A.join() === C.join() });
  }
  return { rows, nodes: nodes.length, legs: cache.size };
}, [DAYS, STOPS, HOUR]);
await b.close();

const r = out.rows;
const med = xs => { const s = xs.slice().sort((x, y) => x - y); return s[Math.floor((s.length - 1) / 2)]; };
const pct = (x, y) => 100 * (y - x) / x;
const hm = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(Math.round(m % 60)).padStart(2, '0')}`;
console.log(`${r.length} days of ${STOPS} stops from ${out.nodes} landmarks, 15 July from ${String(HOUR).padStart(2, '0')}:00; ` +
            `${out.legs} legs routed, ${Math.round((Date.now() - t0) / 1000)} s\n`);
for (const [k, name] of [['a', 'A shortest'], ['b', 'B shady   '], ['c', 'C planned ']])
  console.log(`${name}  sun ${Math.round(med(r.map(x => x[k].sun)))} m   walked ${Math.round(med(r.map(x => x[k].len)))} m` +
              `   ends ${hm(med(r.map(x => x[k].end)))}        (medians)`);
const bc = r.map(x => pct(x.b.sun, x.c.sun)), ab = r.map(x => pct(x.a.sun, x.b.sun));
console.log(`\nB over A, sun:  median ${med(ab).toFixed(1)} %`);
console.log(`C over B, sun:  median ${med(bc).toFixed(1)} %   ` +
            `days C saves >10 %: ${Math.round(100 * r.filter((x, i) => bc[i] < -10).length / r.length)} %   ` +
            `>25 %: ${Math.round(100 * r.filter((x, i) => bc[i] < -25).length / r.length)} %`);
console.log(`C over B, walked: median ${med(r.map(x => pct(x.b.len, x.c.len))).toFixed(1)} %`);
console.log(`C picks the same order as A on ${Math.round(100 * r.filter(x => x.same).length / r.length)} % of days`);
