// Exercise the portable file:// package, including its deliberate offline fallback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(path.join(process.env.PLAYWRIGHT_DRIVER_PATH, 'package'));

(async () => {
  const directory = path.resolve(process.argv[2] || 'web/neighborhood-map');
  const destination = process.argv[3] && path.resolve(process.argv[3]);
  if (destination) fs.mkdirSync(destination, { recursive: true });
  const dataset = JSON.parse(fs.readFileSync(path.join(directory, 'data.json')));
  const expected = dataset.rows.filter(row => row.detail_checked && row.review_count >= 25).length;
  assert.ok(expected > 0, 'Use a real, populated snapshot');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('https://tile.openstreetmap.org/**', route => route.abort());
    await page.goto(pathToFileURL(path.join(directory, 'index.html')).href);
    await page.waitForFunction(() => window.mapReady);
    assert.equal(await page.locator('#rows tr').count(), expected);
    await page.locator('#rows button').first().click();
    assert.ok((await page.locator('#detail h2').innerText()).length > 0);
    const link = await page.locator('#detail a').first().getAttribute('href');
    assert.match(link, /^https:\/\/(www\.)?google\.com\/maps/);
    await page.locator('#search').fill('no-such-restaurant-test-93817');
    assert.equal(await page.locator('#rows tr').count(), 0);
    assert.equal(await page.locator('#empty').isVisible(), true);
    await page.locator('#reset').click();
    assert.equal(await page.locator('#rows tr').count(), expected);
    await page.locator('#minimum').selectOption('100');
    assert.equal(await page.locator('#rows tr').count(), dataset.rows.filter(row => row.detail_checked && row.review_count >= 100).length);
    await page.locator('#reset').click();
    await page.locator('#colour').selectOption('notices');
    await page.locator('#notices').check();
    assert.equal(await page.locator('#rows tr').count(), dataset.rows.filter(row => row.detail_checked && row.review_count >= 25 && row.removal_status === 'parsed' && !row.notice_conflict).length);
    await page.locator('#fit').click();
    await page.locator('#reset').click();
    await page.waitForFunction(() => !document.getElementById('mapFallback').hidden);
    if (destination) await page.screenshot({ path: path.join(destination, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No mobile page overflow');
    if (destination) await page.screenshot({ path: path.join(destination, 'mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, portableFile: true, rows: expected, errors, mobileOverflow: false, basemap: 'deliberately offline' }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
