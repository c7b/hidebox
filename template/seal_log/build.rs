// SPDX-License-Identifier: MIT
fn main() {
    tari_ootle_template_build::TemplateMetadataBuilder::new()
        .build()
        .expect("failed to build template metadata");
}
