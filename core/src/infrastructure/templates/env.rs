// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The Jinja environment every template adapter renders with. Templates are
//! embedded at compile time; the options mirror the Python environment:
//! `trim_blocks`, `lstrip_blocks`, no autoescaping for `.jinja` files and
//! the final newline dropped.

use std::sync::LazyLock;

use minijinja::{AutoEscape, Environment};

const TEMPLATES: &[(&str, &str)] = &[
    (
        "base_layouts/core/compliance_checker.jinja",
        include_str!("../../../resources/templates/base_layouts/core/compliance_checker.jinja"),
    ),
    (
        "base_layouts/core/filter_drift_exceptions.jinja",
        include_str!("../../../resources/templates/base_layouts/core/filter_drift_exceptions.jinja"),
    ),
    (
        "base_layouts/core/filter_reconciliation.jinja",
        include_str!("../../../resources/templates/base_layouts/core/filter_reconciliation.jinja"),
    ),
    (
        "base_layouts/core/iac_generator.jinja",
        include_str!("../../../resources/templates/base_layouts/core/iac_generator.jinja"),
    ),
    (
        "base_layouts/core/import_addresses.jinja",
        include_str!("../../../resources/templates/base_layouts/core/import_addresses.jinja"),
    ),
    (
        "base_layouts/core/import_filter.jinja",
        include_str!("../../../resources/templates/base_layouts/core/import_filter.jinja"),
    ),
    (
        "base_layouts/core/pr_generator.jinja",
        include_str!("../../../resources/templates/base_layouts/core/pr_generator.jinja"),
    ),
    (
        "base_layouts/core/prompt_compositor.jinja",
        include_str!("../../../resources/templates/base_layouts/core/prompt_compositor.jinja"),
    ),
    (
        "base_layouts/core/report_generator.jinja",
        include_str!("../../../resources/templates/base_layouts/core/report_generator.jinja"),
    ),
    (
        "base_layouts/core/requests_filter.jinja",
        include_str!("../../../resources/templates/base_layouts/core/requests_filter.jinja"),
    ),
    (
        "base_layouts/core/target_drift_generator.jinja",
        include_str!("../../../resources/templates/base_layouts/core/target_drift_generator.jinja"),
    ),
    (
        "base_layouts/core/target_session_generator.jinja",
        include_str!("../../../resources/templates/base_layouts/core/target_session_generator.jinja"),
    ),
    (
        "base_layouts/core/task_splitter.jinja",
        include_str!("../../../resources/templates/base_layouts/core/task_splitter.jinja"),
    ),
    (
        "base_layouts/messages/chat_reply.jinja",
        include_str!("../../../resources/templates/base_layouts/messages/chat_reply.jinja"),
    ),
    (
        "base_layouts/messages/joker.jinja",
        include_str!("../../../resources/templates/base_layouts/messages/joker.jinja"),
    ),
    (
        "base_layouts/messages/search_selector.jinja",
        include_str!("../../../resources/templates/base_layouts/messages/search_selector.jinja"),
    ),
    (
        "base_layouts/messages/search_summarizer.jinja",
        include_str!("../../../resources/templates/base_layouts/messages/search_summarizer.jinja"),
    ),
    (
        "base_layouts/messages/status_update.jinja",
        include_str!("../../../resources/templates/base_layouts/messages/status_update.jinja"),
    ),
];

pub static JINJA: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.set_trim_blocks(true);
    env.set_lstrip_blocks(true);
    env.set_keep_trailing_newline(false);
    env.set_auto_escape_callback(|_| AutoEscape::None);
    env.set_unknown_method_callback(minijinja_contrib::pycompat::unknown_method_callback);
    for (name, source) in TEMPLATES {
        env.add_template(name, source).expect("embedded template parses");
    }
    env
});
