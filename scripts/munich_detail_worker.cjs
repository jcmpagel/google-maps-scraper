const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { randomUUID } = require('node:crypto');

function entryIdentity(entry) {
  const fid = /^0x[0-9a-f]+:0x([0-9a-f]+)$/i.exec(entry.data_id || '');
  if (fid) return `cid:${BigInt('0x' + fid[1]).toString()}`;
  if (/^\d+$/.test(entry.cid || '')) return `cid:${BigInt(entry.cid).toString()}`;
  return entry.place_id ? `place:${entry.place_id}` : null;
}

function needsEnglish(entry, policy) {
  return !entry.review_count_available || !entry.reviews_per_rating_available || entry.removed_reviews_status === 'unrecognized' ||
    (policy === 'notice-or-metrics' && entry.removed_reviews_status !== 'parsed');
}

async function pace(pacingFile, now = Date.now, wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))) {
  const previous = fs.existsSync(pacingFile) ? JSON.parse(fs.readFileSync(pacingFile)).lastVisit : 0;
  if (!Number.isFinite(previous)) throw new Error('Invalid persisted pacing state');
  const remaining = Math.max(0, previous + 15000 - now());
  if (remaining) await wait(remaining);
  fs.writeFileSync(pacingFile + '.tmp', JSON.stringify({ lastVisit: now() }));
  fs.renameSync(pacingFile + '.tmp', pacingFile);
}

function mergeObservations(observations, expected) {
  if (!observations.length || observations.some(o => entryIdentity(o.entry) !== expected)) throw new Error('Detail identity does not match reserved place');
  const merged = { ...observations[0].entry };
  const notices = observations.filter(o => o.entry.removed_reviews_status === 'parsed');
  const conflict = new Set(notices.map(o => `${o.entry.removed_reviews_min}/${o.entry.removed_reviews_max}`)).size > 1;
  const recognized = notices[0];
  if (recognized) for (const key of ['removed_reviews_min', 'removed_reviews_max', 'removed_reviews_status', 'removed_reviews_notice']) merged[key] = recognized.entry[key];
  if (conflict) { merged.removed_reviews_min = 0; merged.removed_reviews_max = 0; merged.removed_reviews_status = 'unrecognized'; }
  for (const [available, values] of [['review_count_available', ['review_count', 'review_rating']], ['reviews_per_rating_available', ['reviews_per_rating']]]) {
    const source = observations.find(o => o.entry[available]);
    if (source) { merged[available] = true; for (const key of values) merged[key] = source.entry[key]; }
  }
  return { ...merged, detail_removal_conflict: conflict, detail_observations: observations };
}

async function main() {
  const [database, output, parser, ...args] = process.argv.slice(2);
  if (!database || !output || !parser) throw new Error('Usage: node scripts/munich_detail_worker.cjs DATABASE OUTPUT PARSER [--limit N] [--bbox minLat,minLon,maxLat,maxLon]');
  const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
  const limit = Number(option('--limit', '5'));
  if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw new Error('Pilot limit must be 1–20');
  const bbox = option('--bbox', '48.13,11.56,48.145,11.59');
  const fallback = option('--fallback', 'missing-data');
  if (!['missing-data', 'notice-or-metrics'].includes(fallback)) throw new Error('Unknown fallback policy');
  const helper = path.join(__dirname, 'discovery_store.py');
  const store = (...parameters) => JSON.parse(execFileSync('python3', [helper, database, ...parameters], { encoding: 'utf8' }));
  fs.mkdirSync(output, { recursive: true });
  // Exclusive worker lock: all detail workers sharing this DB use one pacing lane.
  const lock = database + '.detail-worker.lock';
  const descriptor = fs.openSync(lock, 'wx');
  fs.writeSync(descriptor, JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString() }));
  let browser;
  const report = { run_id: randomUUID(), startedAt: new Date().toISOString(), limit, bbox, fallback, completed: [], failures: [], localeRequests: 0 };
  const latest = path.join(output, 'run.json');
  const save = () => {
    const contents = JSON.stringify(report, null, 2);
    fs.writeFileSync(path.join(output, `run-${report.run_id}.json.tmp`), contents);
    fs.renameSync(path.join(output, `run-${report.run_id}.json.tmp`), path.join(output, `run-${report.run_id}.json`));
    fs.writeFileSync(latest + '.tmp', contents); fs.renameSync(latest + '.tmp', latest);
  };
  const pacingFile = database + '.detail-pacing.json';
  try {
    if (fs.existsSync(latest)) fs.copyFileSync(latest, path.join(output, `previous-${report.run_id}.json`));
    const { chromium } = require(path.join(process.env.PLAYWRIGHT_DRIVER_PATH, 'package'));
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ proxy: { server: process.env.HTTPS_PROXY }, userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', viewport: { width: 1920, height: 1080 } });
    for (let i = 0; i < limit; i++) {
      const job = store('claim', '--bbox', bbox);
      if (!job) break;
      const observations = [];
      try {
        for (const language of ['de', 'en']) {
          if (language === 'en' && !needsEnglish(observations[0].entry, fallback)) break;
          await pace(pacingFile);
          const page = await context.newPage();
          const errors = [];
          let blocked = false;
          try {
            await page.route('**/*', async route => {
              if (['image', 'media', 'font'].includes(route.request().resourceType())) return route.abort();
              const url = new URL(route.request().url());
              if (url.hostname === 'ogads-pa.clients6.google.com' || (url.hostname === 'play.google.com' && url.pathname === '/log')) return route.abort();
              try {
                const response = await route.fetch({ timeout: 30000 });
                if ([403, 429].includes(response.status())) blocked = true;
                await route.fulfill({ response });
              } catch (error) { errors.push(error.message.slice(0, 250)); await route.abort(); }
            });
            const url = new URL(job.link); url.searchParams.set('hl', language); url.searchParams.set('gl', 'de');
            report.localeRequests++; save();
            await page.goto(url.toString(), { waitUntil: 'domcontentloaded', timeout: 45000 });
            const reject = page.getByRole('button', { name: /Reject all|Alle ablehnen/i });
            if (await reject.count()) await reject.first().click();
            await page.waitForFunction(() => !!window.APP_INITIALIZATION_STATE, { timeout: 15000 });
            await page.waitForTimeout(3000);
            const body = await page.locator('body').innerText();
            if (blocked || /unusual traffic|ungewöhnlichen Datenverkehr|captcha/i.test(body)) throw new Error('Access block or challenge; stopping');
            const raw = await page.evaluate(() => {
              const state = window.APP_INITIALIZATION_STATE?.[3];
              if (!state) return null;
              for (const value of Object.values(state)) if (Array.isArray(value)) for (const index of [6, 5]) if (typeof value[index] === 'string' && value[index].startsWith(")]}'")) return value[index];
              return null;
            });
            if (!raw || errors.length) throw new Error('Missing payload or incomplete transport: ' + errors.join('; '));
            const payload = JSON.parse(raw.replace(/^\)\]\}'\s*/, ''));
            const prefix = `${job.place_id.replace(/[^a-zA-Z0-9_-]/g, '_')}-${job.token}-${language}`;
            const rawFile = path.join(output, prefix + '-raw.json');
            fs.writeFileSync(rawFile, JSON.stringify(payload));
            const entry = JSON.parse(execFileSync(parser, [], { input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }));
            if (entryIdentity(entry) !== job.place_id) throw new Error('Captured a different place than the leased job');
            observations.push({ language, fetched_at: new Date().toISOString(), raw_file: rawFile, entry });
          } finally { await page.close(); }
        }
        const result = mergeObservations(observations, job.place_id);
        const filename = path.join(output, `${job.token}-result.json`);
        fs.writeFileSync(filename, JSON.stringify(result, null, 2));
        store('finish', job.token, filename);
        report.completed.push({ place_id: job.place_id, title: result.title, languages: observations.map(o => o.language), status: result.removed_reviews_status, min: result.removed_reviews_min, max: result.removed_reviews_max, countAvailable: result.review_count_available, histogramAvailable: result.reviews_per_rating_available, conflict: result.detail_removal_conflict });
        console.log(JSON.stringify(report.completed.at(-1)));
        save();
      } catch (error) {
        let leaseError;
        try { store('fail', job.token, error.message); } catch (failure) { leaseError = failure.message; }
        report.failures.push({ place_id: job.place_id, error: error.message, leaseError }); save();
        throw error; // Conservative stop; the durable queue retains retry state.
      }
    }
  } finally {
    try { if (browser) await browser.close(); }
    finally {
      try { report.finishedAt = new Date().toISOString(); save(); }
      finally { fs.closeSync(descriptor); fs.unlinkSync(lock); }
    }
  }
}

module.exports = { entryIdentity, mergeObservations, needsEnglish, pace };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
