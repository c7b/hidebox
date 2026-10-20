// SPDX-License-Identifier: MIT
// The value of a GET substates/{id} answer, through our proxy or straight from an indexer: tari_indexer
// 0.47.0 sends the live version's at `state.up.substate`, earlier indexers at `substate`. A spent version
// the indexer proved (`state.down`) has none, and an answer with a `state` is read from it alone.
// -> {Utxo: …}, {Component: …}, … or null.
const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function substateValue(response) {
  if (!isObject(response)) return null;
  let value = response.substate;
  if ('state' in response) {
    const { state } = response;
    value = isObject(state) && !('down' in state) && isObject(state.up) ? state.up.substate : null;
  }
  return isObject(value) ? value : null;
}
