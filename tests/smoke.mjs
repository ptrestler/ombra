// Browser checks for the built page. Runs in Chromium and WebKit, and in WebKit
// with the Streams API broken, because that is what iOS Quick Look does.
import { chromium, webkit, devices } from 'playwright';
import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';

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
    check('no horizontal scroll at phone width',
          !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    // data round-trip: these must match tests/validate.py exactly
    const d = await p.evaluate(() => {
      const O = window.ombra, H = O.head, D = O.data, base = ((8 - 1) * 2 + 1) * 32;
      const at = (name, h) => {
        const ni = H.names.indexOf(name); if (ni < 0) return null;
        let s = 0, n = 0;
        for (let i = 0; i < H.nseg; i++) if (D.name[i] === ni) { s += D.shade[i * H.nframe + base + (h - 6) * 2]; n++; }
        return n ? +(s / n).toFixed(1) : null;
      };
      return { fori: at('Via dei Fori Imperiali', 14), trilussa: at('Piazza Trilussa', 18) };
    });
    check('Fori Imperiali unshaded at 14:00', d.fori === 0, `${d.fori}%`);
    check('Piazza Trilussa shaded at 18:00', d.trilussa > 85, `${d.trilussa}%`);
    // street lookup and routing
    await p.fill('#search', 'Via Giulia'); await p.press('#search', 'Enter');
    await p.waitForTimeout(500);
    check('street search', (await p.textContent('#cName')) === 'Via Giulia');
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
    await p.click('#btnRoute'); await p.waitForTimeout(300);
    // the card opens with the A picker already showing; tapping the end it is
    // asking about must not close the search out from under you
    await p.click('#rFrom'); await p.waitForTimeout(200);
    check('empty picker stays open when tapped',
          await p.evaluate(() => document.querySelector('#rcard').classList.contains('picking')));
    await p.fill('#rSearch', 'Pantheon'); await p.waitForTimeout(200); await p.click('.res');
    await p.waitForTimeout(300);
    await p.click('#rTo'); await p.fill('#rSearch', 'Colosseo'); await p.waitForTimeout(200);
    await p.click('.res'); await p.waitForTimeout(600);
    const km = await p.textContent('#rTitle');
    check('routes Pantheon to Colosseo', /km/.test(km), km);
    check('shows the shortest-route comparison',
          /Shortest way/.test(await p.textContent('#rCompare')));
    // must alternate, not recompute from the system each time - when storage is
    // blocked that bug makes the toggle stick on one theme for ever
    const gnd = () => p.evaluate(() => getComputedStyle(document.documentElement)
                                        .getPropertyValue('--ground').trim());
    const t0 = await gnd();
    await p.click('#btnTheme'); await p.waitForTimeout(250); const t1 = await gnd();
    await p.click('#btnTheme'); await p.waitForTimeout(250); const t2 = await gnd();
    check('theme toggle alternates', t0 !== t1 && t1 !== t2 && t0 === t2, `${t0} ${t1} ${t2}`);
    // the phone route panel fills the upper map, so the zoom stack steps aside
    check('route panel does not bury the zoom controls',
          await p.evaluate(() => getComputedStyle(document.querySelector('#zoomctl')).display === 'none'));
    check('close button is clickable (z-order)',
          await p.locator('#rClose').isEnabled() &&
          await p.evaluate(() => { const r = document.querySelector('#rClose').getBoundingClientRect();
            return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.id === 'rClose'; }));
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

await run(chromium, 'Chromium', false, 'chromium');
await run(webkit, 'WebKit', false, 'webkit');
await run(webkit, 'WebKit with the Streams API broken (iOS Quick Look)', true, 'webkit');
await desktopLayout();
console.log(`\n${failures ? failures + ' CHECKS FAILED' : 'all checks passed'}`);
process.exit(failures ? 1 : 0);
