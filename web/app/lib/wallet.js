// SPDX-License-Identifier: MIT
// The browser wallet (direct mode, gate G1): the locker's separate wallet keypair spends its own
// stealth outputs (funded by a sponsor grant) and the browser builds, signs and submits the
// transaction itself, through our read/submit proxy. Same transaction shape as the official wallet
// daemon's stealth transfers: the stealth statement runs in the fee phase and reveals exactly the fee
// into a bucket that pays it, so no account or vault is involved and the chain shows no sender
// account or address. deliver() picks this or our relay for each send.
import { b64uEncode, hex, unhex } from './b64.js';
import { NETWORK_BYTE, TARI_RESOURCE, bindings, parseAddress, ready, tryDecryptUtxo } from './ootle.js';
import { ApiError, config } from './api.js';
import { chainIx, demoPay, postCourier, requestSponsor } from './api-locker.js';
import { inboxState, scan, updateWallet } from './scan.js';
import { memoFor } from './courier.js';
import { hasJudgePass, withPow } from './pow.js';
import { localGet, localSet } from './store.js';
import { authHeaders } from './session.js';

// The same flat fee as every relay send (§1.4), so a direct send doesn't stand out by its fee.
export const FEE_UT = 30000n;
const VALIDITY_EPOCHS = 10;
const MAX_INPUTS = 4;
// Inputs of a submitted transaction are held back this long (longer than waitFinal waits); after
// that a send asks the indexer again: gone means spent, still there means the transaction failed.
const PENDING_MS = 180000;

export class WalletError extends Error {
  // code: 'insufficient' | 'input_gone' | 'rejected' | 'timeout'
  constructor(code, detail = '') {
    super(detail || code);
    this.name = 'WalletError';
    this.code = code;
  }
}

const usable = (w, now) => !w.spent && !(w.pending && now - w.pending.at < PENDING_MS);

export async function balance(identity) {
  const { wallet } = await inboxState(identity);
  const now = Date.now();
  return wallet.filter((w) => usable(w, now)).reduce((sum, w) => sum + BigInt(w.value), 0n);
}

// One sponsor grant per locker per UTC day (PoW `sponsor`, or a judge pass). -> {job_id}
async function requestGrant(identity, opts = {}) {
  return withPow('sponsor', (pow, judge) => requestSponsor(identity.wallet.address, pow, { ...authHeaders(), ...judge }), opts);
}

// "Pay with our demo wallet" (§6.3 demo-pay): our sponsor wallet pays this locker's invoice. -> {job_id}
export async function demoPayInvoice(invoiceId, opts = {}) {
  return withPow('demo_pay', (pow, judge) => demoPay(invoiceId, pow, { ...authHeaders(), ...judge }), opts);
}

// A wallet output as the indexer has it now, unblinded with the wallet's view key. A spent output is
// gone from the indexer (404); any other failure is passed on, so a network blip spends nothing.
async function loadInput(identity, utxoId) {
  let sub;
  try {
    sub = await chainIx('GET', `substates/${utxoId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) throw new WalletError('input_gone', utxoId);
    throw e;
  }
  const body = sub?.substate?.Utxo?.output?.output;
  if (!body || sub.substate.Utxo.is_frozen) throw new WalletError('input_gone', utxoId);
  const mine = await tryDecryptUtxo(identity.wallet.viewSk, { id: utxoId, nonce: body.public_nonce, enc: body.encrypted_data });
  if (!mine) throw new WalletError('input_gone', utxoId);
  return { utxoId, nonce: unhex(body.public_nonce), value: mine.value, mask: mine.mask };
}

function witness(network, keys, amount, memo) {
  return bindings().createStealthOutputWitness(
    network, keys.ownerPk, keys.viewPk, amount, TARI_RESOURCE, null, memo ? JSON.stringify(memo) : null, null, 0n,
  );
}

// Unsigned transaction JSON. The statement is spliced in byte-exact, because its u64 amounts are bare
// JSON numbers that must never round-trip through a JS number.
function unsignedTx(statement, inputs, maxEpoch) {
  const substates = [`{"substate_id":"${TARI_RESOURCE}","version":null,"is_write":false}`]
    .concat(inputs.map((i) => `{"substate_id":"${i.utxoId}","version":null,"is_write":true}`));
  return `{"network":${NETWORK_BYTE},"fee_instructions":[`
    + `{"StealthTransfer":{"resource_address_ref":{"Address":"${TARI_RESOURCE}"},"statement":${statement},"revealed_input_bucket":null}},`
    + '{"PutLastInstructionOutputOnWorkspace":{"key":0}},{"PayFeeFromBucket":{"bucket":{"id":0,"offset":null}}}],'
    + `"instructions":[],"inputs":[${substates.join(',')}],"min_epoch":null,"max_epoch":${maxEpoch},`
    + '"dry_run":false,"is_seal_signer_authorized":true,"blobs":[],"nonce":0}';
}

async function waitFinal(txId, { timeoutMs = 120000, signal } = {}) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    signal?.throwIfAborted();
    // A failed poll is retried until the deadline; only a final decision ends the wait.
    const res = await chainIx('GET', `transactions/${txId}/result`).catch(() => null);
    const fin = res?.result?.Finalized;
    if (fin) {
      if (fin.final_decision === 'Commit') return fin;
      throw new WalletError('rejected', JSON.stringify(fin.final_decision).slice(0, 200));
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new WalletError('timeout', txId);
}

// Send `amountUt` to an Ootle address with an optional memo object ({Message: "…"}).
// onSubmit(txId): the indexer took the transaction (it may still land after a timeout).
// -> {tx_id, inputs, fee_ut}
export async function send(identity, { to, amountUt, memo = null, signal, onSubmit = null }) {
  await ready();
  const w = bindings();
  const dest = await parseAddress(to);
  const amount = BigInt(amountUt);
  const { wallet } = await inboxState(identity);
  const now = Date.now();
  const candidates = wallet.filter((x) => usable(x, now)).sort((a, b) => (BigInt(b.value) > BigInt(a.value) ? 1 : -1));
  const inputs = [];
  let total = 0n;
  for (const c of candidates) {
    if (total >= amount + FEE_UT || inputs.length >= MAX_INPUTS) break;
    try {
      const input = await loadInput(identity, c.utxoId);
      inputs.push(input);
      total += input.value;
    } catch (e) {
      if (!(e instanceof WalletError)) throw e;
      await updateWallet(identity, [c.utxoId], { spent: true, pending: null }); // spent here, in another tab or on another device
    }
  }
  if (total < amount + FEE_UT) throw new WalletError('insufficient');

  const outputs = [witness(NETWORK_BYTE, dest, amount, memo)];
  const change = total - amount - FEE_UT;
  if (change > 0n) outputs.push(witness(NETWORK_BYTE, identity.wallet, change, null));
  const seal = w.generateKeypair();
  const sealSk = seal.secret_key;
  const sealPk = seal.public_key;
  seal.free();
  const inputJson = '[' + inputs.map((i) => `{"mask_and_value":{"value":${i.value},"mask":"${hex(i.mask)}"}}`).join(',') + ']';
  const statement = w.buildStealthTransferStatement(inputJson, 0n, '[' + outputs.join(',') + ']', FEE_UT, sealPk);
  w.validateStealthTransfer(statement, null);

  // The epoch arrives as proxied JSON and is spliced into the transaction text.
  const { current_epoch: epoch } = await chainIx('GET', 'epoch-manager/stats');
  if (!Number.isSafeInteger(epoch) || epoch < 0) throw new WalletError('rejected', 'bad epoch from the indexer');
  let tx = unsignedTx(statement, inputs, epoch + VALIDITY_EPOCHS);
  // Each input is authorised by its one-time key c + k (the receiver side of the stealth DH).
  for (const i of inputs) tx = w.addTransactionSigner(tx, w.stealthDhSecret(NETWORK_BYTE, identity.wallet.ownerSk, i.nonce), sealPk);
  const envelope = w.borEncodeTransaction(w.sealTransaction(tx, sealSk));

  // Submitting takes the locker session: the proxy relays sends of our lockers, not anyone's transactions.
  const { transaction_id: txId } = await chainIx('POST', 'transactions', { transaction: envelope }, authHeaders());
  try {
    onSubmit?.(txId);
  } catch {
    // the caller's display only: the inputs below are marked whatever it did
  }
  const ids = inputs.map((i) => i.utxoId);
  await updateWallet(identity, ids, { pending: { tx: txId, at: Date.now() } });
  try {
    await waitFinal(txId, { signal });
  } catch (e) {
    // Rejected: nothing was spent. A timeout or an abort leaves them pending (see PENDING_MS).
    if (e instanceof WalletError && e.code === 'rejected') await updateWallet(identity, ids, { pending: null });
    throw e;
  }
  await updateWallet(identity, ids, { spent: true, pending: null });
  return { tx_id: txId, inputs: ids, fee_ut: FEE_UT.toString() };
}

// Pays a pack invoice from the browser wallet. The memo carries the invoice id, which the server's
// payment check accepts as the pay-ref (§10.5 step 2). -> {tx_id, …}
export async function payInvoice(identity, invoice, opts = {}) {
  return send(identity, { to: invoice.address, amountUt: invoice.amount_ut, memo: { Message: invoice.invoice_id }, ...opts });
}

const courierAmount = (cfg) => BigInt(cfg.courier?.amount_ut ?? '1000');

// Whether the next send goes from this browser: /config says direct, and after a fresh scan (the
// sponsor grant is an output only a scan finds) the spendable balance covers the courier amount plus
// the fee. The send screen shows this before Send; deliver() decides by it.
export async function canSendDirect(identity, cfg, { signal } = {}) {
  if (!(cfg.send_mode === 'direct' && cfg.features?.direct_send)) return false;
  await scan(identity, { signal }).catch(() => null); // a failed scan only means the balance is as last seen
  return (await balance(identity)) >= courierAmount(cfg) + FEE_UT;
}

const GRANT = 'mutis.grant';
const GRANT_WAIT_MS = 10 * 60000;
let asking = null; // the page's grant request in flight, shared by every caller

// The sponsor grant, asked for whenever the browser wallet can't cover the next spend (`need` µT: a
// courier send by default, or a pack): at most once a UTC day per locker, and once more that day
// after a judge pass is saved, since a pass lifts the per-network limit. The day's answer is kept on
// this device (store.js). -> 'funded' | 'pending' (asked; a scan finds it in a minute or two) | 'refused' (403
// or 429: this network's grants, this locker's or today's budget are used up, or an asked grant
// still hasn't arrived after ten minutes) | null when this deployment has no sponsored direct sends.
export async function ensureGrant(identity, cfg, { need = courierAmount(cfg) + FEE_UT, signal } = {}) {
  if (!(cfg.send_mode === 'direct' && cfg.features?.direct_send && cfg.features?.sponsor)) return null;
  await scan(identity, { signal }).catch(() => null); // a failed scan only means the balance is as last seen
  if ((await balance(identity)) >= BigInt(need)) return 'funded';
  const day = new Date().toISOString().slice(0, 10);
  const judge = hasJudgePass();
  const asked = localGet(GRANT);
  const today = asked?.id === identity.id && asked.day === day ? asked : null;
  if (today?.state === 'pending') return Date.now() - today.at < GRANT_WAIT_MS ? 'pending' : 'refused';
  if (today && (today.judge || !judge)) return today.state;
  asking ??= requestGrant(identity).then(() => 'pending', (e) => {
    if (!(e instanceof ApiError && (e.status === 403 || e.status === 429))) throw e;
    return 'refused';
  }).then((state) => {
    localSet(GRANT, { id: identity.id, day, judge, state, at: Date.now() });
    return state;
  }).finally(() => { asking = null; });
  return asking;
}

// Sends a sealed link (kind 3 or 4, the 125-byte blob) to an Ootle address: from the browser wallet
// when canSendDirect(), otherwise through our relay (session required; a judge pass draws from the
// reserved budget). A direct send that finds too little after asking the indexer falls back to the
// relay too; nothing was submitted then.
// -> {mode: 'direct', tx_id, …} | {mode: 'relay', job_id, not_before}
export async function deliver(identity, { address, kind, blob, signal }) {
  const cfg = await config();
  if (await canSendDirect(identity, cfg, { signal })) {
    try {
      const memo = { Message: memoFor(cfg.origin, kind, blob) };
      return { mode: 'direct', ...(await send(identity, { to: address, amountUt: courierAmount(cfg), memo, signal })) };
    } catch (e) {
      if (!(e instanceof WalletError && e.code === 'insufficient')) throw e;
    }
  }
  const body = { to: 'address', address, kind, blob: b64uEncode(blob) };
  return { mode: 'relay', ...(await withPow(null, (pow, judge) => postCourier(body, { ...authHeaders(), ...judge }), { signal })) };
}
