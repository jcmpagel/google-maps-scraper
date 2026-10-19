// Cookie controls can arrive after DOMContentLoaded under concurrent load.
async function rejectCookies(page, ready) {
  const reject = page.getByRole('button', { name: /Reject all|Alle ablehnen/i }).first();
  const result = await Promise.any([
    reject.waitFor({ state: 'visible', timeout: 25000 }).then(() => 'consent'),
    ready.then(() => 'ready'),
  ]);
  if (result === 'consent') await reject.click();
}
module.exports = { rejectCookies };
