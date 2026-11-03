/* tslint:disable */
/* eslint-disable */

/**
 * Decode an `Event` as the indexer serves it (its CBOR encoding, base64) → JSON string.
 */
export function decodeEvent(encoded: string): string;

/**
 * Decode an `ExecuteResult` as the indexer serves it (its CBOR encoding, base64) → JSON string.
 */
export function decodeExecuteResult(encoded: string): string;

/**
 * Decode a `Resource` as the indexer serves it (its CBOR encoding, base64) → JSON string.
 */
export function decodeResource(encoded: string): string;

/**
 * Decode a `SubstateValue` as the indexer serves it (its CBOR encoding, base64) → JSON string.
 */
export function decodeSubstateValue(encoded: string): string;

/**
 * Decode a `TransactionReceipt` as the indexer serves it (its CBOR encoding, base64) → JSON string.
 */
export function decodeTransactionReceipt(encoded: string): string;

/**
 * Decode a `Utxo` as the indexer serves it (its CBOR encoding, base64) → JSON string.
 */
export function decodeUtxo(encoded: string): string;
