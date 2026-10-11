// SPDX-License-Identifier: MIT
// A classic script in the <head> of app pages: sets <html lang> before the first paint, so the
// header and footer show in the language the app will use (same rule as lib/i18n.js pickLanguage).
(() => {
  const supported = ['en', 'es'];
  let lang = null;
  try {
    lang = JSON.parse(localStorage.getItem('mutis.lang'));
  } catch {
    // Blocked storage: fall back to the browser's languages.
  }
  if (!supported.includes(lang)) {
    lang = (navigator.languages || []).map((l) => l.toLowerCase().split('-')[0]).find((l) => supported.includes(l)) || 'en';
  }
  document.documentElement.lang = lang;
})();
