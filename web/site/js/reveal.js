// SPDX-License-Identifier: MIT
// "Yesterday's key": once a test file is a day old its key is published, and this opens it in the
// visitor's browser with the same format code the viewer uses (/app/lib). Loaded on demand.
import { getBytes } from './canary.js';

const T = {
  first: 'First line',
  rest: (n) => `(then ${n} random characters of padding)`,
  fail: 'It didn\'t open: the key or the bytes have changed.',
};

// -> true when it opened; otherwise the caller lets the visitor try again.
export async function openRevealed(box, entry) {
  const out = box.querySelector('[data-reveal-out]');
  try {
    const text = await decrypt(entry);
    const firstLine = text.split('\n', 1)[0];
    out.textContent = `${T.first}: ${firstLine}\n${T.rest(text.length - firstLine.length - 1)}`;
    box.querySelector('[data-reveal-key-value]').textContent = entry.fk;
    box.querySelector('[data-reveal-key]').hidden = false;
    return true;
  } catch {
    out.textContent = T.fail;
    return false;
  } finally {
    out.hidden = false;
  }
}

async function decrypt(entry) {
  const [{ b64uDecode }, { sha256 }, format] = await Promise.all([
    import('/app/lib/b64.js'), import('/app/lib/crypto.js'), import('/app/lib/format.js')]);
  const header = b64uDecode(entry.header);
  const { chunkCount, salt } = format.parseHeader(header);
  const headerHash = await sha256(header);
  const { contentKey, metaKey } = await format.deriveItemKeys(b64uDecode(entry.fk), salt);
  const meta = await format.decryptMeta(metaKey, headerHash, b64uDecode(entry.meta_ct));
  const stored = await getBytes(entry.raw);
  const parts = await format.decryptBlob({
    contentKey, headerHash, chunkCount, sizeStored: entry.size_stored, plainLength: meta.size,
    readChunk: async (i, start, end) => stored.subarray(start, end),
  });
  return new TextDecoder().decode(await new Blob(parts).arrayBuffer());
}
