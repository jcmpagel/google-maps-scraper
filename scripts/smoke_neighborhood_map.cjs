// Exercise the portable file:// package, including its deliberate offline fallback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(path.join(process.env.PLAYWRIGHT_DRIVER_PATH, 'package'));

(async () => {
  const directory = path.resolve(process.argv[2] || 'web/neighborhood-map');
  const indexFile = directory.endsWith('.html') ? directory : path.join(directory, 'index.html');
  const destination = process.argv[3] && path.resolve(process.argv[3]);
  if (destination) fs.mkdirSync(destination, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('https://tile.openstreetmap.org/**', route => route.abort());
    await page.goto(pathToFileURL(indexFile).href);
    await page.waitForFunction(() => window.mapReady);
    // A live collector can publish a new generation between file reads.
    // Validate the exact self-contained data.js generation loaded by this page.
    const dataset = await page.evaluate(() => window.RESTAURANT_DATA);
    const expected = dataset.rows.filter(row => row.detail_checked && row.review_count >= 25).length;
    assert.ok(expected > 0, 'Use a real, populated snapshot');
    if (directory.endsWith('.html')) {
      for (const name of ['data.json', 'basemap.geojson', 'restaurants.kml']) {
        const waiting = page.waitForEvent('download');
        await page.locator(`a[data-embedded="${name}"]`).first().click();
        const download = await waiting;
        assert.equal(download.suggestedFilename(), name);
        const contents = fs.readFileSync(await download.path(), 'utf8');
        if (name === 'data.json') assert.deepEqual(JSON.parse(contents).rows.map(row => row.id), dataset.rows.map(row => row.id));
        if (name === 'basemap.geojson') assert.equal(JSON.parse(contents).features.length, await page.evaluate(() => window.OFFLINE_BASEMAP.features.length));
        if (name === 'restaurants.kml') assert.equal((contents.match(/<Placemark>/g) || []).length, expected);
      }
    }
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
    if (destination) {
      await page.screenshot({ path: path.join(destination, 'desktop.png'), fullPage: true });
      await page.locator('#mapSection').screenshot({ path: path.join(destination, 'map.png') });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.getElementById('filters').parentElement.id === 'filterDialog');
    await page.evaluate(() => scrollTo(0, 0));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No mobile page overflow');
    assert.equal(await page.locator('#map').evaluate(el => el.getBoundingClientRect().top < innerHeight), true, 'The map is visible on the first mobile screen');
    await page.locator('#showFilters').click();
    assert.equal(await page.locator('#filterDialog').evaluate(el => el.open), true);
    if (destination) await page.screenshot({ path: path.join(destination, 'mobile-filter.png') });
    await page.locator('#search').fill('no-such-restaurant-test-93817');
    await page.locator('#applyFilters').click();
    assert.equal(await page.locator('#cards button').count(), 0);
    await page.locator('#showFilters').click();
    await page.locator('#reset').click();
    await page.keyboard.press('Escape');
    await page.locator('#showPlaces').click();
    await page.locator('#cards button').first().click();
    assert.equal(await page.locator('#detailDialog').evaluate(el => el.open), true);
    assert.match(await page.locator('#detail').innerText(), /Base-Score/);
    if (destination) await page.screenshot({ path: path.join(destination, 'mobile-detail.png') });
    await page.locator('#detailDialog [data-close]').click();
    await page.locator('#showMap').click();
    await page.locator('#fit').click();
    const diagnostics = await page.evaluate(() => window.mapDiagnostics());
    assert.equal(diagnostics.visibleMarkers, expected);
    if (process.argv.includes('--require-streets')) {
      assert.ok(diagnostics.offlineFeatures > 100, 'The package includes real street geometry');
      assert.equal(diagnostics.offlineVisible, true);
      assert.ok(await page.locator('.street-label').count() > 3, 'Street names are actually rendered');
    }
    if (destination) await page.screenshot({ path: path.join(destination, 'mobile.png') });
    await page.setViewportSize({ width: 320, height: 740 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No overflow on a small phone');
    await page.setViewportSize({ width: 820, height: 1180 });
    await page.waitForFunction(() => document.getElementById('filters').parentElement.classList.contains('side-panel'));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No tablet overflow');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, portableFile: true, rows: expected, errors, mobileOverflow: false, basemap: 'deliberately offline' }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
