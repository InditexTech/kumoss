// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

pub mod cli;
pub mod credentials;
pub mod fs;
pub mod git;
pub mod iac_root;
pub mod providers;
pub mod workspace;

/// The `repr()` of the OSError Python would have raised for `e`, e.g.
/// `IsADirectoryError(21, 'Is a directory')`.
pub fn oserror_repr(e: &std::io::Error) -> String {
    use std::io::ErrorKind as K;
    let name = match e.kind() {
        K::NotFound => "FileNotFoundError",
        K::PermissionDenied => "PermissionError",
        K::AlreadyExists => "FileExistsError",
        K::IsADirectory => "IsADirectoryError",
        K::NotADirectory => "NotADirectoryError",
        K::TimedOut => "TimeoutError",
        K::ConnectionRefused => "ConnectionRefusedError",
        K::ConnectionReset => "ConnectionResetError",
        K::BrokenPipe => "BrokenPipeError",
        K::Interrupted => "InterruptedError",
        _ => "OSError",
    };
    let text = e.to_string();
    let strerror = text.split(" (os error").next().unwrap_or(&text);
    match e.raw_os_error() {
        Some(code) => format!("{name}({code}, {})", crate::shared::pyfmt::repr_str(strerror)),
        None => format!("{name}({})", crate::shared::pyfmt::repr_str(strerror)),
    }
}
