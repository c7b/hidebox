// SPDX-License-Identifier: MIT
//! SealLog behaviour, run as compiled WASM in the Ootle engine (tari_engine 0.45 through
//! tari_template_test_tooling).

use std::{env, fs, path::Path};

use serde_json::{Value, json};
use tari_template_lib::prelude::{ComponentAddress, Hash32, NonFungibleAddress};
use tari_template_test_tooling::{
    TemplateTest,
    byte_type::ToByteType,
    crypto::{RistrettoPublicKey, RistrettoSecretKey},
    engine_types::{
        commit_result::{ExecuteResult, ExecutionFailureCode, RejectReason},
        substate::Substate,
        virtual_substate::{VirtualSubstate, VirtualSubstateId},
    },
    transaction::args,
};

type Checkpoint = (u64, Hash32, u64);

const PAD_STEP: u64 = 64;
const KEPT: u64 = 64;
const SHARED_VECTOR: &str = include_str!("vectors/seallog-v1.json");

/// One SealLog and the key that created it, the only key that may append.
struct Log {
    test: TemplateTest,
    address: ComponentAddress,
    writer_key: RistrettoSecretKey,
    writer_proof: NonFungibleAddress,
}

impl Log {
    /// A log created by the harness's default key.
    fn new() -> Self {
        let test = TemplateTest::my_crate();
        let (writer_proof, writer_key) = test.get_test_proof_and_secret_key();
        Self::create(test, writer_key, writer_proof)
    }

    fn create(
        mut test: TemplateTest,
        writer_key: RistrettoSecretKey,
        writer_proof: NonFungibleAddress,
    ) -> Self {
        let template = test.get_template_address("SealLog");
        let result = test.execute_expect_success(
            test.transaction()
                .allocate_component_address("log")
                .call_function(template, "new", args![Workspace("log")])
                .build_and_seal(&writer_key),
            vec![writer_proof.clone()],
        );
        let address = result
            .finalize
            .result
            .accept()
            .unwrap()
            .up_iter()
            .find_map(|(id, _)| id.as_component_address())
            .expect("component created");
        Self {
            test,
            address,
            writer_key,
            writer_proof,
        }
    }

    fn set_epoch(&mut self, epoch: u64) {
        self.test.set_virtual_substate(
            VirtualSubstateId::CurrentEpoch,
            VirtualSubstate::CurrentEpoch(epoch),
        );
    }

    fn append(&mut self, root: Hash32, leaf_count: u64) -> ExecuteResult {
        self.append_many(&[(root, leaf_count)])
    }

    /// Several appends in one transaction, signed by the writer.
    fn append_many(&mut self, roots: &[(Hash32, u64)]) -> ExecuteResult {
        let mut tx = self.test.transaction();
        for &(root, leaf_count) in roots {
            tx = tx.call_method(self.address, "append_root", args![root, leaf_count]);
        }
        let tx = tx.build_and_seal(&self.writer_key);
        self.test
            .execute_expect_success(tx, vec![self.writer_proof.clone()])
    }

    fn append_rejected(&mut self, root: Hash32, leaf_count: u64) -> RejectReason {
        let tx = self
            .test
            .transaction()
            .call_method(self.address, "append_root", args![root, leaf_count])
            .build_and_seal(&self.writer_key);
        self.test
            .execute_expect_failure(tx, vec![self.writer_proof.clone()])
    }

    /// Appends `nth(i)` until the log holds `target` (more than it holds now) checkpoints, 100
    /// per transaction (each append emits two events, and a transaction may emit 256). Returns
    /// the last result.
    fn fill_to(&mut self, target: u64) -> ExecuteResult {
        let mut next = self.count();
        loop {
            let end = target.min(next + 100);
            let roots: Vec<_> = (next..end)
                .map(|i| {
                    let (_, root, leaf_count) = nth(i);
                    (root, leaf_count)
                })
                .collect();
            let result = self.append_many(&roots);
            if end == target {
                return result;
            }
            next = end;
        }
    }

    fn latest(&mut self) -> Option<Checkpoint> {
        self.test
            .call_method(self.address, "latest", args![], vec![])
    }

    fn get(&mut self, index: u64) -> Option<Checkpoint> {
        self.test
            .call_method(self.address, "get", args![index], vec![])
    }

    fn count(&mut self) -> u64 {
        self.test
            .call_method(self.address, "checkpoint_count", args![], vec![])
    }

    /// A fresh key that didn't create the log, with the proof its signature carries.
    fn stranger(&mut self) -> (NonFungibleAddress, RistrettoPublicKey, RistrettoSecretKey) {
        self.test.create_owner_proof()
    }
}

fn h(byte: u8) -> Hash32 {
    Hash32::from_array([byte; 32])
}

/// Checkpoint `i` of a filled log, as appended at epoch 0: a root naming `i` and 64 * (i + 1).
fn nth(i: u64) -> Checkpoint {
    let mut root = [0; 32];
    root[..8].copy_from_slice(&i.to_be_bytes());
    (0, Hash32::from_array(root), PAD_STEP * (i + 1))
}

/// The `SealLog.*` events of a transaction as (topic, [(key, value)]) with keys sorted.
fn template_events(result: &ExecuteResult) -> Vec<(String, Vec<(String, String)>)> {
    result
        .finalize
        .events
        .iter()
        .filter(|event| event.topic().starts_with("SealLog."))
        .map(|event| {
            let payload = event.payload();
            let fields = payload
                .iter()
                .map(|(key, _)| {
                    (
                        key.clone(),
                        payload.get_str(key).expect("string value").to_owned(),
                    )
                })
                .collect();
            (event.topic().to_owned(), fields)
        })
        .collect()
}

fn fields(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
    pairs
        .iter()
        .map(|&(key, value)| (key.to_owned(), value.to_owned()))
        .collect()
}

/// The log's component substate as `result` wrote it.
fn written_component(result: &ExecuteResult, log: ComponentAddress) -> &Substate {
    result
        .finalize
        .result
        .accept()
        .unwrap()
        .up_iter()
        .find(|(id, _)| id.as_component_address() == Some(log))
        .map(|(_, substate)| substate)
        .expect("the log was written")
}

fn failure(reason: &RejectReason) -> (&ExecutionFailureCode, &str) {
    match reason {
        RejectReason::ExecutionFailure { code, message } => (code, message),
        other => panic!("expected an execution failure, got {other}"),
    }
}

fn assert_template_error(reason: &RejectReason, expected: &str) {
    let (code, message) = failure(reason);
    assert_eq!(code, &ExecutionFailureCode::TemplateError);
    assert!(message.contains(expected), "{message}");
}

/// (tree_size, root) of each checkpoint in the shared Merkle vector.
fn vector_checkpoints() -> Vec<(u64, Hash32)> {
    let vector: Value = serde_json::from_str(SHARED_VECTOR).unwrap();
    vector["checkpoints"]
        .as_array()
        .unwrap()
        .iter()
        .map(|checkpoint| {
            let size = checkpoint["tree_size"].as_u64().unwrap();
            let root = Hash32::from_hex(checkpoint["root"].as_str().unwrap()).unwrap();
            (size, root)
        })
        .collect()
}

#[test]
fn the_writer_appends_and_anyone_reads() {
    let mut log = Log::new();
    log.append(h(7), 64);
    log.append(h(8), 128);

    let (proof, _, key) = log.stranger();
    let result = log.test.execute_expect_success(
        log.test
            .transaction()
            .call_method(log.address, "latest", args![])
            .call_method(log.address, "get", args![0u64])
            .call_method(log.address, "checkpoint_count", args![])
            .build_and_seal(&key),
        vec![proof],
    );
    let outputs = &result.finalize.execution_results;
    let latest: Option<Checkpoint> = outputs[0].decode().unwrap();
    let first: Option<Checkpoint> = outputs[1].decode().unwrap();
    let count: u64 = outputs[2].decode().unwrap();
    assert_eq!(latest, Some((0, h(8), 128)));
    assert_eq!(first, Some((0, h(7), 64)));
    assert_eq!(count, 2);
}

#[test]
fn only_the_creating_key_can_append() {
    let mut log = Log::new();
    log.append(h(1), 64);
    let (proof, _, key) = log.stranger();

    let reason = log.test.execute_expect_failure(
        log.test
            .transaction()
            .call_method(log.address, "append_root", args![h(2), 128u64])
            .build_and_seal(&key),
        vec![proof],
    );

    assert_eq!(failure(&reason).0, &ExecutionFailureCode::AccessDenied);
    assert_eq!(log.count(), 1);
    assert_eq!(log.latest(), Some((0, h(1), 64)));
}

/// The log has no owner, so the engine refuses to point it at other code, even for the key that
/// created it. With an owner, one transaction could swap in a template that rewrites the state
/// and swap SealLog back. Swapping to SealLog itself is enough to show the refusal: the engine
/// checks ownership before it looks at the new template.
#[test]
fn nobody_can_swap_the_code_under_the_log() {
    let mut log = Log::new();
    log.append(h(1), 64);
    let template = log.test.get_template_address("SealLog");

    let reason = log.test.execute_expect_failure(
        log.test
            .transaction()
            .update_component_template(log.address, template)
            .build_and_seal(&log.writer_key),
        vec![log.writer_proof.clone()],
    );

    let (code, message) = failure(&reason);
    assert_eq!(code, &ExecutionFailureCode::AccessDenied);
    assert!(
        message.contains("native.component.update_template"),
        "{message}"
    );
    assert_eq!(log.latest(), Some((0, h(1), 64)));
}

#[test]
fn leaf_count_must_grow() {
    let mut log = Log::new();
    log.append(h(1), 128);

    assert_template_error(
        &log.append_rejected(h(2), 128),
        "append-only: leaf_count must grow",
    );
    assert_template_error(
        &log.append_rejected(h(2), 64),
        "append-only: leaf_count must grow",
    );
    assert_eq!(log.count(), 1);
    assert_eq!(log.latest(), Some((0, h(1), 128)));
}

/// 10-spec §11.3: the worker pads every tree to the next multiple of 64 above its size, so the
/// public count moves only in steps of 64. The template refuses any other count.
#[test]
fn leaf_count_must_be_a_multiple_of_64() {
    let mut log = Log::new();

    assert_template_error(
        &log.append_rejected(h(1), 0),
        "append-only: leaf_count must grow",
    );
    assert_template_error(
        &log.append_rejected(h(1), 65),
        "leaf_count must be a multiple of 64",
    );
    log.append(h(1), 64);
    assert_template_error(
        &log.append_rejected(h(2), 100),
        "leaf_count must be a multiple of 64",
    );
    log.append(h(2), 192);

    assert_eq!(log.count(), 2);
    assert_eq!(log.latest(), Some((0, h(2), 192)));
}

#[test]
fn checkpoints_keep_epoch_root_and_count_in_order() {
    let mut log = Log::new();
    let expected: Vec<Checkpoint> = (1..=5u8)
        .map(|i| (12_126 + u64::from(i), h(i), PAD_STEP * u64::from(i)))
        .collect();

    for &(epoch, root, leaf_count) in &expected {
        log.set_epoch(epoch);
        log.append(root, leaf_count);
    }

    assert_eq!(log.count(), 5);
    for (index, checkpoint) in expected.iter().enumerate() {
        assert_eq!(log.get(index as u64).as_ref(), Some(checkpoint));
    }
    assert_eq!(log.latest().as_ref(), expected.last());
}

#[test]
fn an_empty_log_has_no_checkpoints() {
    let mut log = Log::new();

    assert_eq!(log.count(), 0);
    assert_eq!(log.latest(), None);
    assert_eq!(log.get(0), None);
}

#[test]
fn get_past_the_end_is_none() {
    let mut log = Log::new();
    log.append(h(1), 64);
    log.append(h(2), 128);

    assert_eq!(log.get(1), Some((0, h(2), 128)));
    assert_eq!(log.get(2), None);
    // 2^32 truncates to 0 on wasm32 if the index is cast with `as`.
    assert_eq!(log.get(1 << 32), None);
    assert_eq!(log.get(u64::MAX), None);
}

#[test]
fn append_root_emits_index_root_count_and_epoch() {
    let mut log = Log::new();
    log.append(h(1), 64);
    log.set_epoch(12_127);
    let root_hex = "511494118b292d471dd6141cb29ddeae9de2cae84a4cddf69e5a2909afb00b74";

    let result = log.append(Hash32::from_hex(root_hex).unwrap(), 128);

    assert_eq!(
        template_events(&result),
        vec![(
            "SealLog.root".to_owned(),
            fields(&[
                ("epoch", "12127"),
                ("index", "1"),
                ("leaf_count", "128"),
                ("root", root_hex),
            ]),
        )]
    );
}

#[test]
fn anyone_can_notarize_and_the_event_names_the_signer() {
    let mut log = Log::new();
    log.append(h(1), 64);
    log.set_epoch(12_200);
    let (proof, public_key, key) = log.stranger();
    let signer = public_key.to_byte_type().to_string();

    let result = log.test.execute_expect_success(
        log.test
            .transaction()
            .call_method(log.address, "notarize", args![h(0xcd)])
            .build_and_seal(&key),
        vec![proof],
    );

    assert_eq!(
        template_events(&result),
        vec![(
            "SealLog.notarize".to_owned(),
            fields(&[
                ("commitment", &"cd".repeat(32)),
                ("epoch", "12200"),
                ("signer", &signer),
            ]),
        )]
    );
    let diff = result.finalize.result.accept().unwrap();
    assert!(
        diff.up_iter()
            .all(|(id, _)| id.as_component_address() != Some(log.address)),
        "notarize must not write the component"
    );
    assert_eq!(log.count(), 1);
}

/// The state keeps the newest 64 checkpoints, so every call costs the same however long the log
/// gets; `get` answers `None` for the older ones, whose `root` events still carry them.
#[test]
fn the_state_keeps_the_newest_64_checkpoints() {
    let mut log = Log::new();
    let first = log.fill_to(100);
    let at_100 = written_component(&first, log.address).to_bytes().len();
    let last = log.fill_to(300);
    let at_300 = written_component(&last, log.address).to_bytes().len();

    assert_eq!(log.count(), 300);
    assert_eq!(log.get(300 - KEPT - 1), None);
    assert_eq!(log.get(300 - KEPT), Some(nth(300 - KEPT)));
    assert_eq!(log.get(0), None);
    assert_eq!(log.latest(), Some(nth(299)));
    assert_eq!(at_300, at_100, "the state must not grow");
    let (_, fields) = template_events(&last).pop().unwrap();
    assert!(fields.contains(&("index".to_owned(), "299".to_owned())));
}

/// The shared Merkle vector (tests/vectors/seallog-v1.json, also read by the server and the app)
/// follows the padding rule: a stored file, its exit, then an idle window, at 64, 128 and 192.
/// Its roots go in as they are and come back byte for byte, in state and in the event.
#[test]
fn the_shared_vector_checkpoints_are_valid_appends() {
    let mut log = Log::new();
    let checkpoints = vector_checkpoints();
    assert_eq!(checkpoints.len(), 3);

    for (epoch, &(tree_size, root)) in (12_127..).zip(&checkpoints) {
        log.set_epoch(epoch);
        let result = log.append(root, tree_size);
        let (_, fields) = &template_events(&result)[0];
        assert!(fields.contains(&("root".to_owned(), root.to_string())));
        assert_eq!(log.latest(), Some((epoch, root, tree_size)));
    }
}

/// A log holding the shared vector's first two checkpoints (epochs 12127 and 12128), and its
/// component substate as an indexer serves it.
fn log_with_two_checkpoints() -> (Log, Value) {
    let mut log = Log::new();
    let checkpoints = vector_checkpoints();
    log.set_epoch(12_127);
    log.append(checkpoints[0].1, checkpoints[0].0);
    log.set_epoch(12_128);
    let result = log.append(checkpoints[1].1, checkpoints[1].0);
    let substate = written_component(&result, log.address).substate_value();
    let json = serde_json::to_value(substate).unwrap();
    (log, json)
}

/// What `/verify` checks before it trusts a root: the log has no owner, and only our key may
/// append. The rule names the key as the public-identity badge whose id is the key's bytes.
#[test]
fn the_header_shows_no_owner_and_names_the_writer() {
    let (log, substate) = log_with_two_checkpoints();
    let header = &substate["Component"]["header"];

    assert_eq!(header["owner_rule"], "None");
    let badge = header
        .pointer(
            "/access_rules/method_access/append_root/Restricted/Require/Require/NonFungibleAddress",
        )
        .expect("append_root requires one badge");
    assert_eq!(
        badge["resource_address"],
        format!("resource_01{}", "0".repeat(62))
    );
    assert_eq!(
        badge["id"]["U256"],
        log.test.to_public_key_bytes().to_string()
    );
}

/// The component substate as an indexer serves it: the layout `/verify` parses.
/// `SEALLOG_BLESS=1 cargo test` rewrites tests/vectors/seallog-state-v1.json after an intended
/// change; tell the app builder when it changes.
#[test]
fn the_component_state_matches_the_state_vector() {
    let (_, substate) = log_with_two_checkpoints();
    let vector = json!({
        "about": "SealLog component substate after two appends (the roots of seallog-v1.json at \
                  epochs 12127 and 12128), as an Ootle indexer returns it in the `substate` field \
                  of GET /substates/<component>. Written by tests/seal_log.rs; do not edit. \
                  template_address, entity_id and the key in the append_root rule come from the \
                  test engine; on Esmeralda they are the published template's address, the log's \
                  entity id and our writer key.",
        "substate": substate,
    });
    let text = serde_json::to_string_pretty(&vector).unwrap() + "\n";
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors/seallog-state-v1.json");
    if env::var_os("SEALLOG_BLESS").is_some() {
        fs::write(&path, &text).unwrap();
    }
    assert_eq!(
        fs::read_to_string(&path).unwrap_or_default(),
        text,
        "the component state changed: check the app's SealLog parser, then rerun with SEALLOG_BLESS=1"
    );
}

/// Prints fee, WASM points and state size of `append_root` as the log grows, for the README.
/// It asserts nothing, so it is ignored by default: `../check.sh --costs` runs it. Fees use the
/// test engine's fee table; compare the first line with the live figure (1,837 µT).
#[test]
#[ignore = "measurement, not a check: run ../check.sh --costs"]
fn costs_as_the_log_grows() {
    let mut test = TemplateTest::my_crate();
    let (account, proof, key) = test.create_funded_account();
    let mut log = Log::create(test, key, proof);
    let max_fee = 100_000_000u64;

    for before in [0, 1, 63, 64, 300, 1_000] {
        if log.count() < before {
            log.fill_to(before);
        }
        log.test.enable_fees();
        let (_, root, leaf_count) = nth(before);
        let tx = log
            .test
            .transaction()
            .pay_fee_from_component(account, max_fee)
            .call_method(log.address, "append_root", args![root, leaf_count])
            .build_and_seal(&log.writer_key);
        let result = log
            .test
            .execute_expect_success(tx, vec![log.writer_proof.clone()]);
        log.test.disable_fees();
        println!(
            "COST append_root after {before} checkpoints: {} uT, {} WASM points, component {} bytes",
            result.finalize.fee_receipt.total_fees_charged(),
            log.test.last_execution_points().wasm,
            written_component(&result, log.address).to_bytes().len(),
        );
    }

    let (stranger_account, stranger_proof, stranger_key) = log.test.create_funded_account();
    let count = log.count();
    log.test.enable_fees();
    let result = log.test.execute_expect_success(
        log.test
            .transaction()
            .pay_fee_from_component(stranger_account, max_fee)
            .call_method(log.address, "notarize", args![h(2)])
            .build_and_seal(&stranger_key),
        vec![stranger_proof],
    );
    println!(
        "COST notarize on a log of {count} checkpoints: {} uT, {} WASM points",
        result.finalize.fee_receipt.total_fees_charged(),
        log.test.last_execution_points().wasm,
    );
}
