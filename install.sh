#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0
#
# Installs the kumoss CLI. Re-running replaces the binary (an upgrade) and
# never touches an existing stack:
#
#   curl -fsSL https://raw.githubusercontent.com/InditexTech/kumoss/main/install.sh | bash
#
# Environment:
#   KUMOSS_VERSION       release to install (default: the latest release)
#   KUMOSS_INSTALL_DIR   where the binary goes (default: ~/.local/bin)
#   KUMOSS_RELEASE_BASE  override the release download URL (mirrors, tests)
#
# Never uses sudo and never writes outside the user's home.

set -euo pipefail

REPO="InditexTech/kumoss"
INSTALL_DIR="${KUMOSS_INSTALL_DIR:-${HOME}/.local/bin}"
RELEASE_BASE="${KUMOSS_RELEASE_BASE:-https://github.com/${REPO}/releases}"

say() { printf '%s\n' "$*"; }
die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

# fetch URL DEST: curl, else wget, else the binary itself (which serves the
# same files, for a host behind a proxy only it knows).
fetch() {
	local url="$1" dest="$2"
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL "$url" -o "$dest"
	elif command -v wget >/dev/null 2>&1; then
		wget -q "$url" -O "$dest"
	else
		"$(command -v kumoss)" fetch-release "$url" >"$dest" ||
			die "neither curl nor wget is installed"
	fi
}

# latest_version prints the tag the releases/latest redirect points at. This
# avoids the rate-limited REST API.
latest_version() {
	local url="${RELEASE_BASE}/latest"
	local effective
	if command -v curl >/dev/null 2>&1; then
		effective=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$url")
	elif command -v wget >/dev/null 2>&1; then
		effective=$(wget -q -S -O /dev/null --max-redirect=0 "$url" 2>&1 | grep -i '^ *location:' | tail -n1 | tr -d '\r')
	fi
	case "$effective" in
	*/tag/*) printf '%s\n' "${effective##*/tag/}" ;;
	*) die "could not resolve the latest release from ${url}" ;;
	esac
}

detect_platform() {
	local os arch
	case "$(uname -s)" in
	Linux) os=linux ;;
	Darwin) os=darwin ;;
	MINGW* | MSYS* | CYGWIN*) os=windows ;;
	*) die "unsupported OS: $(uname -s). Linux, macOS and WSL2 are supported." ;;
	esac
	if [ "$os" = windows ]; then
		die "native Windows is not supported; run this inside WSL2"
	fi
	case "$(uname -m)" in
	x86_64 | amd64) arch=amd64 ;;
	aarch64 | arm64) arch=arm64 ;;
	*) die "unsupported architecture: $(uname -m). amd64 and arm64 are supported." ;;
	esac
	printf '%s %s\n' "$os" "$arch"
}

# sha256 FILE prints the file's hash with whichever tool is present.
sha256() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | cut -d' ' -f1
	elif command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" | cut -d' ' -f1
	else
		die "neither sha256sum nor shasum is installed; cannot verify the download"
	fi
}

on_path() {
	case ":${PATH}:" in
	*":${INSTALL_DIR}:"*) return 0 ;;
	*) return 1 ;;
	esac
}

main() {
	read -r os arch <<EOF
$(detect_platform)
EOF

	local version="${KUMOSS_VERSION:-}" tag
	local base
	if [ -z "$version" ]; then
		# The redirect's tag name is already vX.Y.Z; keep it verbatim for the URL.
		tag=$(latest_version)
		base="${RELEASE_BASE}/download/${tag}"
	else
		tag="v${version#v}"
		base="${RELEASE_BASE}/download/${tag}"
	fi
	local archive="kumoss_${version#v}_${os}_${arch}.tar.gz"

	local tmp
	tmp=$(mktemp -d)
	# shellcheck disable=SC2064
	trap "rm -rf '${tmp}'" EXIT

	say "Downloading ${archive}"
	fetch "${base}/${archive}" "${tmp}/${archive}"
	fetch "${base}/checksums.txt" "${tmp}/checksums.txt"

	local want got
	want=$(grep " ${archive}\$" "${tmp}/checksums.txt" | cut -d' ' -f1) ||
		die "${archive} is not listed in checksums.txt"
	[ -n "$want" ] || die "${archive} is not listed in checksums.txt"
	got=$(sha256 "${tmp}/${archive}")
	[ "$got" = "$want" ] || die "checksum mismatch for ${archive}: expected ${want}, got ${got}"

	tar -xzf "${tmp}/${archive}" -C "${tmp}"
	[ -f "${tmp}/kumoss" ] || die "archive does not contain a kumoss binary"

	mkdir -p "$INSTALL_DIR"
	# Same-directory rename, so an upgrade is never a half-written binary.
	mv -f "${tmp}/kumoss" "${INSTALL_DIR}/kumoss"
	chmod 0755 "${INSTALL_DIR}/kumoss"

	say "Installed kumoss ${version#v} to ${INSTALL_DIR}/kumoss"
	if ! on_path; then
		say ""
		say "Add it to your PATH, e.g. for bash:"
		say "  echo 'export PATH=\"${INSTALL_DIR}:\$PATH\"' >> ~/.bashrc"
		say "or for zsh:"
		say "  echo 'export PATH=\"${INSTALL_DIR}:\$PATH\"' >> ~/.zshrc"
	fi

	if [ "$os" = linux ] && grep -qi microsoft /proc/version 2>/dev/null; then
		if ! docker info >/dev/null 2>&1; then
			say ""
			say "warning: docker is not reachable. On WSL2, enable Settings > Resources >"
			say "WSL integration for this distribution in Docker Desktop."
		fi
	fi

	say ""
	say "Next: kumoss init"
}

main "$@"
