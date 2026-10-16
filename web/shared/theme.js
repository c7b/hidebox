// SPDX-License-Identifier: MIT
// A classic script loaded in <head>, so what it decides applies before the first paint.
// The light switch (DESIGN.md): lights on = the light theme, lights off = the dark one, where the ghost
// glows. It follows the OS until it is pressed, then remembers the choice in this browser (a
// convenience: storage may be blocked, and then the choice lasts for this page). Its name stays
// "Lights" and its state is aria-pressed (pressed = lights on). On Oct 31 from 18:00 local the house
// lights are already down (11-brand §13.11), unless the visitor chose.
// html.motion: scripts run and the visitor allows motion.
// html[data-has-drive]: a drive lives in this browser ('mutis.drive', kept by site.js), so Open my drive paints first.
(() => {
  const KEY = 'mutis.theme';
  const root = document.documentElement;
  const osDark = matchMedia('(prefers-color-scheme: dark)');
  if (!matchMedia('(prefers-reduced-motion: reduce)').matches) root.classList.add('motion');

  const stored = (key) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  };
  if (stored('mutis.drive') === '1') root.dataset.hasDrive = '';
  const now = new Date();
  const halloweenNight = now.getMonth() === 9 && now.getDate() === 31 && now.getHours() >= 18;
  const chosen = stored(KEY);
  if (chosen === 'light' || chosen === 'dark') root.dataset.theme = chosen;
  else if (halloweenNight) root.dataset.theme = 'dark';

  const isDark = () => (root.dataset.theme ? root.dataset.theme === 'dark' : osDark.matches);
  const paint = (button) => button.setAttribute('aria-pressed', String(!isDark()));

  document.addEventListener('DOMContentLoaded', () => {
    const buttons = document.querySelectorAll('[data-theme-toggle]');
    for (const button of buttons) {
      paint(button);
      button.hidden = false;
      button.addEventListener('click', () => {
        const next = isDark() ? 'light' : 'dark';
        root.dataset.theme = next;
        try {
          localStorage.setItem(KEY, next);
        } catch {
          // Private window or blocked storage: the choice lasts for this page only.
        }
        buttons.forEach(paint);
      });
    }
    osDark.addEventListener('change', () => buttons.forEach(paint));
  });
})();
