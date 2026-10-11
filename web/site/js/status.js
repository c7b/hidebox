// SPDX-License-Identifier: MIT
// /status: the public subset our health check writes to /status.json every five minutes.
import { getJson, lang, locale } from './site.js';

const T = {
  en: {
    names: { https: 'Web server and certificate', api: 'API', chain_worker: 'Chain worker', walletd: 'Our wallet',
      sponsor_balance: 'Demo tTARI in the sponsor wallet', mirror: 'Our copy of the chain', canary: 'Hourly test file',
      credits: 'Crediting payments', disk: 'Disk space', budgets: 'Daily budgets' },
    states: { green: 'working', amber: 'slow or near a limit', red: 'broken' },
  },
  es: {
    names: { https: 'Servidor web y certificado', api: 'API', chain_worker: 'Proceso de la cadena', walletd: 'Nuestra cartera',
      sponsor_balance: 'tTARI de demostración en la cartera patrocinadora', mirror: 'Nuestra copia de la cadena',
      canary: 'Archivo de prueba de cada hora', credits: 'Abono de pagos', disk: 'Espacio en disco', budgets: 'Presupuestos diarios' },
    states: { green: 'funciona', amber: 'lento o cerca de un límite', red: 'roto' },
  },
}[lang];

getJson('/status.json').then((status) => {
  const list = document.querySelector('[data-status-list]');
  for (const [name, state] of Object.entries(status.checks ?? {})) {
    if (!(state in T.states)) continue;
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = T.names[name] ?? name;
    const chip = document.createElement('span');
    chip.className = `state ${state}`;
    chip.textContent = T.states[state];
    li.append(label, chip);
    list.append(li);
  }
  document.querySelector('[data-status-time]').textContent =
    new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(status.updated_at * 1000));
  document.querySelector('[data-status-attention]').hidden = !status.attention;
  document.querySelector('[data-status]').hidden = false;
  document.querySelector('[data-status-missing]').hidden = true;
}).catch(() => {}); // the "board is dark" line stays
