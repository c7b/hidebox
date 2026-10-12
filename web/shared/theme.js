// SPDX-License-Identifier: MIT
// A classic script loaded in <head>, so what it decides applies before the first paint.
// "Lights off / Lights on": the choice is a per-browser convenience in localStorage; without it the OS
// decides, except on Oct 31 from 18:00 local, when the house lights are already down (11-brand §13.11).
// html.motion: scripts run and the visitor allows motion, so a page may lay out its scroll scene for
// playing (the home page's exit wall) instead of its static version.
(() => {
  const KEY = 'mutis.theme';
  const root = document.documentElement;
  const osDark = matchMedia('(prefers-color-scheme: dark)');
  if (!matchMedia('(prefers-reduced-motion: reduce)').matches) root.classList.add('motion');

  const stored = () => {
    try {
      return localStorage.getItem(KEY);
    } catch {
      return null;
    }
  };
  // Oct 31 from 18:00 local. A classic script, so the rule lives here and not in a module that would load after paint.
  const now = new Date();
  const halloweenNight = now.getMonth() === 9 && now.getDate() === 31 && now.getHours() >= 18;
  const chosen = stored();
  if (chosen === 'light' || chosen === 'dark') root.dataset.theme = chosen;
  else if (halloweenNight) root.dataset.theme = 'dark';

  const isDark = () => (root.dataset.theme ? root.dataset.theme === 'dark' : osDark.matches);

  function label(button) {
    button.textContent = isDark() ? button.dataset.on : button.dataset.off;
  }

  document.addEventListener('DOMContentLoaded', () => {
    const buttons = document.querySelectorAll('[data-theme-toggle]');
    for (const button of buttons) {
      label(button);
      button.hidden = false;
      button.addEventListener('click', () => {
        const next = isDark() ? 'light' : 'dark';
        root.dataset.theme = next;
        try {
          localStorage.setItem(KEY, next);
        } catch {
          // Private window or blocked storage: the choice lasts for this page only.
        }
        buttons.forEach(label);
      });
    }
    osDark.addEventListener('change', () => buttons.forEach(label));
  });
})();
