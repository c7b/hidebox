// SPDX-License-Identifier: MIT
//! The mainnet build's substates as an Ootle 0.50 indexer serves them: `Encoded<SubstateValue>`, the base64
//! of the value's CBOR. The readers that don't run the engine are held to these bytes: server/mutis/cbor.py
//! (verify-deploy and template/wasm_check.py load it), and the app's SealLog check through the official
//! ootle-wasm-bor decoder (web/app/tests/receipts.test.js).
//!
//! `SEALLOG_BLESS=1 cargo test` rewrites tests/vectors/seallog-encoded-v2.json after an intended change.

use std::{env, fs, path::Path};

use serde_json::json;
use tari_template_lib::prelude::{ComponentAddress, Hash32};
use tari_template_test_tooling::{
    TemplateTest,
    engine_types::{
        published_template::{PublishedTemplate, TemplateBlob, TemplateName},
        substate::SubstateValue,
        virtual_substate::{VirtualSubstate, VirtualSubstateId},
    },
    transaction::args,
};

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// Standard base64 with padding, as the indexers write an `Encoded` value.
fn base64(bytes: &[u8]) -> String {
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let n = chunk
            .iter()
            .enumerate()
            .fold(0u32, |n, (i, &b)| n | (u32::from(b) << (16 - 8 * i)));
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(char::from(B64[((n >> (18 - 6 * i)) & 63) as usize]));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// A log with the shared vector's first two roots, appended at epochs 12127 and 12128 (as in
/// seal_log.rs), and its component substate value.
fn log_with_two_checkpoints() -> (TemplateTest, SubstateValue) {
    let mut test = TemplateTest::my_crate();
    let (proof, key) = test.get_test_proof_and_secret_key();
    let template = test.get_template_address("SealLog");
    let result = test.execute_expect_success(
        test.transaction()
            .allocate_component_address("log")
            .call_function(template, "new", args![Workspace("log")])
            .build_and_seal(&key),
        vec![proof.clone()],
    );
    let log: ComponentAddress = result
        .finalize
        .result
        .accept()
        .unwrap()
        .up_iter()
        .find_map(|(id, _)| id.as_component_address())
        .expect("component created");
    let roots = [
        (
            12_127u64,
            "511494118b292d471dd6141cb29ddeae9de2cae84a4cddf69e5a2909afb00b74",
            64u64,
        ),
        (
            12_128,
            "f90ac46ceb47cb60adcd2c5456884fc60c1910c068f2e88cf10731f48c983fbd",
            128,
        ),
    ];
    let mut value = None;
    for (epoch, root, leaf_count) in roots {
        test.set_virtual_substate(
            VirtualSubstateId::CurrentEpoch,
            VirtualSubstate::CurrentEpoch(epoch),
        );
        let root = Hash32::from_hex(root).unwrap();
        let result = test.execute_expect_success(
            test.transaction()
                .call_method(log, "append_root", args![root, leaf_count])
                .build_and_seal(&key),
            vec![proof.clone()],
        );
        value = result
            .finalize
            .result
            .accept()
            .unwrap()
            .up_iter()
            .find(|(id, _)| id.as_component_address() == Some(log))
            .map(|(_, substate)| substate.substate_value().clone());
    }
    (test, value.expect("the log was written"))
}

#[test]
fn the_encoded_substates_match_the_vector() {
    let (test, component) = log_with_two_checkpoints();
    // A PublishedTemplate as 0.50 encodes one; a few bytes stand in for the 107 KB binary.
    let template = SubstateValue::Template(PublishedTemplate {
        template_name: TemplateName::new_checked("SealLog").unwrap(),
        author: test.to_public_key_bytes(),
        binary: TemplateBlob::new_checked(b"\0asm\x01\0\0\0".to_vec()).unwrap(),
        at_epoch: 12_951,
        metadata_hash: None,
    });
    let vector = json!({
        "about": "The SealLog component after two appends (as seallog-state-v1.json) and a PublishedTemplate with \
                  an 8-byte stand-in binary, as Encoded<SubstateValue> values: the base64 of their CBOR, which \
                  an Ootle 0.50 indexer serves in `state.up.substate` of GET /substates/<id>. Written by \
                  tests/encoded.rs from tari_engine_types 0.50 at the pinned commit; do not edit. The JSON beside \
                  each is the same value through serde.",
        "component": base64(&component.to_bytes()),
        "component_json": serde_json::to_value(&component).unwrap(),
        "template": base64(&template.to_bytes()),
        "template_json": serde_json::to_value(&template).unwrap(),
    });
    let text = serde_json::to_string_pretty(&vector).unwrap() + "\n";
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/vectors/seallog-encoded-v2.json");
    if env::var_os("SEALLOG_BLESS").is_some() {
        fs::write(&path, &text).unwrap();
    }
    assert_eq!(
        fs::read_to_string(&path).unwrap_or_default(),
        text,
        "the encoded substates changed: check server/mutis/cbor.py and the app's SealLog reader, then rerun \
         with SEALLOG_BLESS=1"
    );
}
