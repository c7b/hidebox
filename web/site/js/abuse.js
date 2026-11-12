// SPDX-License-Identifier: MIT
// The report form (spec §6.3 Abuse). The link's key is removed in this browser unless the reporter
// ticks the box, and the anti-bot proof of work is the app's own (/app/lib/pow.js), not a captcha.
// The form ships hidden and appears only once this module runs: a form the browser submitted by
// itself would put the whole link, key included, in a request to us and in the history.
import { config } from './site.js';

const T = {
  working: 'A few seconds of math instead of a captcha…',
  sent: (id) => `Thanks. Report ${id} received. We read every report and usually disable the link first and ask questions later.`,
  notLink: 'Paste a link from this site: it has /s/, /p/, /d/ or /shop/ in it.',
  wait: (s) => `You can send another report in ${s} seconds.`,
  offline: 'We couldn\'t reach our server. Nothing was sent. Try again.',
  failed: 'Our server failed. Nothing was sent. Try again in a minute.',
};
const PATH = /^\/(s\/[A-Za-z0-9_-]{22}|p\/[A-Za-z0-9_-]{22}|d\/[0-9a-hjkmnp-tv-z]{10}|shop\/[A-Za-z0-9_-]{22})$/;
// A paid link (/p/<id>) is a link with a price: the same id opens as /s/<id> for a report.
function asPlain(link) {
  const url = new URL(link);
  return url.origin + url.pathname.replace(/^\/p\//, '/s/') + url.hash;
}

const form = document.querySelector('[data-abuse]');
const linkInput = form.elements.link;
const status = form.querySelector('[role="status"]');
const submit = form.querySelector('[type="submit"]');

function say(text, isError = false) {
  status.textContent = text;
  status.classList.toggle('error', isError);
}

// → the link to send, with its key removed unless the reporter chose to include it; null if invalid.
function cleanLink(raw, includeKey, origins) {
  let url;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  if (!PATH.test(url.pathname) || url.search || (origins && !origins.includes(url.origin))) return null;
  return url.origin + url.pathname + (includeKey && url.hash ? url.hash : '');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const origins = (await config)?.memo_origins ?? null;
  const link = cleanLink(linkInput.value, form.elements.include_key.checked, origins);
  linkInput.toggleAttribute('aria-invalid', !link);
  if (!link) {
    say(T.notLink, true);
    linkInput.focus();
    return;
  }
  submit.disabled = true;
  say(T.working);
  try {
    const [{ solvePow }, { reportAbuse }] = await Promise.all([import('/app/lib/pow.js'), import('/app/lib/api.js')]);
    const send = async (as) => reportAbuse({
      link: as, category: form.elements.category.value, details: form.elements.details.value.trim(),
      contact: form.elements.contact.value.trim() || null, pow: await solvePow('report'),
    });
    // A server that doesn't take /p/ links yet answers `invalid`: the report goes again under the link's own
    // id as /s/<id>, which every server takes, so a paid link can be reported either way.
    const { report_id: id } = await send(link).catch((e) => {
      if (e.code !== 'invalid' || asPlain(link) === link) throw e;
      return send(asPlain(link));
    });
    form.reset();
    say(T.sent(id));
  } catch (e) {
    if (e.code === 'invalid') say(T.notLink, true);
    else if (e.code === 'rate_limited') say(T.wait(e.retryAfter ?? 60), true);
    else if (e.code === 'network') say(T.offline, true);
    else say(T.failed, true);
  } finally {
    submit.disabled = false;
  }
});

// The app's "Report this link", "Report this drop" and "Report this shop" open /fine-print#link=<the link without its key>.
// The fragment is cleared at once; the field takes the link only as the form would send it, and the
// page goes to the form (it sits below the privacy and terms text).
const prefill = new URLSearchParams(location.hash.slice(1)).get('link');
if (prefill !== null) {
  history.replaceState(null, '', location.pathname + location.search);
  (document.getElementById('report') ?? form).scrollIntoView({ block: 'start' });
  config.then((c) => {
    const link = cleanLink(prefill, false, c?.memo_origins ?? null);
    if (link && !linkInput.value) linkInput.value = link;
  });
}

// Only now, with the handler in place, can the form be seen and sent.
form.hidden = false;
