// SPDX-License-Identifier: MIT
// The secret word (14-ghost-design §5): four words drawn from a list of 1,296 (about 41 bits), loaded
// only when someone asks for a word. Rejection sampling keeps every word equally likely.
let list = null;

export async function fourWords() {
  list ??= (await (await fetch('/app/lib/words.txt')).text()).split('\n').filter(Boolean);
  const limit = 65536 - (65536 % list.length);
  const out = [];
  while (out.length < 4) {
    for (const n of crypto.getRandomValues(new Uint16Array(8))) if (n < limit && out.length < 4) out.push(list[n % list.length]);
  }
  return out.join('-');
}
