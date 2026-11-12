// SPDX-License-Identifier: MIT
// The value of a GET substates/{id} answer, through our proxy or straight from an indexer: tari_indexer
// 0.47.0 sends the live version's at `state.up.substate`, earlier indexers at `substate`, and 0.48 on send it
// as an `Encoded<SubstateValue>` (base64 CBOR), read with the official decoder. A spent version the indexer
// proved (`state.down`) has none, and an answer with a `state` is read from it alone.
// -> {Utxo: …}, {Component: …}, … or null (a value the decoder refuses included). null alone isn't proof that
// a substate is spent: substateDown() says whether the indexer proved it.
import { decodeSubstateValue } from './ootle.js';

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export async function substateValue(response) {
  if (!isObject(response)) return null;
  let value = response.substate;
  if ('state' in response) {
    const { state } = response;
    value = isObject(state) && !('down' in state) && isObject(state.up) ? state.up.substate : null;
  }
  if (typeof value === 'string') {
    try {
      value = await decodeSubstateValue(value);
    } catch {
      return null;
    }
  }
  return isObject(value) ? value : null;
}

// true only when the indexer proved this version spent (`state.down`). A 404, an answer without a value
// or one the decoder refuses proves nothing: an indexer that hasn't caught up answers the same way.
export function substateDown(response) {
  return isObject(response) && isObject(response.state) && 'down' in response.state;
}
