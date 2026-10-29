// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Serialization formats the HTTP API and the cache inherited from pydantic.

use chrono::{DateTime, Timelike, Utc};

/// Pydantic's JSON datetime: `2026-01-01T12:00:00Z`, with `.ffffff` only
/// when the microseconds are non-zero.
pub fn format_datetime(dt: &DateTime<Utc>) -> String {
    let micros = dt.nanosecond() / 1000 % 1_000_000;
    if micros == 0 {
        dt.format("%Y-%m-%dT%H:%M:%SZ").to_string()
    } else {
        format!("{}.{:06}Z", dt.format("%Y-%m-%dT%H:%M:%S"), micros)
    }
}

/// Parse what `format_datetime` (or any RFC 3339 producer) wrote.
pub fn parse_datetime(raw: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(raw)
        .map(|d| d.with_timezone(&Utc))
        .ok()
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.f")
                .ok()
                .map(|n| n.and_utc())
        })
}

pub mod py_datetime {
    use chrono::{DateTime, Utc};
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(dt: &DateTime<Utc>, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&super::format_datetime(dt))
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<DateTime<Utc>, D::Error> {
        let raw = String::deserialize(d)?;
        super::parse_datetime(&raw).ok_or_else(|| serde::de::Error::custom(format!("invalid datetime '{raw}'")))
    }
}

/// Truncate to microseconds, the precision Postgres stores.
pub fn now_micros() -> DateTime<Utc> {
    let now = Utc::now();
    let nanos = now.nanosecond() / 1000 * 1000;
    now.with_nanosecond(nanos).unwrap_or(now)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn pydantic_layout() {
        let d = Utc.with_ymd_and_hms(2026, 1, 1, 12, 0, 0).unwrap();
        assert_eq!(format_datetime(&d), "2026-01-01T12:00:00Z");
        let d = d.with_nanosecond(120_000_000).unwrap();
        assert_eq!(format_datetime(&d), "2026-01-01T12:00:00.120000Z");
        assert_eq!(parse_datetime("2026-01-01T12:00:00.120000Z"), Some(d));
    }
}
