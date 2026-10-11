// SPDX-License-Identifier: MIT
//! SealLog: tamper-evident storage receipts for mutis.
//!
//! Component state on the Ootle is public, so the log holds only checkpoints of
//! `(epoch, merkle_root, leaf_count)`. Each root covers an RFC 9162 Merkle tree (SHA-256) of
//! leaf hashes: one per stored ciphertext, one per file that leaves, and padding. File names,
//! sizes, keys, links and owners never reach the chain.
//!
//! This is tamper evidence, not privacy: it shows what we committed to and when, and that
//! checkpoints are only ever added. See README.md for what it does not prove.
use tari_template_lib::prelude::*;

/// Every tree size is a multiple of this, so the public count moves only in whole steps.
const PAD_STEP: u64 = 64;

/// How many of the newest checkpoints the state keeps. Every call decodes the whole state, so a
/// bounded state keeps the fee flat and the WASM memory use fixed. Every root also stays in its
/// `root` event, which is part of a transaction receipt that no transaction can change.
const KEPT: usize = 64;

#[template]
mod seal_log {
    use super::*;

    pub struct SealLog {
        /// The newest checkpoints, oldest first: (epoch, merkle_root, leaf_count).
        checkpoints: Vec<(u64, Hash32, u64)>,
        /// The index of `checkpoints[0]` among all checkpoints ever appended.
        first_index: u64,
    }

    impl SealLog {
        /// Creates an empty log. Only the key that signs this transaction may append. The log has
        /// no owner, so nobody, that key included, can change its access rules or the code
        /// behind it. Anyone may read or notarize.
        pub fn new(alloc: ComponentAddressAllocation) -> Component<Self> {
            let writer = CallerContext::transaction_signer_public_key();
            Component::new(Self {
                checkpoints: Vec::new(),
                first_index: 0,
            })
            .with_address_allocation(alloc)
            .with_access_rules(
                ComponentAccessRules::new()
                    .method("append_root", rule!(public_key(writer)))
                    .method("notarize", rule!(allow_all))
                    .method("latest", rule!(allow_all))
                    .method("checkpoint_count", rule!(allow_all))
                    .method("get", rule!(allow_all))
                    .default(rule!(deny_all)),
            )
            // The engine lets only an owner change a component's rules or swap its template.
            .with_owner_rule(OwnerRule::None)
            .create()
        }

        /// Writer only. Records a Merkle root and its tree size at the current epoch and emits a
        /// `root` event. The tree size must be a multiple of 64 and larger than the last one.
        pub fn append_root(&mut self, root: Hash32, leaf_count: u64) {
            assert!(
                leaf_count.is_multiple_of(PAD_STEP),
                "leaf_count must be a multiple of 64"
            );
            let last = self.checkpoints.last().map_or(0, |&(_, _, count)| count);
            assert!(leaf_count > last, "append-only: leaf_count must grow");
            if self.checkpoints.len() == KEPT {
                self.checkpoints.remove(0);
                self.first_index += 1;
            }
            let epoch = Consensus::current_epoch();
            self.checkpoints.push((epoch, root, leaf_count));
            emit_event(
                "root",
                metadata![
                    "index" => (self.checkpoint_count() - 1).to_string(),
                    "root" => root.to_string(),
                    "leaf_count" => leaf_count.to_string(),
                    "epoch" => epoch.to_string(),
                ],
            );
        }

        /// Anyone. Timestamps an opaque 32-byte commitment with a `notarize` event. Writes no
        /// state. The event names the transaction's signer, which the transaction makes public
        /// anyway, so a reader can tell which key sent it.
        pub fn notarize(&self, commitment: Hash32) {
            emit_event(
                "notarize",
                metadata![
                    "commitment" => commitment.to_string(),
                    "signer" => CallerContext::transaction_signer_public_key().to_string(),
                    "epoch" => Consensus::current_epoch().to_string(),
                ],
            );
        }

        /// The newest checkpoint, if any.
        pub fn latest(&self) -> Option<(u64, Hash32, u64)> {
            self.checkpoints.last().cloned()
        }

        /// Checkpoint `index` (0 = the first ever appended). `None` past the end, and for the
        /// older checkpoints the state no longer keeps; their `root` events still carry them.
        pub fn get(&self, index: u64) -> Option<(u64, Hash32, u64)> {
            let offset = index.checked_sub(self.first_index)?;
            // `as usize` would truncate on wasm32 and alias 2^32 to an earlier checkpoint.
            self.checkpoints.get(usize::try_from(offset).ok()?).cloned()
        }

        /// How many checkpoints have ever been appended.
        pub fn checkpoint_count(&self) -> u64 {
            self.first_index + self.checkpoints.len() as u64
        }
    }
}
