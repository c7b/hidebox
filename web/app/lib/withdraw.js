// SPDX-License-Identifier: MIT
// Withdrawing earnings (docs/withdraw.md): the money people paid for this drive's pay links sits in stealth outputs
// to the drive's sales address. Each one is spent with its one-time key, c + k (lib/ootle.js stealthDhSecret: the
// receiver side of the stealth exchange, Ootle 0.48+), from the sales keys this browser derives from the drive's seed
// (lib/pay.js salesKeys). Nothing that can spend leaves this browser: the transaction is built, balanced and signed
// here, exactly as wallet.js's send() builds "Pay from my drive", and our server only relays it.
//
// The rules, the same on both sides (server/mutis/withdraw.py, served in /config `withdraw`):
// - the network fee (wallet.js FEE_UT) comes out of what is withdrawn: what arrives is the amount minus the fee;
// - at least `min_ut` is withdrawn, so at least as much as the fee arrives;
// - change below `dust_ut` (it would cost more to move than it is worth) goes along with the rest, said before Send;
// - one withdrawal spends at most `max_inputs` payments; more money needs another withdrawal;
// - only settled money: payments our server vouches for (counted, and test money or checked by the owner's drive),
//   and change of earlier withdrawals. A payment still being counted would lose its buyer the open if spent first.
// One withdrawal at a time in this browser; our server also refuses money already on its way.
import { hex, unhex } from './b64.js';
import { equal } from './bytes.js';
import { ApiError, enc, request } from './api.js';
import { AddressError, bindings, networkByte, parseAddress, ready, tryDecryptUtxo } from './ootle.js';
import { FEE_UT, VALIDITY_EPOCHS, WalletError, unsignedTx, waitFinal, witness } from './wallet.js';
import { chainIx } from './api-locker.js';
import { substateDown, substateValue } from './substate.js';
import { idbGet, idbPut } from './idb.js';

export { FEE_UT };

// The routes (docs/api.md "Withdraw"); each takes the drive's session.
export const getOutputs = (headers) => request('GET', '/me/sales/outputs', { headers });
const postWithdrawal = (body, headers) => request('POST', '/me/withdrawals', { json: body, headers });
const reportOutcome = (txId, outcome, headers) => request('POST', `/me/withdrawals/${enc(txId)}`, { json: { outcome }, headers });
// An output the drive can't find: our server asks every indexer itself, and takes it off the list only on proof it was spent.
const reportGone = (utxoId, headers) => request('POST', `/me/sales/outputs/${enc(utxoId)}/gone`, { headers });

export class WithdrawError extends Error {
  // code: 'busy' (one is on its way here) | 'input_gone' (a payment was spent elsewhere) | 'changed' (less than planned)
  constructor(code, detail = '') {
    super(detail || code);
    this.name = 'WithdrawError';
    this.code = code;
  }
}

const big = (v) => BigInt(v ?? 0);
const sum = (list) => list.reduce((n, o) => n + big(o.value_ut), 0n);
const byValue = (a, b) => (big(b.value_ut) > big(a.value_ut) ? 1 : big(b.value_ut) < big(a.value_ut) ? -1 : 0);
const nowS = () => Math.floor(Date.now() / 1000);
const TX = /^[0-9a-f]{64}$/;

// "0.25" or "12" (tTARI) -> µT, or null: digits, at most 6 decimals, nothing else.
export function parseAmount(text) {
  const m = /^(\d{1,12})(?:[.,](\d{1,6}))?$/.exec(String(text ?? '').trim());
  return m ? BigInt(m[1]) * 1000000n + BigInt((m[2] ?? '').padEnd(6, '0')) : null;
}

// The rules as our server serves them, with the fee this browser pays in any case.
export function rulesOf(serverRules = {}) {
  return {
    fee: FEE_UT, min: big(serverRules.min_ut ?? FEE_UT * 2n), dust: big(serverRules.dust_ut ?? FEE_UT),
    maxInputs: Number(serverRules.max_inputs ?? 8), pendingS: Number(serverRules.pending_s ?? 600),
  };
}

// What can go now: settled outputs with no withdrawal on its way (one older than the window counts as free, as on
// our server). -> {free, onTheirWay, total, best}: `best` is the most one withdrawal can take (its biggest outputs).
export function available(outputs, rules, now = nowS()) {
  const onTheirWay = outputs.filter((o) => o.pending_tx && now - (o.pending_at ?? 0) < rules.pendingS);
  const free = outputs.filter((o) => !onTheirWay.includes(o)).sort(byValue);
  return { free, onTheirWay, total: sum(free), best: sum(free.slice(0, rules.maxInputs)) };
}

// A withdrawal of `want` µT ('all': the most one withdrawal can take): its inputs (biggest first, fewest), what
// arrives (want minus the fee), the change back to the sales address, and the dust that went along instead of
// staying. -> {inputs, withdrawUt, feeUt, arriveUt, changeUt, dustUt, capped} or {error, …}.
export function plan(outputs, want, rules) {
  const { free, total, best } = available(outputs, rules);
  const take = want === 'all' ? best : big(want);
  if (take < rules.min) return { error: 'below_min', min: rules.min };
  if (take > total) return { error: 'over', total };
  if (take > best) return { error: 'too_many', best, max: rules.maxInputs };
  const inputs = [];
  let got = 0n;
  for (const o of free) {
    if (got >= take) break;
    inputs.push(o);
    got += big(o.value_ut);
  }
  let withdrawUt = take;
  let changeUt = got - take;
  let dustUt = 0n;
  if (changeUt > 0n && changeUt < rules.dust) {
    dustUt = changeUt;
    withdrawUt = got;
    changeUt = 0n;
  }
  return { inputs, withdrawUt, feeUt: rules.fee, arriveUt: withdrawUt - rules.fee, changeUt, dustUt, capped: free.length > rules.maxInputs && want === 'all' };
}

// A sales output as the indexer has it now, opened with the sales view key. Gone (404, a proven down, frozen) means
// spent: here, on another device, or by a withdrawal whose outcome wasn't reported.
async function loadInput(keys, utxoId) {
  let sub;
  try {
    sub = await chainIx('GET', `substates/${utxoId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) throw new WithdrawError('input_gone', utxoId);
    throw e;
  }
  const utxo = (await substateValue(sub))?.Utxo;
  const body = utxo?.output?.output;
  if (!body || utxo.is_frozen) throw new WithdrawError('input_gone', utxoId);
  const mine = await tryDecryptUtxo(keys.viewSk, { id: utxoId, nonce: body.public_nonce, enc: body.encrypted_data });
  if (!mine) throw new WithdrawError('input_gone', utxoId);
  return { utxoId, nonce: unhex(body.public_nonce), value: mine.value, mask: mine.mask };
}

// The address a withdrawal goes to: an Ootle address on this network, checksum and keys checked by the official
// library (lib/ootle.js parseAddress: 'bad_address', 'mainnet_address' for another network, 'l1_address'), with no
// payment reference ('pay_ref'), and not this drive's own sales address ('own_sales').
export async function checkAddress(identity, to) {
  const dest = await parseAddress(to);
  if (dest.payRef) throw new AddressError('pay_ref');
  const { salesKeys } = await import('./pay.js');
  const keys = await salesKeys(identity);
  if (equal(dest.ownerPk, keys.ownerPk) && equal(dest.viewPk, keys.viewPk)) throw new AddressError('own_sales');
  return dest;
}

// ---------- this browser's receipts (the address stays here, never on our server) ----------

const RECEIPTS = (identity) => `withdrawals:${identity.id}`;

export async function receipts(identity) {
  try {
    return (await idbGet('inbox', RECEIPTS(identity))) ?? [];
  } catch {
    return [];
  }
}

async function keepReceipt(identity, receipt) {
  try {
    const all = (await receipts(identity)).filter((r) => r.tx !== receipt.tx);
    all.unshift(receipt);
    await idbPut('inbox', RECEIPTS(identity), all.slice(0, 50));
  } catch {
    // Storage blocked: the withdrawal stands; this browser just can't list it later.
  }
}

// ---------- withdrawals that never said how they ended ----------

// For each withdrawal pending past the window (the tab closed before the chain answered): ask the chain how it ended
// and tell our server, so its money is spent or free again. -> how many were settled.
export async function settleStale(outputs, rules, headers, now = nowS()) {
  const stale = new Map();
  for (const o of outputs) {
    if (o.pending_tx && TX.test(o.pending_tx) && now - (o.pending_at ?? 0) >= rules.pendingS && !stale.has(o.pending_tx)) stale.set(o.pending_tx, o);
  }
  let settled = 0;
  for (const [txId, o] of stale) {
    const res = await chainIx('GET', `transactions/${txId}/result`).catch(() => null);
    const fin = res?.result?.Finalized;
    let outcome = fin ? (fin.final_decision === 'Commit' ? 'commit' : 'reject') : null;
    if (!outcome && o.source === 'sale') {
      // Forgotten by the indexer (50 epochs): the input tells, on evidence only (as lib/pay.js auditOutput). Shown
      // unspent, it never went; proven spent, it did. A 404 or an answer nothing can read says neither (an indexer
      // that hasn't caught up answers the same), so the withdrawal stays as it is and is asked about again.
      const sub = await chainIx('GET', `substates/${o.utxo_id}`).catch(() => null);
      if (sub) outcome = substateDown(sub) ? 'commit' : (await substateValue(sub))?.Utxo ? 'reject' : null;
    }
    if (outcome && (await reportOutcome(txId, outcome, headers).then(() => true, () => false))) settled++;
  }
  return settled;
}

// ---------- the withdrawal ----------

let inFlight = null;

// Sends plan.arriveUt to `to`. onStep(step, txId?): 'build' (in this browser), 'sent' (our server relayed it),
// 'chain' (committed). -> {tx_id, to, arriveUt, feeUt, changeUt, dustUt, inputs}. A second call while one runs is
// refused ('busy'): the button is off meanwhile, and our server refuses the same money twice.
export function withdraw(identity, opts) {
  if (inFlight) return Promise.reject(new WithdrawError('busy'));
  inFlight = run(identity, opts).finally(() => { inFlight = null; });
  return inFlight;
}

async function run(identity, { to, plan: p, rules, headers, signal, onStep = () => {} }) {
  await ready();
  const w = bindings();
  const dest = await checkAddress(identity, to);
  const { salesKeys } = await import('./pay.js');
  const keys = await salesKeys(identity);
  onStep('build');
  const inputs = [];
  for (const o of p.inputs) {
    try {
      inputs.push(await loadInput(keys, o.utxo_id));
    } catch (e) {
      // Spent elsewhere: without this, every later plan would pick it again (biggest first) and fail the same way.
      if (e instanceof WithdrawError && e.code === 'input_gone') await reportGone(o.utxo_id, headers).catch(() => null);
      throw e;
    }
  }
  // The chain's values decide, not the list's: the change is what is left of them.
  const total = inputs.reduce((n, i) => n + i.value, 0n);
  if (total < p.withdrawUt) throw new WithdrawError('changed');
  let withdrawUt = p.withdrawUt;
  let changeUt = total - withdrawUt;
  if (changeUt > 0n && changeUt < rules.dust) {
    withdrawUt = total;
    changeUt = 0n;
  }
  const arriveUt = withdrawUt - FEE_UT;
  if (arriveUt < rules.min - FEE_UT) throw new WithdrawError('changed');
  const outputs = [witness(networkByte(), dest, arriveUt, null)];
  let changeNonce = null;
  if (changeUt > 0n) {
    const change = witness(networkByte(), keys, changeUt, null);
    changeNonce = JSON.parse(change).witness.sender_public_nonce;
    outputs.push(change);
  }
  const seal = w.generateKeypair();
  const sealSk = seal.secret_key;
  const sealPk = seal.public_key;
  seal.free();
  const inputJson = '[' + inputs.map((i) => `{"mask_and_value":{"value":${i.value},"mask":"${hex(i.mask)}"}}`).join(',') + ']';
  const statement = w.buildStealthTransferStatement(inputJson, 0n, '[' + outputs.join(',') + ']', FEE_UT, sealPk);
  w.validateStealthTransfer(statement, null);
  const { current_epoch: epoch } = await chainIx('GET', 'epoch-manager/stats');
  if (!Number.isSafeInteger(epoch) || epoch < 0) throw new WalletError('rejected', 'bad epoch from the indexer');
  let tx = unsignedTx(statement, inputs, epoch + VALIDITY_EPOCHS);
  for (const i of inputs) tx = w.addTransactionSigner(tx, w.stealthDhSecret(networkByte(), keys.ownerSk, keys.viewSk, i.nonce), sealPk);
  const envelope = w.borEncodeTransaction(w.sealTransaction(tx, sealSk));
  // The change goes back to the sales address: our server keeps its id and value, so any device can withdraw it.
  let change;
  if (changeNonce) {
    const out = JSON.parse(statement).outputs_statement.outputs.map((x) => x.output).find((x) => x.sender_public_nonce === changeNonce);
    if (out) change = { utxo_id: `utxo_${'01'.repeat(32)}_${out.commitment}`, value_ut: changeUt.toString() };
  }
  signal?.throwIfAborted();
  const { tx_id: txId } = await postWithdrawal({ transaction: envelope, ...(change ? { change } : {}) }, headers);
  const receipt = { tx: txId, to, arriveUt: arriveUt.toString(), feeUt: FEE_UT.toString(), changeUt: changeUt.toString(), at: nowS(), state: 'sent' };
  await keepReceipt(identity, receipt);
  onStep('sent', txId);
  try {
    await waitFinal(txId, { signal });
  } catch (e) {
    if (e instanceof WalletError && e.code === 'rejected') {
      await reportOutcome(txId, 'reject', headers).catch(() => null);
      await keepReceipt(identity, { ...receipt, state: 'rejected' });
    }
    throw Object.assign(e, { txId });
  }
  await reportOutcome(txId, 'commit', headers).catch(() => null);  // if this is lost, settleStale() tells it later
  await keepReceipt(identity, { ...receipt, state: 'done' });
  onStep('chain', txId);
  return { tx_id: txId, to, arriveUt, feeUt: FEE_UT, changeUt, dustUt: withdrawUt - p.withdrawUt + p.dustUt, inputs: inputs.map((i) => i.utxoId) };
}

// The address as wallets show it: the network prefix with its separator (`otl_esm_1` on Esmeralda, `otl_1` on the
// mainnet), then the first and last 6 characters set apart.
export function addressParts(address) {
  const a = String(address);
  const prefix = /^otl_(?:[a-z]+_)?1/.exec(a)?.[0] ?? '';   // otl_esm_1 on Esmeralda, otl_1 on the mainnet
  const body = a.slice(prefix.length);
  if (body.length <= 12) return { prefix, head: body, middle: '', tail: '' };
  return { prefix, head: body.slice(0, 6), middle: body.slice(6, -6), tail: body.slice(-6) };
}

