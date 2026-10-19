const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(path.join(process.env.PLAYWRIGHT_DRIVER_PATH, 'package'));
const { rejectCookies } = require('./maps_consent.cjs');
const { detailPayload } = require('./munich_detail_worker.cjs');

test('an early initialization object does not bypass late consent and place data', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<html><body><script>window.APP_INITIALIZATION_STATE = [];</script></body></html>');
    await page.evaluate(() => {
      setTimeout(() => {
        const button = document.createElement('button');
        button.textContent = 'Alle ablehnen';
        button.onclick = () => {
          window.rejectedConsent = true;
          button.remove();
          setTimeout(() => {
            window.APP_INITIALIZATION_STATE[3] = { detail: [null, null, null, null, null, null, ")]}'\n[]"] };
          }, 50);
        };
        document.body.append(button);
      }, 75);
    });
    await rejectCookies(page, page.waitForFunction(detailPayload, null, { timeout: 2000 }));
    await page.waitForFunction(detailPayload, null, { timeout: 2000 });
    assert.equal(await page.evaluate(() => window.rejectedConsent), true);
    assert.equal(await page.evaluate(detailPayload), ")]}'\n[]");
  } finally {
    await browser.close();
  }
});
