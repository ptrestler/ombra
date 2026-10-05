// Where the page's boot time goes, stage by stage, at desktop speed and with
// the CPU slowed 4x - about a phone, judged by the inflate stage, which
// CLAUDE.md has measured on one. Needs a build: `make`, then
//   node measure_boot.mjs
//
// Every stage but the first draw scales with the payload, so this is also the
// cost model for a bigger map: see "Wider coverage" in CLAUDE.md. Chromium only;
// the CPU throttle is a Chromium DevTools feature.
import { chromium, devices } from 'playwright';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { existsSync, statSync } from 'node:fs';

const page_ = resolve(dirname(fileURLToPath(import.meta.url)), 'dist/ombra-roma.html');
if (!existsSync(page_)) { console.error('build it first: make'); process.exit(1); }
const exe = process.env.PLAYWRIGHT_CHROMIUM_PATH;
const b = await chromium.launch(exe ? { executablePath: exe } : {});
console.log(`dist/ombra-roma.html  ${(statSync(page_).size / 1e6).toFixed(2)} MB`);
for (const rate of [1, 4]) {
  const runs = [];
  for (let i = 0; i < 3; i++) {
    const ctx = await b.newContext({ ...devices['iPhone 13'] });
    const p = await ctx.newPage();
    await (await ctx.newCDPSession(p)).send('Emulation.setCPUThrottlingRate', { rate });
    await p.goto(pathToFileURL(page_).href, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none',
                            { timeout: 120000, polling: 50 });
    runs.push(await p.evaluate(() => ({ ...window.ombra.BOOT })));
    await ctx.close();
  }
  // the median run, by total, so one slow start does not set the numbers
  const tot = r => Object.values(r).reduce((a, v) => a + v, 0);
  runs.sort((a, c) => tot(a) - tot(c));
  const r = runs[1];
  console.log(`cpu x${rate}  total ${tot(r)} ms  ` +
              Object.entries(r).map(([k, v]) => `${k} ${v}`).join(' · '));
}
await b.close();
