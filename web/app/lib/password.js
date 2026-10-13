// SPDX-License-Identifier: MIT
// Passwords (§4.7). P = PBKDF2-SHA256(password, salt, iter, 32). Link + password (the default) mixes
// P with the secret in the link; password only derives the link secret from P alone, so the server's
// copy of the access verifier is only as strong as the password, and the UI says so.
import { b64uDecode, b64uEncode } from './b64.js';
import { concat } from './bytes.js';
import { hkdf, pbkdf2Sha256, randomBytes } from './crypto.js';

export const PBKDF2_ITER = 600000;
const MAX_ITER = 5000000;
export const MIN_LENGTH = { link_password: 4, password: 10 };

export function newKdfParams() {
  return { alg: 'PBKDF2-SHA256', iter: PBKDF2_ITER, salt: b64uEncode(randomBytes(16)) };
}

function kdfSalt(kdf) {
  const salt = kdf && kdf.alg === 'PBKDF2-SHA256' && Number.isInteger(kdf.iter) && kdf.iter >= PBKDF2_ITER
    && kdf.iter <= MAX_ITER ? b64uDecode(kdf.salt) : null;
  if (!salt || salt.length !== 16) throw new TypeError('unsupported password parameters');
  return salt;
}

export async function linkPasswordSecret(s0, password, kdf) {
  const P = await pbkdf2Sha256(password, kdfSalt(kdf), kdf.iter);
  return hkdf(concat(s0, P), 'mutis/v1', 'link+password', 32);
}

export async function passwordOnlySecret(password, kdf) {
  const P = await pbkdf2Sha256(password, kdfSalt(kdf), kdf.iter);
  return hkdf(P, 'mutis/v1', 'password-only', 32);
}

// A hand-written list of very common passwords, English and Spanish ones (people type the passwords
// they know), and the mutis/Tari words people try first. Checked after undoing common substitutions
// and stripping trailing digits and symbols ("P@ssw0rd2024!" -> "password").
const COMMON = new Set(`
123456 password 12345678 qwerty 123456789 12345 1234 111111 1234567 dragon 123123 baseball abc123
football monkey letmein shadow master 666666 qwertyuiop 123321 mustang 1234567890 michael 654321
superman 1qaz2wsx 7777777 121212 000000 qazwsx 123qwe killer trustno1 jordan jennifer zxcvbnm asdfgh
hunter buster soccer harley batman andrew tigger sunshine iloveyou 2000 charlie robert thomas
hockey ranger daniel starwars klaster 112233 george computer michelle jessica pepper 1111 zxcvbn
555555 11111111 131313 freedom 777777 pass maggie 159753 aaaaaa ginger princess joshua cheese amanda
summer love ashley nicole chelsea biteme matthew access yankees 987654321 dallas austin thunder taylor
matrix montana moscow welcome welcome1 admin administrator
login passw0rd password1 qwerty123 abc12345 iloveyou1 princess1 monkey1 dragon1 football1 baseball1
secret secret1 changeme default guest root toor test test123 testing user demo letmein1 hello hello123
whatever trustme nothing mypassword passwords password12 password123 qwer1234 asdf1234 zaq12wsx
1q2w3e4r 1q2w3e 1q2w3e4r5t q1w2e3r4 qwe123 asd123 zxc123 aa123456 a123456 123abc 123654 147258369
147258 258456 789456123 789456 159357 951753 135790 246810 102030 101010 202020 999999 888888
222222 333333 444444 0987654321 112358 123987 696969 4815162342 abcdef abcd1234 qwertz azerty
asdfghjkl lovely loveme iloveu babygirl angel angels sweety sweetheart butterfly flower princesa
sunflower rainbow purple orange banana chocolate cookie cupcake bubbles daisy lucky blessed jesus
christ god mother father family friends friend forever soccer1 hockey1 tennis golfer cowboys eagles
packers lakers bulls yankee steelers warriors arsenal liverpool chelsea1 barcelona realmadrid juventus
pokemon naruto minecraft fortnite roblox gaming gamer pikachu spiderman batman1 superman1 ironman
starwars1 hogwarts gandalf frodo matrix1 zelda mario nintendo playstation xbox360 corvette ferrari
porsche mercedes bmw toyota honda nissan harley1 yamaha ducati mustang1 camaro jaguar tiger lion
eagle falcon shark wolf bear panther dolphin horse dog cat kitty kitten puppy snoopy garfield
alexander anthony william joseph david james john richard charles christopher daniel1 paul mark
donald steven kevin brian edward ronald timothy jason jeffrey ryan jacob gary nicholas eric
jonathan stephen larry justin scott brandon benjamin samuel gregory frank raymond patrick jack
dennis jerry tyler aaron henry adam douglas nathan peter zachary kyle walter harold carl arthur
maria susan karen nancy lisa betty sandra margaret carol kimberly emily donna melissa deborah
stephanie rebecca laura sharon cynthia kathleen amy shirley angela helen anna brenda pamela
contrasena contraseña clave secreto hola holamundo teamo amor mexico guadalajara monterrey
estrella mariposa corazon tequiero miamor bonita princesa1 futbol america chivas barcelona1
mutis mutislocker tari ootle bitcoin ethereum crypto monero satoshi blockchain wallet
`.trim().split(/\s+/));

const KEYBOARD = ['qwertyuiopasdfghjklzxcvbnm', '1234567890', 'abcdefghijklmnopqrstuvwxyz', 'qazwsxedcrfvtgbyhnujmikolp'];
const SUBST = { '@': 'a', 4: 'a', 0: 'o', 1: 'i', '!': 'i', 3: 'e', $: 's', 5: 's', 7: 't', '+': 't', 8: 'b', 9: 'g' };

function core(pw) {
  const lower = pw.toLowerCase();
  const stripped = lower.replace(/[\d\W_]+$/u, '');
  return [lower, stripped, Array.from(stripped || lower, (c) => SUBST[c] ?? c).join('')];
}

function isPattern(pw) {
  const p = pw.toLowerCase();
  if (/^(.)\1*$/u.test(p)) return true;
  if (/^(19|20)\d\d$/.test(p)) return true;
  const rev = [...p].reverse().join('');
  return p.length >= 4 && KEYBOARD.some((row) => row.includes(p) || row.includes(rev));
}

// -> {ok, problem: null|'too_short'|'common'|'pattern', strength: 'weak'|'fair'|'strong'}.
// Only the minimum length is a rule (`ok`); `common` and `pattern` drive the strength hint.
export function checkPassword(password, mode) {
  const length = Array.from(password).length;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^\da-zA-Z]/u].filter((re) => re.test(password)).length;
  let problem = null;
  if (length < MIN_LENGTH[mode]) problem = 'too_short';
  else if (core(password).some((c) => COMMON.has(c))) problem = 'common';
  else if (isPattern(password)) problem = 'pattern';
  const strength = problem ? 'weak' : length >= 20 || (length >= 14 && classes >= 3) ? 'strong' : 'fair';
  return { ok: problem !== 'too_short', problem, strength };
}
