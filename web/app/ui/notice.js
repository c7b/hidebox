// SPDX-License-Identifier: MIT
// The staging banner (claim C62) on the drive's page, which has no site header: when /config says staging (the
// mainnet instance's rehearsal on Esmeralda), the page says so above everything. The other app pages get the
// same banner with the site's header (web/shared/partials/staging-banner.html, set by the build and site.js).
import { h } from './lines.js';
import { t } from '../lib/i18n.js';

export function stagingBanner(cfg) {
  if (!cfg?.staging || document.querySelector('.staging-banner')) return;
  document.body.prepend(h('div', { class: 'staging-banner', role: 'note', 'data-testid': 'staging-banner' },
    h('p', {}, t('staging.banner', { testnet: String(cfg.testnet_origin ?? '').replace(/^https:\/\//, '') }))));
}
