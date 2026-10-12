// Bounded discovery experiment. No place-detail pages or review requests.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(path.join(process.env.PLAYWRIGHT_DRIVER_PATH, 'package'));
const output = process.argv[2];
if (!output) throw new Error('Usage: node scripts/munich_discovery_pilot.cjs OUTPUT_DIRECTORY');
const deep = process.argv.includes('--deep');
const refine = process.argv.includes('--refine');
if (deep && refine) throw new Error('Choose either --deep or --refine');
const maxScrolls = deep || refine ? 20 : 4;
function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0) return null;
  if (!process.argv[index + 1] || process.argv[index + 1].startsWith('--')) throw new Error(`Missing value for ${name}`);
  return process.argv[index + 1];
}
const storePath = option('--store');
const boundaryPath = option('--boundary');
if (boundaryPath && !storePath) throw new Error('--boundary requires --store');
fs.mkdirSync(output, { recursive: true });
const sites = [
  { name: 'zentrum', lat: 48.1372, lon: 11.5756 },
  { name: 'sendling', lat: 48.1175, lon: 11.5390 },
  { name: 'aubing', lat: 48.1575, lon: 11.4140 },
];
const plan = sites.flatMap(site => ['Restaurant', 'Café'].map(keyword => ({ ...site, keyword, zoom: 15 })));
plan.push(...['Restaurant', 'Café'].map(keyword => ({ ...sites[0], keyword, zoom: 16 })));
plan.push({ name: 'zentrum-ost', lat: 48.1372, lon: 11.5823, keyword: 'Restaurant', zoom: 16 });
plan.push({ name: 'zentrum-nord', lat: 48.1417, lon: 11.5756, keyword: 'Restaurant', zoom: 16 });
if (deep) plan.splice(0, plan.length,
  { ...sites[0], keyword: 'Restaurant', zoom: 16 },
  { ...sites[2], keyword: 'Café', zoom: 16 });
if (refine) plan.splice(0, plan.length,
  ...[[-1, -1], [-1, 1], [1, -1], [1, 1]].map(([north, east]) => ({
    name: `zentrum-child-${north}-${east}`, lat: sites[0].lat + north * 0.00225,
    lon: sites[0].lon + east * 0.00336, keyword: 'Restaurant', zoom: 17,
  })),
  { ...sites[0], keyword: 'Döner', zoom: 16 },
  { ...sites[0], keyword: 'Imbiss', zoom: 16 });
const statePath = path.join(output, 'discovery.json');
const state = fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : { version: 1, maxScrolls, plan, searches: [] };
if (JSON.stringify(state.plan) !== JSON.stringify(plan)) throw new Error('Output directory belongs to a different plan');
if ((state.maxScrolls ?? 4) !== maxScrolls) throw new Error('Output directory belongs to a different scroll budget');
function save() {
  fs.writeFileSync(statePath + '.tmp', JSON.stringify(state, null, 2));
  fs.renameSync(statePath + '.tmp', statePath);
}
function syncStore() {
  if (!storePath) return;
  const helper = path.join(__dirname, 'discovery_store.py');
  execFileSync('python3', [helper, storePath, 'import', statePath], { stdio: 'pipe' });
  if (boundaryPath) execFileSync('python3', [helper, storePath, 'classify', boundaryPath], { stdio: 'pipe' });
}
function identity(link) {
  const url = new URL(link);
  const place = url.pathname.match(/!1s([^!/?]+)/);
  if (place) {
    const value = decodeURIComponent(place[1]);
    return 'maps-id:' + (/^0x[0-9a-f]+:0x[0-9a-f]+$/i.test(value) ? value.toLowerCase() : value);
  }
  if (url.searchParams.has('cid')) return 'cid:' + url.searchParams.get('cid');
  return 'url:' + url.origin + url.pathname;
}
function distanceKm(place, search) {
  const coordinates = place.link.match(/!3d([-\d.]+)!4d([-\d.]+)/);
  if (!coordinates) return null;
  const lat = Number(coordinates[1]), lon = Number(coordinates[2]);
  return 111.32 * Math.hypot(lat - search.lat, (lon - search.lon) * Math.cos(search.lat * Math.PI / 180));
}
async function summarize() {
  const seen = new Map();
  const results = state.searches.filter(s => s.status === 'completed').map(search => {
    let fresh = 0;
    for (const place of search.places) {
      if (!seen.has(place.id)) { seen.set(place.id, { ...place, foundIn: [] }); fresh++; }
      seen.get(place.id).foundIn.push(search.key);
    }
    const distances = search.places.map(p => distanceKm(p, search)).filter(d => d !== null).sort((a, b) => a - b);
    return { key: search.key, count: search.places.length, newInRunOrder: fresh, duplicateInRunOrder: search.places.length - fresh, exhaustedScrollBudget: search.exhaustedScrollBudget, endOfList: search.endOfList, seconds: search.seconds, coordinatesAvailable: distances.length, maxDistanceKm: distances.length ? distances.at(-1) : null, medianDistanceKm: distances.length ? distances[Math.floor(distances.length / 2)] : null };
  });
  const sets = state.searches.filter(s => s.status === 'completed');
  const comparisons = [];
  for (let i = 0; i < sets.length; i++) for (let j = i + 1; j < sets.length; j++) {
    const a = new Set(sets[i].places.map(p => p.id));
    const b = new Set(sets[j].places.map(p => p.id));
    const shared = [...a].filter(id => b.has(id)).length;
    comparisons.push({ a: sets[i].key, b: sets[j].key, shared, onlyA: a.size - shared, onlyB: b.size - shared });
  }
  const summary = { results, unique: seen.size, appearances: results.reduce((n, r) => n + r.count, 0), comparisons, detailRequests: 0 };
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2));
  fs.writeFileSync(path.join(output, 'places.json'), JSON.stringify([...seen.values()], null, 2));
  console.log(JSON.stringify(summary));
}
(async () => {
  save();
  syncStore();
  if (process.argv.includes('--summarize')) { await summarize(); return; }
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ proxy: { server: process.env.HTTPS_PROXY }, userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', viewport: { width: 1920, height: 1080 } });
    for (const task of plan) {
      const key = `${task.name}/${task.keyword}/${task.zoom}`;
      if (state.searches.some(s => s.key === key && s.status === 'completed')) continue;
      const record = { ...task, key, startedAt: new Date().toISOString(), status: 'running', transportErrors: [], deniedResponses: [], skippedOptionalRequests: 0, places: [] };
      state.searches.push(record);
      save();
      const page = await context.newPage();
      let blocked = false;
      await page.route('**/*', async route => {
        if (['image', 'media', 'font'].includes(route.request().resourceType())) return route.abort();
        const requestURL = new URL(route.request().url());
        if (requestURL.hostname === 'ogads-pa.clients6.google.com' ||
            (requestURL.hostname === 'play.google.com' && requestURL.pathname === '/log')) {
          record.skippedOptionalRequests++;
          return route.abort();
        }
        try {
          const response = await route.fetch({ timeout: 30000 });
          if ([403, 429].includes(response.status())) {
            record.deniedResponses.push({ url: route.request().url().split('?')[0], status: response.status() });
            blocked = true;
          }
          await route.fulfill({ response });
        } catch (error) {
          record.transportErrors.push(error.message.slice(0, 250));
          await route.abort();
        }
      });
      try {
        const url = `https://www.google.com/maps/search/${encodeURIComponent(task.keyword)}/@${task.lat},${task.lon},${task.zoom}z?hl=de&gl=de`;
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
        const reject = page.getByRole('button', { name: /Reject all|Alle ablehnen/i });
        if (await reject.count()) await reject.first().click();
        const feed = page.locator('div[role=feed]');
        await feed.waitFor({ timeout: 25000 });
        const collected = new Map();
        for (let scroll = 0; scroll <= maxScrolls; scroll++) {
          const body = await page.locator('body').innerText();
          if (blocked || /unusual traffic|ungewöhnlichen Datenverkehr|captcha/i.test(body)) throw new Error('Rate limit, access block or challenge: stopping pilot');
          const rows = await feed.locator('a[href*="/maps/place/"]').evaluateAll(nodes => nodes.map(n => ({ title: n.getAttribute('aria-label') || n.textContent, link: n.href })));
          for (const row of rows) { const id = identity(row.link); collected.set(id, { ...row, id }); }
          record.endOfList = /Ende der Liste|end of the list/i.test(await feed.innerText());
          if (record.endOfList) break;
          if (scroll === maxScrolls) { record.exhaustedScrollBudget = true; break; }
          await feed.evaluate(el => el.scrollTo(0, el.scrollHeight));
          await page.waitForTimeout(4000);
        }
        if (record.transportErrors.length) throw new Error('Incomplete transport: stopping pilot, result not counted as complete');
        record.places = [...collected.values()];
        record.finalURL = page.url();
        record.status = 'completed';
        record.seconds = (Date.now() - Date.parse(record.startedAt)) / 1000;
        console.log(JSON.stringify({ key, count: record.places.length, endOfList: record.endOfList }));
      } catch (error) {
        record.status = 'failed'; record.error = error.message;
        save(); throw error;
      } finally { await page.close(); }
      save();
      syncStore();
      if (plan.indexOf(task) < plan.length - 1) await new Promise(resolve => setTimeout(resolve, 15000));
    }
  } finally { await browser.close(); await summarize(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
