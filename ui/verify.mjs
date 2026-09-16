import { chromium } from 'playwright';
import { readFileSync } from 'fs';

// Headless verification run: seeds sessionStorage from the token dumped by
// the last headed login (journey.mjs) — no interactive login needed, as
// long as that token hasn't expired yet.
const tokens = JSON.parse(readFileSync('/tmp/a2a-tokens.json', 'utf8'));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message.slice(0, 200)));

await ctx.addInitScript((t) => sessionStorage.setItem('a2a_demo.tokens', t), JSON.stringify(tokens));
await page.goto('http://localhost:5173/', { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
await page.waitForTimeout(2500);
const signedIn = (await page.locator('.logout-button').count()) > 0;
console.log('seeded signed-in:', signedIn);
if (!signedIn) process.exit(1);

await page.locator('button:has-text("Travel Planner")').first().click();
await page.waitForTimeout(1500);
await page.locator('textarea, input[placeholder*="message" i]').last()
  .fill('Find flights SFO to JFK on 2026-09-20 for 2 passengers and hotels in NYC 2026-09-20 to 2026-09-22, then book the cheapest flight and the cheapest hotel.');
await page.keyboard.press('Enter');
console.log('→ search+book request sent…');

await page.waitForTimeout(60_000);
await page.screenshot({ path: '/tmp/v-mid.png' });
await page.waitForTimeout(60_000);
await page.screenshot({ path: '/tmp/v-final.png' });
console.log('console errors:', errors.length ? errors : 'none');
await browser.close();
console.log('done');
