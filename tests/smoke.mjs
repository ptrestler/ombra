// Browser checks for the built page. Runs in Chromium and WebKit, and in WebKit
// with the Streams API broken, because that is what iOS Quick Look does.
import { chromium, webkit, devices } from 'playwright';
import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const page_ = resolve(root, 'dist/ombra-roma.html');
if (!existsSync(page_)) { console.error('build it first: make'); process.exit(1); }
const url = pathToFileURL(page_).href;
let failures = 0;
const check = (name, ok, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) failures++;
};

// Optional overrides for environments where the browsers aren't in Playwright's
// default location. Normally unset - `npx playwright install` is enough.
const EXE = { chromium: process.env.PLAYWRIGHT_CHROMIUM_PATH,
              webkit:   process.env.PLAYWRIGHT_WEBKIT_PATH };

async function run(engine, label, breakStreams, which) {
  const exe = EXE[which];
  const browser = await engine.launch(exe ? { executablePath: exe } : {});
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  if (breakStreams) await ctx.addInitScript(() => {
    try { delete window.DecompressionStream; } catch {}
    try { Blob.prototype.stream = () => ({ pipeThrough: () => ({}) }); } catch {}
  });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  p.on('console', m => { if (m.type() === 'error' && !/ERR_|fonts\.googleapis/.test(m.text())) errs.push(m.text()); });
  await p.route('**fonts.googleapis.com**', r => r.abort());   // must work offline
  console.log(`\n${label}`);
  const t0 = Date.now();
  await p.goto(url, { waitUntil: 'domcontentloaded' });
  let booted = true;
  await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                          { timeout: 45000 }).catch(() => { booted = false; });
  check('boots', booted, `${Date.now() - t0} ms`);
  if (booted) {
    check('standards mode, not quirks', await p.evaluate(() => document.compatMode) === 'CSS1Compat');
    // the clock and its date are one line; on an iPhone "· Rome time" wrapped
    check('the clock reads on one line', await p.evaluate(() =>
      document.querySelector('.clock').getBoundingClientRect().height < 45));
    check('no horizontal scroll at phone width',
          !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    // data round-trip: these must match tests/validate.py exactly
    const d = await p.evaluate(() => {
      const O = window.ombra, H = O.head, D = O.data, base = ((8 - 1) * 2 + 1) * 32;
      O.loadDate((8 - 1) * 2 + 1);             // shade is unpacked a date at a time
      const at = (name, h) => {
        const ni = H.names.indexOf(name); if (ni < 0) return null;
        let s = 0, n = 0;
        for (let i = 0; i < H.nseg; i++) if (D.name[i] === ni) { s += D.shade[i * H.nframe + base + (h - 6) * 2]; n++; }
        return n ? +(s / n).toFixed(1) : null;
      };
      return { fori: at('Via dei Fori Imperiali', 14), trilussa: at('Piazza Trilussa', 18) };
    });
    check('Fori Imperiali unshaded at 14:00', d.fori === 0, `${d.fori}%`);
    // Shade is unpacked one date at a time, so a date can be missing or land in
    // the wrong frames without the named streets noticing. The build ships the
    // city mean of every frame; unpack every date and recompute it from D.shade.
    const rt = await p.evaluate(() => {
      const O = window.ombra, H = O.head, D = O.data;
      let worst = 0, at = -1;
      for (let d = 0; d < H.ndate; d++) O.loadDate(d);
      for (let f = 0; f < H.nframe; f++) {
        let s = 0; for (let i = 0; i < H.nseg; i++) s += D.shade[i * H.nframe + f];
        const e = Math.abs(s / H.nseg - H.city[f]);
        if (e > worst) { worst = e; at = f; }
      }
      return { worst: +worst.toFixed(3), at, n: H.nframe };
    });
    check('every date unpacks into its own frames', rt.worst <= 0.006,
          `worst frame ${rt.at} of ${rt.n} off by ${rt.worst} pp`);
    check('Piazza Trilussa shaded at 18:00', d.trilussa > 85, `${d.trilussa}%`);
    // street lookup and routing
    await p.fill('#search', 'Via Giulia'); await p.press('#search', 'Enter');
    await p.waitForTimeout(500);
    check('street search', (await p.textContent('#cName')) === 'Via Giulia');
    // The field used to match only on Enter, on the first substring it found in
    // map order. Rome has hundreds of streets that start the same way.
    await p.fill('#search', 'Via dei Co'); await p.waitForTimeout(250);
    const sug = await p.evaluate(() => [...document.querySelectorAll('#sugg .sg')]
      .map(b => b.textContent.trim()));
    check('typing suggests streets', sug.length > 1 && sug.length <= 8,
          sug.slice(0, 3).join(' | '));
    check('and every one of them matches what was typed',
          sug.every(n => n.toLowerCase().includes('via dei co')));
    await p.press('#search', 'ArrowDown'); await p.press('#search', 'ArrowDown');
    const picked = await p.evaluate(() =>
      document.querySelector('#sugg .sg[aria-selected="true"]').textContent.trim());
    await p.press('#search', 'Enter'); await p.waitForTimeout(400);
    check('arrow keys and Enter take the one you chose',
          (await p.textContent('#cName')) === picked, picked);
    check('and the list closes behind it',
          await p.evaluate(() => document.querySelector('#sugg').hidden));
    await p.fill('#search', 'Via dei Co'); await p.waitForTimeout(250);
    await p.press('#search', 'Escape'); await p.waitForTimeout(150);
    check('Escape dismisses the suggestions',
          await p.evaluate(() => document.querySelector('#sugg').hidden));
    await p.fill('#search', 'Margutta'); await p.waitForTimeout(250);
    await p.click('#sugg .sg'); await p.waitForTimeout(400);
    check('and tapping one works on a phone',
          /Margutta/.test(await p.textContent('#cName')),
          await p.textContent('#cName'));
    await p.click('#cClose'); await p.waitForTimeout(200);
    // The console was 49% of a phone screen. The date grid folds away, and the
    // search box must not go with it - that regression cost "Find a street".
    const conH = () => p.evaluate(() => Math.round(100 *
      document.querySelector('#console').getBoundingClientRect().height / innerHeight));
    const collapsed = await conH();
    check('console starts folded and leaves the map most of the screen',
          collapsed < 40, `${collapsed}% of the viewport`);
    check('search survives folding', await p.locator('#search').isVisible());
    await p.click('#conToggle'); await p.waitForTimeout(250);
    const open_ = await conH();
    check('unfolding brings the date grid back', open_ > collapsed &&
          await p.locator('#months').isVisible(), `${collapsed}% -> ${open_}%`);
    await p.click('#conToggle'); await p.waitForTimeout(250);
    // opens on the sampled date and half-hour nearest the device clock
    const when = await p.evaluate(() => {
      const n = new Date(), st = window.ombra.st;
      const ti = Math.max(0, Math.min(31, Math.round((n.getHours() + n.getMinutes()/60 - 6) * 2)));
      const dom = n.getDate();
      let mo = n.getMonth(), day;
      if (dom < 8) day = 1; else if (dom < 23) day = 15; else { day = 1; mo = (mo+1)%12; }
      return { got:[st.mo, st.day, st.ti], want:[mo, day, ti] };
    });
    // ti within one slot, not equal: the page picks its moment at load and this
    // recomputes seconds later, so a run that straddles a half-hour boundary
    // would fail on a correct build.
    check('opens at the moment nearest now, not a hardcoded August',
          when.got[0] === when.want[0] && when.got[1] === when.want[1] &&
          Math.abs(when.got[2] - when.want[2]) <= 1,
          `${when.got} vs ${when.want}`);
    // Zoom used to be scroll-only, and the wheel handler read deltaY as pixels -
    // so one Firefox notch (3 *lines*) zoomed by half a percent. The buttons are
    // the discoverable way in; they must survive the panel z-order too.
    const scale = () => p.evaluate(() => window.ombra.st.scale);
    await p.click('#btnZfit'); await p.waitForTimeout(150);
    const z0 = await scale();
    await p.click('#btnZin'); await p.waitForTimeout(150); const z1 = await scale();
    await p.click('#btnZout'); await p.waitForTimeout(150); const z2 = await scale();
    check('zoom buttons zoom, and round-trip', z1 > z0 * 1.5 && Math.abs(z2 - z0) < 1e-9,
          `${z0.toFixed(3)} -> ${z1.toFixed(3)} -> ${z2.toFixed(3)}`);
    // The map could be dragged until half the screen was empty. Zoomed in, a
    // hard drag each way must stop with the map's edge within a panel's height
    // of the screen's edge: 84 px under the masthead, 40 px elsewhere.
    const edges = () => p.evaluate(() => {
      const o = window.ombra, st = o.st, b = o.head.bbox, s = document.querySelector('#stage');
      const W = s.clientWidth, H = s.clientHeight;
      return { l: (b.x0 - st.cx) * st.scale + W / 2, r: W - ((b.x1 - st.cx) * st.scale + W / 2),
               t: (st.cy - b.y1) * st.scale + H / 2, b: H - ((st.cy - b.y0) * st.scale + H / 2) };
    });
    await p.click('#btnZin'); await p.click('#btnZin'); await p.waitForTimeout(150);
    const sb0 = await p.locator('#stage').boundingBox();
    const cx0 = sb0.x + sb0.width / 2, cy0 = sb0.y + sb0.height / 2;
    const gaps = {};
    for (const [k, dx, dy] of [['l', 1, 0], ['r', -1, 0], ['t', 0, 1], ['b', 0, -1]]) {
      for (let i = 0; i < 12; i++) {           // twelve hard flings, far past any edge
        await p.mouse.move(cx0, cy0); await p.mouse.down();
        await p.mouse.move(cx0 + dx * 150, cy0 + dy * 150, { steps: 3 }); await p.mouse.up();
      }
      await p.waitForTimeout(60);
      gaps[k] = Math.round((await edges())[k]);
    }
    check('the map cannot be dragged off the screen', gaps.l <= 41 && gaps.r <= 41 &&
          gaps.t <= 85 && gaps.b <= 41, JSON.stringify(gaps) + ' px of empty edge');
    for (let i = 0; i < 12; i++) {             // until the button gives up
      if (await p.evaluate(() => document.querySelector('#btnZout').disabled)) break;
      await p.click('#btnZout');
    }
    await p.waitForTimeout(150);
    const out = await edges();
    check('or zoomed out past the whole map', Math.min(out.l + out.r, out.t + out.b) <= 2 &&
          await p.evaluate(() => document.querySelector('#btnZout').disabled),
          `smallest margin pair ${Math.round(Math.min(out.l + out.r, out.t + out.b))} px`);
    await p.click('#btnZfit'); await p.waitForTimeout(150);
    const wheelZoom = (deltaY, deltaMode) => p.evaluate(([dy, dm]) => {
      const st = window.ombra.st, before = st.scale, stage = document.querySelector('#stage');
      const r = stage.getBoundingClientRect();
      stage.dispatchEvent(new WheelEvent('wheel', { deltaY: dy, deltaMode: dm, bubbles: true,
        cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
      const after = st.scale; st.scale = before; return after / before;
    }, [deltaY, deltaMode]);
    const px = await wheelZoom(-100, 0), line = await wheelZoom(-3, 1);
    check('one wheel notch zooms the same in pixel and line mode',
          px > 1.15 && Math.abs(px - line) < 1e-6, `${px.toFixed(3)} vs ${line.toFixed(3)}`);
    // a stray tap selects a street; Escape has to put it away again
    await p.click('#btnZfit'); await p.waitForTimeout(150);
    await p.fill('#search', 'Via Giulia'); await p.press('#search', 'Enter');
    await p.waitForTimeout(400);
    await p.evaluate(() => document.activeElement.blur());
    await p.keyboard.press('Escape'); await p.waitForTimeout(200);
    check('Escape closes a street card you did not mean to open',
          !(await p.evaluate(() => document.querySelector('#card').classList.contains('open'))));
    // Pin the clock. The page opens on whatever sampled moment is nearest to now,
    // so on a UTC runner these route checks ran at 20:00 - when the whole city is
    // shaded, the shadiest way IS the shortest, and the comparison text they
    // assert never appears. The checks below describe a specific afternoon.
    const setClock = (mo, day, ti) => p.evaluate(([m, d, t]) => {
      const st = window.ombra.st; st.mo = m; st.day = d; st.ti = t;
      const el = document.querySelector('#time');
      el.value = t; el.dispatchEvent(new Event('input', { bubbles: true }));
    }, [mo, day, ti]);
    await setClock(7, 15, 16);                       // 14:00, 15 August
    await p.waitForTimeout(250);

    await p.click('#btnRoute'); await p.waitForTimeout(300);
    // the card opens with the A picker already showing; tapping the end it is
    // asking about must not close the search out from under you
    await p.click('#rFrom'); await p.waitForTimeout(200);
    check('empty picker stays open when tapped',
          await p.evaluate(() => document.querySelector('#rcard').classList.contains('picking')));
    // Two nested scrollers fought each other and showed three suggestions. The
    // fix for that took the whole map instead, which answered "where is that?"
    // with a blank wall. Both numbers have to hold at once now.
    const pick = await p.evaluate(() => {
      const card = document.querySelector('#rcard'), list = document.querySelector('#rResults');
      const row = document.querySelector('.res').getBoundingClientRect().height;
      const stage = document.querySelector('#stage').getBoundingClientRect();
      const c = card.getBoundingClientRect(), z = document.querySelector('#zoomctl');
      return { cardScrolls: card.scrollHeight > card.clientHeight + 1,
               fits: Math.floor(list.clientHeight / row),
               mapPct: Math.round((c.top - stage.top) / stage.height * 100),
               consoleGone: getComputedStyle(document.querySelector('#console')).display === 'none',
               rows: document.querySelectorAll('#rResults .res').length,
               zoom: getComputedStyle(z).display !== 'none' &&
                     z.getBoundingClientRect().bottom <= c.top + 1 };
    });
    check('the results list is the only thing that scrolls, and shows a useful number',
          !pick.cardScrolls && pick.fits >= 5, `${pick.fits} suggestions visible`);
    // with the search field gone the shortlist is the only way in besides the map
    check('the shortlist still offers the landmarks', pick.rows >= 20, `${pick.rows} places`);
    check('and the map is still there to look at', pick.mapPct >= 35,
          `${pick.mapPct}% of the map area`);
    check('the console steps aside to pay for it', pick.consoleGone);
    check('the zoom controls stay above the sheet', pick.zoom);
    // A and B are fields: typing filters the list under whichever has the cursor
    await p.fill('#rFromI', 'Pantheon'); await p.waitForTimeout(250);
    const typed = await p.evaluate(() =>
      [...document.querySelectorAll('#rResults .res')].map(b => b.textContent));
    check('typing in the start field filters the list',
          typed.length > 0 && typed.every(t => /pantheon/i.test(t)),
          `${typed.length} matches`);
    await p.press('#rFromI', 'Enter'); await p.waitForTimeout(400);
    check('Enter takes the top match, and the field keeps it',
          await p.inputValue('#rFromI') === 'Pantheon',
          await p.inputValue('#rFromI'));
    // answering "where are you now?" should ask "where are you going?" by itself
    check('picking the start moves straight on to the destination',
          await p.evaluate(() => window.ombra.st.pick) === 'b');
    // the point of seeing the map: the end you just chose is on it
    check('the start you chose is on the visible map', await p.evaluate(() => {
      const o = window.ombra, [x, y] = o.screenXY(o.st.a);
      const stage = document.querySelector('#stage').getBoundingClientRect();
      const top = document.querySelector('#rcard').getBoundingClientRect().top - stage.top;
      return x > 0 && x < stage.width && y > 74 && y < top;
    }));
    // "tap anywhere on the map" was printed over the whole map
    await p.click('#pickMap'); await p.waitForTimeout(250);
    check('picking on the map leaves you a map to pick from', await p.evaluate(() => {
      const stage = document.querySelector('#stage').getBoundingClientRect();
      const c = document.querySelector('#rcard').getBoundingClientRect();
      return (c.top - stage.top) / stage.height > 0.5;
    }));
    // and tapping the end it is already asking about is the way out of that mode
    await p.click('#rTo'); await p.waitForTimeout(250);
    check('tapping the open end again leaves map-pick for the list',
          await p.evaluate(() => !window.ombra.st.mapPick &&
            document.querySelectorAll('#rResults .res').length > 0));
    await p.locator('.res', { hasText: 'Colosseo' }).first().click();
    await p.waitForTimeout(600);
    const km = await p.textContent('#rTitle');
    check('routes Pantheon to Colosseo', /km/.test(km), km);
    check('shows the shortest-route comparison',
          /Shortest way/.test(await p.textContent('#rCompare')));
    // With the console hidden behind the route panel this strip is the only
    // time control a phone has left, and it is the better one - it plots this
    // route's shade rather than the city's. If it stops scrubbing, the hour is
    // stuck.
    const wasTi = await p.evaluate(() => window.ombra.st.ti);
    const sb = await p.locator('#rstrip').boundingBox();
    await p.mouse.click(sb.x + sb.width * 0.15, sb.y + sb.height / 2);
    await p.waitForTimeout(300);
    const nowTi = await p.evaluate(() => window.ombra.st.ti);
    check('the route strip sets the hour, now that it is the only thing that can',
          nowTi !== wasTi, `slot ${wasTi} -> ${nowTi}`);
    // ...and after sunset there is nothing to trade, which it should say rather
    // than quietly offering a detour that buys no shade
    await setClock(8, 15, 28);                       // 20:00, 15 September
    await p.evaluate(() => { window.ombra.recompute(); window.ombra.renderRoute(); });
    await p.waitForTimeout(300);
    check('after sunset it says a detour would buy nothing',
          /no detour needed/i.test(await p.textContent('#rCompare')),
          (await p.textContent('#rCompare')).replace(/\s+/g, ' ').trim().slice(0, 60));
    await setClock(7, 15, 16);
    await p.evaluate(() => { window.ombra.recompute(); window.ombra.renderRoute(); });
    await p.waitForTimeout(300);
    // The big percentage is painted with the map ramp, which is tuned for thin
    // lines over a map, not 31px text on a panel: a 73% landed on an indigo that
    // vanished into the dark card. rampInk keeps the hue and walks it toward the
    // panel's text colour until it is legible, so check the whole range - and in
    // both themes, because the fix has to work in each direction.
    const worstRamp = () => p.evaluate(() => {
      const T = s => { s = s.trim();
        if (s[0] === '#') { let h = s.slice(1);
          if (h.length === 3) h = h.split('').map(c => c + c).join('');
          return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)]; }
        const n = s.slice(s.indexOf('(')+1, s.indexOf(')')).split(',');
        return [+n[0], +n[1], +n[2]]; };
      const L = c => { const f = x => { x /= 255;
        return x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4); };
        return 0.2126*f(c[0]) + 0.7152*f(c[1]) + 0.0722*f(c[2]); };
      const cr = (a,b) => { const x = L(a), y = L(b);
        return (Math.max(x,y)+0.05) / (Math.min(x,y)+0.05); };
      const cs = getComputedStyle(document.documentElement);
      const p1 = T(cs.getPropertyValue('--panel')), p2 = T(cs.getPropertyValue('--panel-2'));
      let worst = 99;
      for (let v = 0; v <= 100; v++) {
        const c = T(window.ombra.rampInk(v));
        worst = Math.min(worst, cr(c,p1), cr(c,p2));
      }
      return +worst.toFixed(2);
    });
    const w1 = await worstRamp();
    await p.click('#btnTheme'); await p.waitForTimeout(250);
    const w2 = await worstRamp();
    await p.click('#btnTheme'); await p.waitForTimeout(250);
    check('every shade percentage stays legible on the card, both themes',
          w1 >= 4.5 && w2 >= 4.5, `worst ${w1} and ${w2}`);

    // metric and imperial, and the button says which you are looking at
    const dist = () => p.evaluate(() => document.querySelector('#rTitle').textContent);
    const inKm = await dist();
    await p.click('#btnUnits'); await p.waitForTimeout(300);
    const inMi = await dist();
    check('distances switch between km and miles',
          / km · /.test(inKm) && / mi · /.test(inMi) &&
          await p.evaluate(() => document.querySelector('#btnUnits').textContent) === 'mi',
          `${inKm}  ->  ${inMi}`);
    await p.click('#btnUnits'); await p.waitForTimeout(300);
    check('and switch back', await dist() === inKm);

    // must alternate, not recompute from the system each time - when storage is
    // blocked that bug makes the toggle stick on one theme for ever
    const gnd = () => p.evaluate(() => getComputedStyle(document.documentElement)
                                        .getPropertyValue('--ground').trim());
    const t0 = await gnd();
    await p.click('#btnTheme'); await p.waitForTimeout(250); const t1 = await gnd();
    await p.click('#btnTheme'); await p.waitForTimeout(250); const t2 = await gnd();
    check('theme toggle alternates', t0 !== t1 && t1 !== t2 && t0 === t2, `${t0} ${t1} ${t2}`);
    // the phone route panel fills the upper map, so the zoom stack steps aside
    // Nasoni: counted along the route, and the line only speaks when it has
    // something to act on, because it costs a line of card and the card costs map
    const naso = await p.evaluate(() => {
      const o = window.ombra, n = o.st.route.naso;
      return { all: o.head.nnaso, on: n.n, gap: Math.round(n.gap),
               line: document.querySelector('#rNaso').textContent.trim(),
               legend: document.querySelector('#legend').classList.contains('naso') };
    });
    check('the payload carries the fountains', naso.all > 300, `${naso.all} nasoni`);
    // a projection or quantisation slip would put them in the Tyrrhenian Sea
    check('and puts them inside the map', await p.evaluate(() => {
      const o = window.ombra, d = o.data, bb = o.head.bbox;
      for (let i = 0; i < d.naX.length; i++)
        if (d.naX[i] < bb.x0 || d.naX[i] > bb.x1 ||
            d.naY[i] < bb.y0 || d.naY[i] > bb.y1) return false;
      return d.naX.length === o.head.nnaso;
    }));
    check('and picks out the ones along a route',
          naso.on > 0 && naso.on < naso.all, `${naso.on} on the way, driest ${naso.gap} m`);
    check('the dry-stretch line speaks only when the stretch is long',
          naso.gap >= 400 ? /dry stretch/.test(naso.line) : naso.line === '',
          naso.line || '(silent, as it should be)');
    check('the legend explains them while they are on the map', naso.legend);

    // Via a nasone: a dry walk offers the stop, and taking it bends the walk
    // through a fountain without breaking it into pieces
    const keep = await p.evaluate(() => {
      const o = window.ombra, st = o.st, H = o.head, keep = { a: st.a, b: st.b };
      const [ax, ay] = o.nodeXY(st.a);
      for (let n = 0; n < H.nnode; n += 37) {
        if (o.comp(n) !== o.bigc()) continue;
        const [x, y] = o.nodeXY(n), d = Math.hypot(x - ax, y - ay);
        if (d < 1200 || d > 2500) continue;
        st.b = n; o.recompute();
        const na = st.route && st.route.naso;
        if (na && (na.n === 0 || na.gap >= 400)) break;
      }
      o.renderRoute();
      return keep;
    });
    const viaBtn = () => p.evaluate(() => {
      const b = document.querySelector('#rVia'); return b ? b.textContent : null; });
    check('a dry walk offers to route via a nasone', await viaBtn() === 'Route via one');
    await p.click('#rVia'); await p.waitForTimeout(300);
    const via = await p.evaluate(() => {
      const o = window.ombra, r = o.st.route, D = o.data;
      let joined = true;
      for (let i = 1; i < r.edges.length; i++) {
        const e0 = r.edges[i - 1], e1 = r.edges[i];
        const s0 = [D.eU[e0], D.eV[e0]];
        if (!s0.includes(D.eU[e1]) && !s0.includes(D.eV[e1])) joined = false;
      }
      return { via: r.via, on: r.via >= 0 && r.naso.idx.has(r.via), joined,
               len: Math.round(r.len), direct: r.direct && Math.round(r.direct.len),
               line: document.querySelector('#rNaso').textContent.trim(),
               band: (() => {
                 const s = document.querySelector('#stage').getBoundingClientRect();
                 const c = document.querySelector('#rcard').getBoundingClientRect();
                 return Math.round((c.top - s.top) / s.height * 100); })() };
    });
    check('and the walk then passes one', via.on, via.line);
    check('as one connected walk, no longer than it has to be',
          via.joined && via.len >= via.direct - 1, `${via.direct} m -> ${via.len} m`);
    check('and the card still leaves the route most of the screen', via.band >= 50, `${via.band}% map`);
    check('the stop can be taken back', await viaBtn() === 'Go direct');
    await p.click('#rVia'); await p.waitForTimeout(300);
    check('and taking it back restores the direct walk',
          await p.evaluate(() => window.ombra.st.route.via === -1 && !window.ombra.st.via));
    await p.evaluate(k => { const o = window.ombra; o.st.a = k.a; o.st.b = k.b;
                            o.recompute(); o.renderRoute(); }, keep);

    // the route card carries its own scrubber, and it is about this route
    check('the console stays out of the way while the route is up',
          await p.evaluate(() => getComputedStyle(document.querySelector('#console')).display === 'none'));
    const band = await p.evaluate(() => {
      const s = document.querySelector('#stage').getBoundingClientRect();
      const c = document.querySelector('#rcard').getBoundingClientRect();
      return Math.round((c.top - s.top) / s.height * 100); });
    check('which leaves the route itself most of the screen', band >= 50, `${band}% map`);
    // a control behind a panel is a control you do not have
    check('nothing in the zoom stack ends up behind the route card',
          await p.evaluate(() => {
            const c = document.querySelector('#rcard').getBoundingClientRect();
            return [...document.querySelectorAll('#zoomctl .iconbtn')]
              .filter(b => b.offsetParent !== null)
              .every(b => b.getBoundingClientRect().bottom <= c.top + 1); }));
    check('close button is clickable (z-order)',
          await p.locator('#rClose').isEnabled() &&
          await p.evaluate(() => { const r = document.querySelector('#rClose').getBoundingClientRect();
            return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.id === 'rClose'; }));
    // no version.txt to fetch here, and a downloaded copy must never nag
    check('no stale-build prompt from a file:// copy',
          await p.evaluate(() => document.querySelector('#fresh').hidden));
    // the thing typing is for: streets are not on the 29-item shortlist
    await p.click('#rToI'); await p.waitForTimeout(200);
    await p.fill('#rToI', 'Via Giulia'); await p.waitForTimeout(250);
    await p.press('#rToI', 'Enter'); await p.waitForTimeout(600);
    check('a street can be a destination, which only typing can reach',
          await p.inputValue('#rToI') === 'Via Giulia' &&
          /km|m/.test(await p.textContent('#rTitle')),
          `${await p.inputValue('#rToI')} - ${(await p.textContent('#rTitle')).trim()}`);
    // and an empty field offers the landmarks again rather than nothing
    await p.fill('#rToI', ''); await p.waitForTimeout(250);
    check('clearing a field brings the shortlist back', await p.evaluate(() =>
      document.querySelectorAll('#rResults .res').length >= 20));

    await p.click('#rClose'); await p.waitForTimeout(350);
    // 460 taps over the whole city is not a map; they wait for the zoom
    check('no fountains on the city-wide view', await p.evaluate(() =>
      !document.querySelector('#legend').classList.contains('naso')));
    await p.evaluate(() => { window.ombra.st.scale = 0.5; });
    await p.click('#btnZin'); await p.waitForTimeout(300);
    check('and fountains once you zoom in to a walk', await p.evaluate(() =>
      document.querySelector('#legend').classList.contains('naso')));
    await p.click('#btnZfit'); await p.waitForTimeout(300);

    check('closing the route hands the console back',
          await p.evaluate(() =>
            getComputedStyle(document.querySelector('#console')).display !== 'none' &&
            !document.querySelector('#rcard').classList.contains('open')));
  }
  check('no console or page errors', errs.length === 0, errs.slice(0, 2).join(' | '));
  await browser.close();
}

// The route panel is a floating card on a phone and a sidebar section on a
// desktop, moved between the two by placeRcard. Getting that wrong once left the
// close button anchored to the sidebar instead of the card.
async function desktopLayout(){
  const browser = await chromium.launch(EXE.chromium ? { executablePath: EXE.chromium } : {});
  const p = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.route('**fonts.googleapis.com**', r => r.abort());
  console.log('');
  console.log('Chromium, desktop width');
  await p.goto(url, { waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                          { timeout: 45000 });
  await p.click('#btnRoute'); await p.waitForTimeout(400);
  check('route panel sits in the sidebar, not over the map',
        await p.evaluate(() => document.querySelector('#rcard').parentNode.id) === 'console');
  check('its close button stays on the card',
        await p.evaluate(() => { const c = document.querySelector('#rcard').getBoundingClientRect();
          const x = document.querySelector('#rClose').getBoundingClientRect();
          return x.top >= c.top - 1 && x.right <= c.right + 1; }));
  check('the zoom controls stay reachable', await p.locator('#btnZin').isVisible());
  check('no console or page errors', errs.length === 0, errs.slice(0, 2).join(' | '));
  await browser.close();
}


// GitHub Pages serves the page with a ten-minute cache and gives no way to
// change that, so for a while after a deploy a phone can still be holding the
// old copy. The page cannot beat the cache, so it notices instead: it fetches
// version.txt with no-store and offers a reload when that disagrees with the
// stamp baked into it. The quiet cases matter most - the artifact and a file://
// copy have no version.txt at all, and must never nag.
// The files a deploy puts beside the page, served as Pages would serve them.
const TYPES = { '.js': 'text/javascript', '.webmanifest': 'application/manifest+json',
                '.png': 'image/png' };
function serveDist(req, res, override = {}) {
  const path = req.url.split('?')[0];
  const ext = Object.keys(TYPES).find(e => path.endsWith(e));
  if (!ext) return false;
  const file = resolve(root, 'dist' + path);
  if (!override[path] && !existsSync(file)) { res.writeHead(404); res.end(); return true; }
  res.writeHead(200, { 'Content-Type': TYPES[ext] });
  res.end(override[path] ?? readFileSync(file));
  return true;
}

// The installable app: what Pages serves, as an installed phone would see it.
// Chromium only - Playwright's WebKit does not run service workers.
async function installable(){
  console.log('');
  console.log('Chromium, as an installed app (manifest, service worker, offline)');
  const html0 = readFileSync(page_, 'utf8');
  const stamp = readFileSync(resolve(root, 'dist/version.txt'), 'utf8').trim();
  const NEXT = '2099-01-01 00:00 deadbee';
  // "deploying" a new build: the page and the worker both carry the new stamp
  let gen = 0;
  const pageFor  = () => gen ? html0.split(stamp).join(NEXT) : html0;
  const swFor    = () => gen ? readFileSync(resolve(root, 'dist/sw.js'), 'utf8').split(stamp).join(NEXT) : null;
  const srv = createServer((req, res) => {
    const path = req.url.split('?')[0];
    if (path === '/version.txt') { res.writeHead(200); return res.end(gen ? NEXT : stamp); }
    const sw = swFor();
    if (serveDist(req, res, sw ? { '/sw.js': sw } : {})) return;
    if (path === '/' || path === '/index.html') {
      res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end(pageFor());
    }
    res.writeHead(404); res.end();
  });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch(EXE.chromium ? { executablePath: EXE.chromium } : {});
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.route('**fonts.googleapis.com**', r => r.abort());
  const booted = () => p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                                         { timeout: 45000 }).then(() => true, () => false);

  // the manifest, and icons that are the sizes it claims
  const m = await (await fetch(base + 'manifest.webmanifest')).json();
  check('the manifest names the app and opens it standalone',
        m.name === 'Ombra Roma' && m.display === 'standalone' && m.start_url === './',
        `${m.short_name}, ${m.display}`);
  const sizes = [];
  for (const ic of m.icons) {
    const b = Buffer.from(await (await fetch(base + ic.src)).arrayBuffer());
    const w = b.readUInt32BE(16), h = b.readUInt32BE(20);   // PNG IHDR
    sizes.push(`${w}x${h}` === ic.sizes);
  }
  check('every icon is the size the manifest says',
        sizes.length >= 3 && sizes.every(Boolean) && m.icons.some(i => i.purpose === 'maskable'));

  await p.goto(base); await booted();
  const reg = await p.evaluate(() => navigator.serviceWorker.ready.then(r => !!r.active));
  check('the service worker installs on the first visit', reg);
  check('no update offered on a first visit',
        await p.evaluate(() => document.querySelector('#fresh').hidden));
  await p.reload(); await booted();
  check('and controls the page from the next one',
        await p.evaluate(() => !!navigator.serviceWorker.controller));

  // a phone in a Roman courtyard with no signal
  await ctx.setOffline(true);
  await p.reload();
  check('it boots with no network at all', await booted());
  await ctx.setOffline(false);

  // a deploy lands: the page should offer it, and taking it should load it
  gen = 1;
  await p.reload(); await booted();
  const offered = await p.waitForFunction(() => !document.querySelector('#fresh').hidden,
                                          { timeout: 15000 }).then(() => true, () => false);
  check('a new deploy is offered once it is ready', offered);
  if (offered) {
    await Promise.all([p.waitForEvent('load', { timeout: 20000 }).catch(() => null), p.click('#fresh')]);
    await booted();
    const now = await p.evaluate(() => window.ombra.BUILD);
    check('and taking it loads the new build', now === NEXT, now);
  }
  check('no page errors', errs.length === 0, errs.join(' | '));
  await browser.close();
  srv.close();
}

// Where you are, and now. Chromium, a phone, a faked GPS fix.
async function hereAndNow(){
  console.log('');
  console.log('Chromium, here and now (location dot, follow, live clock)');
  const browser = await chromium.launch(EXE.chromium ? { executablePath: EXE.chromium } : {});
  const booted = p => p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                                        { timeout: 45000 });
  // where the Pantheon is, in degrees, from the page's own place list
  let ctx = await browser.newContext({ ...devices['iPhone 13'] });
  let p = await ctx.newPage();
  await p.goto(url); await booted(p);
  const pan = await p.evaluate(() => {
    const o = window.ombra, H = o.head, e = o.searchDest('Pantheon')[0], [x, y] = o.entryXY(e);
    return { lat: H.proj.lat0 + y / H.proj.mperlat, lon: H.proj.lon0 + x / H.proj.mperlon, x, y };
  });
  check('nothing asks for location at launch when it was never allowed', await p.evaluate(() =>
    window.ombra.me.watch === null));
  await ctx.close();

  // already granted: the app opens on you, following
  ctx = await browser.newContext({ ...devices['iPhone 13'], permissions: ['geolocation'],
                                   geolocation: { latitude: pan.lat, longitude: pan.lon, accuracy: 25 } });
  p = await ctx.newPage();
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(url); await booted(p);
  await p.waitForFunction(() => window.ombra.me.t > 0, { timeout: 10000 }).catch(() => {});
  const on = await p.evaluate(() => { const o = window.ombra, me = o.me, st = o.st;
    return { follow: me.follow, inside: me.inside, d: Math.hypot(st.cx - me.x, st.cy - me.y),
             pressed: document.querySelector('#btnLoc').getAttribute('aria-pressed'),
             shown: !document.querySelector('#btnLoc').hidden }; });
  check('with location already allowed, it opens on you and follows',
        on.shown && on.inside && on.follow && on.d < 1 && on.pressed === 'true', JSON.stringify(on));
  // dragging means looking elsewhere
  const sb = await p.locator('#stage').boundingBox();
  await p.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2); await p.mouse.down();
  await p.mouse.move(sb.x + sb.width / 2 + 120, sb.y + sb.height / 2 + 60, { steps: 4 }); await p.mouse.up();
  check('dragging the map stops it following', await p.evaluate(() =>
    !window.ombra.me.follow && document.querySelector('#btnLoc').getAttribute('aria-pressed') === 'false'));
  await p.click('#btnLoc'); await p.waitForTimeout(200);
  check('the button brings it back', await p.evaluate(() => { const o = window.ombra;
    return o.me.follow && Math.hypot(o.st.cx - o.me.x, o.st.cy - o.me.y) < 1; }));
  await p.click('#btnLoc'); await p.waitForTimeout(100);
  check('and pressed while following, switches location off',
        await p.evaluate(() => window.ombra.me.watch === null));
  // the route picker takes the fix it already has
  await p.click('#btnLoc'); await p.waitForTimeout(400);
  await p.click('#btnRoute'); await p.waitForTimeout(300);
  await p.click('#pickGeo'); await p.waitForTimeout(300);
  check('"Use my location" takes the fix the dot already has',
        /^My location/.test(await p.inputValue('#rFromI')), await p.inputValue('#rFromI'));
  await p.click('#rClose'); await p.waitForTimeout(200);

  // now: live until the clock is moved, and back on request
  const live0 = await p.evaluate(() => window.ombra.st.live && document.querySelector('#btnNow').hidden);
  check('the clock starts live', live0);
  await p.evaluate(() => { const el = document.querySelector('#time');
    el.value = (+el.value + 6) % 32; el.dispatchEvent(new Event('input', { bubbles: true })); });
  const moved = await p.evaluate(() => !window.ombra.st.live && !document.querySelector('#btnNow').hidden);
  check('moving it by hand leaves it there, and offers the way back', moved);
  await p.click('#btnNow'); await p.waitForTimeout(100);
  const back = await p.evaluate(() => {
    const st = window.ombra.st, n = new Date();
    const ti = Math.max(0, Math.min(31, Math.round((n.getHours() + n.getMinutes() / 60 - 6) * 2)));
    return { live: st.live, ti: st.ti, want: ti, hidden: document.querySelector('#btnNow').hidden };
  });
  check('"Back to now" returns to the present', back.live && back.hidden && Math.abs(back.ti - back.want) <= 1,
        `slot ${back.ti} vs ${back.want}`);
  check('no page errors', errs.length === 0, errs.join(' | '));
  await ctx.close();

  // granted, but far away: it says nothing at launch, and explains when asked
  ctx = await browser.newContext({ ...devices['iPhone 13'], permissions: ['geolocation'],
                                   geolocation: { latitude: 48.8566, longitude: 2.3522 } });   // Paris
  p = await ctx.newPage();
  await p.goto(url); await booted(p); await p.waitForTimeout(1500);
  check('far from Rome, it opens quietly on the map', await p.evaluate(() =>
    document.querySelector('#toast').hidden && window.ombra.me.watch === null));
  await p.click('#btnLoc');
  const note = await p.waitForFunction(() => !document.querySelector('#toast').hidden, { timeout: 8000 })
                      .then(() => p.textContent('#toast'), () => '');
  check('and when asked, says how far off the map you are', /from the edge of this map/.test(note),
        note.slice(0, 50));
  await browser.close();
}

async function freshness(){
  console.log('');
  console.log('Chromium, served over HTTP (how Pages serves it)');
  const stampFile = resolve(root, 'dist/version.txt');
  if (!existsSync(stampFile)) {
    check('version.txt written beside the build', false, 'missing');
    return;
  }
  const stamp = readFileSync(stampFile, 'utf8').trim();
  const html  = readFileSync(page_);
  let version = null;                    // what version.txt answers with, per case
  const srv = createServer((req, res) => {
    if (req.url.split('?')[0] === '/version.txt') {
      if (version === null) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      return res.end(version);
    }
    if (serveDist(req, res)) return;
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(html);
  });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const port = srv.address().port;
  const browser = await chromium.launch(EXE.chromium ? { executablePath: EXE.chromium } : {});
  const load = async (v) => {
    version = v;
    const ctx = await browser.newContext({ ...devices['iPhone 13'] });
    const p = await ctx.newPage();
    await p.route('**fonts.googleapis.com**', r => r.abort());
    await p.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                            { timeout: 45000 });
    // the check is a fetch, and once a service worker controls the page it is a
    // worker update as well: wait for the pill, and treat 3 s of nothing as none
    await p.waitForFunction(() => !document.querySelector('#fresh').hidden, { timeout: 3000 })
           .catch(() => {});
    const out = await p.evaluate(() => ({ build: window.ombra.BUILD,
                                          up: !document.querySelector('#fresh').hidden }));
    await ctx.close();
    return out;
  };
  const same = await load(stamp);
  check('the page carries the stamp the build wrote', same.build === stamp, same.build);
  check('no prompt while version.txt agrees', same.up === false);
  const newer = await load('2099-01-01 00:00 deadbee');
  check('prompt once version.txt has moved on', newer.up === true);
  const none = await load(null);
  check('no prompt where there is no version.txt', none.up === false);
  await browser.close();
  srv.close();
}

await run(chromium, 'Chromium', false, 'chromium');
await run(webkit, 'WebKit', false, 'webkit');
await run(webkit, 'WebKit with the Streams API broken (iOS Quick Look)', true, 'webkit');
await desktopLayout();
await hereAndNow();
await freshness();
await installable();
console.log(`\n${failures ? failures + ' CHECKS FAILED' : 'all checks passed'}`);
process.exit(failures ? 1 : 0);
