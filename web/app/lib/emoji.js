// SPDX-License-Identifier: MIT
// Safety codes: 12 emoji (96 bits) from a locker address's two public keys, so two people can compare
// an address out loud. The alphabet is Tari's 256-emoji address alphabet (RFC-0155), copied in order
// from tari-project/tari v6.1.0 (commit 463e53d), base_layer/common_types/src/emoji.rs, BSD-3-Clause;
// the tests check 256 unique single code points and the SHA-256 of the joined table.
import { concat, utf8 } from './bytes.js';
import { hex } from './b64.js';
import { sha256 } from './crypto.js';

export const ALPHABET = Object.freeze(`
  🐢 📟 🌈 🌊 🎯 🐋 🌙 🤔 🌕 ⭐ 🎋 🌰 🌴 🌵 🌲 🌸
  🌹 🌻 🌽 🍀 🍁 🍄 🥑 🍆 🍇 🍈 🍉 🍊 🍋 🍌 🍍 🍎
  🍐 🍑 🍒 🍓 🍔 🍕 🍗 🍚 🍞 🍟 🥝 🍣 🍦 🍩 🍪 🍫
  🍬 🍭 🍯 🥐 🍳 🥄 🍵 🍶 🍷 🍸 🍾 🍺 🍼 🎀 🎁 🎂
  🎃 🤖 🎈 🎉 🎒 🎓 🎠 🎡 🎢 🎣 🎤 🎥 🎧 🎨 🎩 🎪
  🎬 🎭 🎮 🎰 🎱 🎲 🎳 🎵 🎷 🎸 🎹 🎺 🎻 🎼 🎽 🎾
  🎿 🏀 🏁 🏆 🏈 ⚽ 🏠 🏥 🏦 🏭 🏰 🐀 🐉 🐊 🐌 🐍
  🦁 🐐 🐑 🐔 🙈 🐗 🐘 🐙 🐚 🐛 🐜 🐝 🐞 🦋 🐣 🐨
  🦀 🐪 🐬 🐭 🐮 🐯 🐰 🦆 🦂 🐴 🐵 🐶 🐷 🐸 🐺 🐻
  🐼 🐽 🐾 👀 👅 👑 👒 🧢 💅 👕 👖 👗 👘 👙 💃 👛
  👞 👟 👠 🥊 👢 👣 🤡 👻 👽 👾 🤠 👃 💄 💈 💉 💊
  💋 👂 💍 💎 💐 💔 🔒 🧩 💡 💣 💤 💦 💨 💩 ➕ 💯
  💰 💳 💵 💺 💻 💼 📈 📜 📌 📎 📖 📿 📡 ⏰ 📱 📷
  🔋 🔌 🚰 🔑 🔔 🔥 🔦 🔧 🔨 🔩 🔪 🔫 🔬 🔭 🔮 🔱
  🗽 😂 😇 😈 🤑 😍 😎 😱 😷 🤢 👍 👶 🚀 🚁 🚂 🚚
  🚑 🚒 🚓 🛵 🚗 🚜 🚢 🚦 🚧 🚨 🚪 🚫 🚲 🚽 🚿 🧲
`.trim().split(/\s+/));

export const SAFETY_CODE_LENGTH = 12;

export async function safetyCode(ownerPk, viewPk) {
  const h = await sha256(concat(utf8('mutis-safety-v1'), ownerPk, viewPk));
  const code = h.subarray(0, SAFETY_CODE_LENGTH);
  return {
    emoji: Array.from(code, (b) => ALPHABET[b]),
    hex: hex(code).match(/.{4}/g).join(' '),
  };
}
