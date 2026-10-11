// SPDX-License-Identifier: MIT
// The API endpoints of lockers, dead drops, the courier, the chain mirror and payments (§6.3), kept
// out of api.js so the anonymous widget doesn't download them. Same request() and ApiError.
import { enc, request } from './api.js';

// Lockers and sessions
export const register = (body, headers) => request('POST', '/auth/register', { json: body, headers });
export const signIn = (body) => request('POST', '/auth/session', { json: body });
export const signOut = (headers) => request('DELETE', '/auth/session', { headers, expect: 'none' });
export const getMe = (headers) => request('GET', '/me', { headers });
export const deleteMe = (body, headers) => request('DELETE', '/me', { json: body, headers, expect: 'none' });
export const adoptItem = (itemId, body, headers) => request('POST', `/items/${enc(itemId)}/adopt`, { json: body, headers });

// Dead drops
export const createDropRecord = (body, headers) => request('POST', '/drops', { json: body, headers });
export const getDropRecord = (dropId) => request('GET', `/drops/${enc(dropId)}`);
export const patchDrop = (dropId, body, headers) => request('PATCH', `/drops/${enc(dropId)}`, { json: body, headers });

// Courier and jobs
export const postCourier = (body, headers) => request('POST', '/courier', { json: body, headers });
export const getJob = (jobId) => request('GET', `/jobs/${enc(jobId)}`);

// Chain
export const chainUtxos = (after, limit = 1000, signal) => request('GET', `/chain/utxos?after=${after}&limit=${limit}`, { signal, timeoutMs: 30000 });
export const chainSeq = (epoch) => request('GET', `/chain/seq?epoch=${epoch}`);
export const chainIx = (method, path, json) => request(method, `/chain/ix/${path}`, { json });
export const txView = (txId) => request('GET', `/chain/tx/${enc(txId)}/view`);

// Payments
export const createInvoice = (pack, headers) => request('POST', '/invoices', { json: { pack }, headers });
export const getInvoice = (invoiceId, headers) => request('GET', `/invoices/${enc(invoiceId)}`, { headers });
export const demoPay = (invoiceId, pow, headers) => request('POST', `/invoices/${enc(invoiceId)}/demo-pay`, { json: { pow }, headers });
export const requestSponsor = (walletAddress, pow, headers) => request('POST', '/sponsor', { json: { wallet_address: walletAddress, pow }, headers });

// P1: kept files and SealLog receipts (contracts of §6.3 "P1 endpoints" and brand P-8)
export const listMyItems = (cursor, headers) => request('GET', `/me/items?limit=50${cursor ? `&cursor=${enc(cursor)}` : ''}`, { headers });
export const openMyItem = (itemId, headers) => request('POST', `/me/items/${enc(itemId)}/open`, { json: {}, headers });
export const claimItem = (itemId, ownerWrap, headers) => request('POST', `/items/${enc(itemId)}/claim`, { json: { owner_wrap: ownerWrap }, headers });
export const sealProof = (itemId) => request('GET', `/seallog/proof/${enc(itemId)}`);
