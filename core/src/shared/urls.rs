// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

use crate::shared::config::urlsplit;
use crate::shared::pyfmt;

/// True when `uri` is an `https://` URL with a host.
pub fn is_https_url(uri: &str) -> bool {
    let parsed = urlsplit(pyfmt::strip(uri));
    parsed.scheme == "https" && parsed.hostname.is_some()
}

/// The URL with its userinfo and port dropped, safe to log:
/// `urlunparse(parsed._replace(netloc=parsed.hostname or ""))`.
pub fn safe_uri(uri: &str) -> String {
    let p = urlsplit(uri);
    let mut out = String::new();
    if !p.scheme.is_empty() {
        out.push_str(&p.scheme);
        out.push(':');
    }
    let netloc = p.hostname.clone().unwrap_or_default();
    if !netloc.is_empty() || p.scheme == "https" || p.scheme == "http" || uri.contains("//") {
        out.push_str("//");
        out.push_str(&netloc);
    }
    out.push_str(&p.path);
    if !p.query.is_empty() {
        out.push('?');
        out.push_str(&p.query);
    }
    if !p.fragment.is_empty() {
        out.push('#');
        out.push_str(&p.fragment);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_detection() {
        assert!(is_https_url("https://github.com/a/b"));
        assert!(is_https_url("  HTTPS://github.com/a/b "));
        assert!(!is_https_url("http://github.com/a/b"));
        assert!(!is_https_url("https:///a/b"));
        assert!(!is_https_url("git@github.com:a/b"));
    }

    #[test]
    fn safe_uri_drops_credentials() {
        assert_eq!(safe_uri("https://u:p@github.com/a/b.git"), "https://github.com/a/b.git");
        assert_eq!(safe_uri("https://github.com/a/b"), "https://github.com/a/b");
    }
}
