// SPDX-License-Identifier: MIT
// The exit wall's words in English: stage directions, cue labels and fates (11-brand §9.3 S1).
export default {
  script: ['(A wall of locked files. We can\'t see inside any of them. Each light means: waiting for its cue.)',
    '(Someone opens a link. Once.)', '(Third view.)', '(Midnight.)', '(The rest: opened, expired, deleted.)',
    '(One light left on.)'],
  data: { intro: '(The last files stored on our server, by their exit rules: not whose, not what, not whether they\'ve left. We can\'t see inside any of them.)',
    once: '(Once: the first open is the cue.)', views: '(Views: the last allowed view is the cue.)',
    time: '(Timed: the clock is the cue.)', kept: '(Kept: its owner\'s delete is the cue.)',
    end: '(One light left on: a file we locked ourselves.)' },
  views: ['(3 views)', '(2 views)', '(1 view)'],
  labels: { once: '(once)', views: '(views)', time: '(timed)', kept: '(only me)', empty: '' },
  fates: { once: 'the first open is its cue.', views: 'the last view is its cue.', time: 'the clock is its cue.',
    kept: 'its owner\'s delete is its cue.', empty: 'empty.' },
  yours: '(yours)',
  desc: (n) => `A wall of lockers drawn from the last ${n} files stored on our server: each label is only its exit rule, never a name, its contents or whether it has left. We can't see inside any of them. The scene plays every cue forward until one light is left: a file we locked ourselves.`,
};
