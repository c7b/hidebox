// SPDX-License-Identifier: MIT
// The 404 page's last easter egg, for whoever opens the browser's console there: site.js imports this module only
// on that page (main.not-found). A module, never an inline script, so the site's CSP stays script-src 'self'.
// The ghost is ASCII art by Donovan Baker, from asciiart.eu; the artist asks for credit, so the console names him too.
// Its spacing is exact: a template literal, with each backslash and the backtick escaped.
const GHOST = `you found the last easter egg, you found the ghost of John McAfee...
 .-.
(o o) boo!
| O \\
 \\   \\
  \`~~~'`;
export const CREDIT = 'ghost: Donovan Baker, asciiart.eu';

export function start() {
  console.log(GHOST);
  console.log(`%c${CREDIT}`, 'font-size: 10px');
}
