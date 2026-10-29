// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Colour-coded stdout logging in the core's historical line format:
//! `LEVEL:[module][HH:MM:SS] message`.

use std::fmt;

use tracing::{Event, Level, Subscriber};
use tracing_subscriber::EnvFilter;
use tracing_subscriber::fmt::format::{FormatEvent, FormatFields, Writer};
use tracing_subscriber::fmt::{FmtContext, FormattedFields};
use tracing_subscriber::registry::LookupSpan;

const RED: &str = "\x1b[31m";
const LIGHTBLACK_EX: &str = "\x1b[90m";
const LIGHTRED_EX: &str = "\x1b[91m";
const LIGHTGREEN_EX: &str = "\x1b[92m";
const LIGHTYELLOW_EX: &str = "\x1b[93m";
const LIGHTMAGENTA_EX: &str = "\x1b[95m";
const LIGHTCYAN_EX: &str = "\x1b[96m";
const RESET: &str = "\x1b[0m";

struct StdoutFormatter;

impl<S, N> FormatEvent<S, N> for StdoutFormatter
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
{
    fn format_event(&self, ctx: &FmtContext<'_, S, N>, mut writer: Writer<'_>, event: &Event<'_>) -> fmt::Result {
        let meta = event.metadata();
        let (color, level) = match *meta.level() {
            Level::TRACE | Level::DEBUG => (LIGHTMAGENTA_EX, "DEBUG"),
            Level::INFO => (LIGHTGREEN_EX, "INFO"),
            Level::WARN => (LIGHTYELLOW_EX, "WARNING"),
            Level::ERROR => (LIGHTRED_EX, "ERROR"),
        };
        let module = meta.target().rsplit("::").next().unwrap_or("").to_lowercase();
        let time = chrono::Local::now().format("%H:%M:%S");
        write!(
            writer,
            "{color}{level}:{LIGHTCYAN_EX}[{module}]{LIGHTBLACK_EX}[{time}] {RESET}"
        )?;
        let _ = (RED, &ctx);
        ctx.field_format().format_fields(writer.by_ref(), event)?;
        if let Some(scope) = ctx.event_scope() {
            for span in scope.from_root() {
                if let Some(fields) = span.extensions().get::<FormattedFields<N>>()
                    && !fields.is_empty()
                {
                    write!(writer, " {fields}")?;
                }
            }
        }
        writeln!(writer)
    }
}

/// Install the global subscriber: the core at DEBUG, dependencies at WARN.
pub fn init() {
    let filter = EnvFilter::try_from_env("KUMOSS_LOG")
        .unwrap_or_else(|_| EnvFilter::new("warn,kumoss_core=debug,kumoss_core::access=info"));
    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .event_format(StdoutFormatter)
        .with_writer(std::io::stdout)
        .try_init();
}
