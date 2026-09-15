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
    await p.click('#btnRoute'); await p.waitForTimeout(300);
    await p.fill('#rSearch', 'Pantheon'); await p.waitForTimeout(200); await p.click('.res');
    await p.waitForTimeout(300);
    await p.click('#rTo'); await p.fill('#rSearch', 'Colosseo'); await p.waitForTimeout(200);
    await p.click('.res'); await p.waitForTimeout(600);
    const km = await p.textContent('#rTitle');
    check('routes Pantheon to Colosseo', /km/.test(km), km);
    check('shows the shortest-route comparison',
          /Shortest way/.test(await p.textContent('#rCompare')));
    check('close button is clickable (z-order)',
          await p.locator('#rClose').isEnabled() &&
          await p.evaluate(() => { const r = document.querySelector('#rClose').getBoundingClientRect();
            return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.id === 'rClose'; }));
  }
  check('no console or page errors', errs.length === 0, errs.slice(0, 2).join(' | '));
  await browser.close();
}

await run(chromium, 'Chromium', false, 'chromium');
await run(webkit, 'WebKit', false, 'webkit');
await run(webkit, 'WebKit with the Streams API broken (iOS Quick Look)', true, 'webkit');
console.log(`\n${failures ? failures + ' CHECKS FAILED' : 'all checks passed'}`);
process.exit(failures ? 1 : 0);
