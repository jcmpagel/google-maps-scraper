const fs = require('node:fs');
const path = require('node:path');
const { rejectCookies } = require('./maps_consent.cjs');
const { chromium } = require(path.join(process.env.PLAYWRIGHT_DRIVER_PATH, 'package'));
(async () => {
  const [query, target] = process.argv.slice(2);
  if (!query || !target) throw new Error('Usage: node scripts/resolve_map_location.cjs QUERY OUTPUT');
  const browser = await chromium.launch({ headless: true });
  const failures = [];
  try {
    const page = await browser.newPage({ proxy: { server: process.env.HTTPS_PROXY }, viewport: { width: 1920, height: 1080 } });
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (['image', 'media', 'font'].includes(route.request().resourceType()) || url.hostname === 'ogads-pa.clients6.google.com' || (url.hostname === 'apis.google.com' && url.pathname === '/js/client.js') || (url.hostname === 'play.google.com' && url.pathname === '/log')) return route.abort();
      try {
        const response = await route.fetch({ timeout: 30000 });
        if ([403, 429].includes(response.status())) failures.push({ status: response.status(), url: url.origin + url.pathname });
        await route.fulfill({ response });
      } catch (error) { failures.push({ error: error.message }); await route.abort(); }
    });
    await page.goto('https://www.google.com/maps/search/' + encodeURIComponent(query) + '?hl=de&gl=de', { waitUntil: 'domcontentloaded', timeout: 45000 });
    await rejectCookies(page, page.waitForFunction(() => !!window.APP_INITIALIZATION_STATE, { timeout: 25000 }));
    await page.waitForFunction(() => !!window.APP_INITIALIZATION_STATE, { timeout: 20000 });
    await page.waitForTimeout(3000);
    const raw = await page.evaluate(() => {
      const state = window.APP_INITIALIZATION_STATE?.[3];
      for (const value of Object.values(state || {})) if (Array.isArray(value)) for (const index of [6, 5]) if (typeof value[index] === 'string' && value[index].startsWith(")]}'")) return value[index];
      return null;
    });
    const parsed = raw ? JSON.parse(raw.replace(/^\)\]\}'\s*/, '')) : null;
    const camera = await page.evaluate(() => window.APP_INITIALIZATION_STATE?.[0]);
    const result = { query, url: page.url(), heading: await page.locator('h1').first().innerText().catch(() => ''), coordinates: parsed?.[6]?.[9], camera, failures, captured_at: new Date().toISOString() };
    if (failures.length) throw new Error(JSON.stringify(result));
    fs.writeFileSync(target, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
