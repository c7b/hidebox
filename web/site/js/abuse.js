// SPDX-License-Identifier: MIT
// The report form (spec §6.3 Abuse). The link's key is removed in this browser unless the reporter
// ticks the box, and the anti-bot proof of work is the app's own (/app/lib/pow.js), not a captcha.
// The form ships hidden and appears only once this module runs: a form the browser submitted by
// itself would put the whole link, key included, in a request to us and in the history.
import { config, lang } from './site.js';

const T = {
  en: {
    working: 'A few seconds of math instead of a captcha…',
    sent: (id) => `Thanks. Report ${id} received. We read every report and usually disable the link first and ask questions later.`,
    notLink: 'Paste a mutis link: it has /s/ or /d/ in it.',
    wait: (s) => `You can send another report in ${s} seconds.`,
    offline: 'We couldn\'t reach our server. Nothing was sent. Try again.',
    failed: 'Our server failed. Nothing was sent. Try again in a minute.',
  },
  es: {
    working: 'Unos segundos de cálculo en lugar de un captcha…',
    sent: (id) => `Gracias. Recibimos el reporte ${id}. Leemos cada reporte y casi siempre primero desactivamos el enlace y luego preguntamos.`,
    notLink: 'Pega un enlace de mutis: lleva /s/ o /d/.',
    wait: (s) => `Puedes enviar otro reporte en ${s} segundos.`,
    offline: 'No pudimos llegar a nuestro servidor. No se envió nada. Intenta de nuevo.',
    failed: 'Nuestro servidor falló. No se envió nada. Intenta de nuevo en un minuto.',
  },
}[lang];
const PATH = /^\/(s\/[A-Za-z0-9_-]{22}|d\/[0-9a-hjkmnp-tv-z]{10})$/;

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
    const pow = await solvePow('report');
    const { report_id: id } = await reportAbuse({
      link, category: form.elements.category.value, details: form.elements.details.value.trim(),
      contact: form.elements.contact.value.trim() || null, pow,
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

// The app's "Report this link" and "Report this drop" open /abuse#link=<the link without its key>.
// The fragment is cleared at once; the field takes the link only as the form would send it.
const prefill = new URLSearchParams(location.hash.slice(1)).get('link');
if (prefill !== null) {
  history.replaceState(null, '', location.pathname + location.search);
  config.then((c) => {
    const link = cleanLink(prefill, false, c?.memo_origins ?? null);
    if (link && !linkInput.value) linkInput.value = link;
  });
}

// Only now, with the handler in place, can the form be seen and sent.
form.hidden = false;
