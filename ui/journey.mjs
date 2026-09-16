import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

// Full logged-in demo journey. Headed: the human completes PingOne's hosted
// login once; tokens are dumped to /tmp/a2a-tokens.json so later headless
// runs can seed sessionStorage and skip login entirely (until they expire).
const browser = await chromium.launch({ headless: false, slowMo: 250 });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message.slice(0, 200)));

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.locator('button:has-text("Sign in")').first().click();
console.log('→ complete the PingOne sign-on in the browser window…');

// signed-in state = .logout-button appears (the ⎋ in the identity panel)
await page
  .waitForSelector('.logout-button', { timeout: 300_000 })
  .catch(() => console.log('login did not complete in 5 min'));
const signedIn = (await page.locator('.logout-button').count()) > 0;
console.log('signed in:', signedIn);
if (!signedIn) process.exit(1);

// dump tokens for future headless seeding
const tokens = await page.evaluate(() => sessionStorage.getItem('a2a_demo.tokens'));
writeFileSync('/tmp/a2a-tokens.json', tokens ?? '');
console.log('tokens dumped:', (tokens ?? '').length, 'bytes');

// switch to the Travel Planner tab and send one search+book request
await page.locator('button:has-text("Travel Planner")').first().click();
await page.waitForTimeout(1500);
await page.screenshot({ path: '/tmp/j-planner-tab.png' });
const composer = page.locator('textarea, input[placeholder*="message" i]').last();
await composer.fill('Find flights SFO to JFK on 2026-09-20 for 2 passengers and hotels in NYC 2026-09-20 to 2026-09-22, then book the cheapest flight and the cheapest hotel.');
await page.keyboard.press('Enter');
console.log('→ search+book request sent; waiting for the delegation chain…');

await page.waitForTimeout(60_000);
await page.screenshot({ path: '/tmp/b-mid.png' });
await page.waitForTimeout(60_000);
await page.screenshot({ path: '/tmp/b-final.png' });

console.log('console errors:', errors.length ? errors : 'none');
await browser.close();
console.log('done');
