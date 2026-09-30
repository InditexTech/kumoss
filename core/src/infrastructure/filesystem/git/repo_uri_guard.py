# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""SSRF guard for user-supplied repository URIs.

Every repository URI a caller hands us ends up as an argument to a git
subprocess running inside the core container, on the same network as the
database, Redis, object storage and the sidecars. This module decides which
URIs git may be pointed at:

- `parse_repo_uri` is the syntactic check (no I/O): only `https://`,
  `ssh://` and scp-style `user@host:path` remotes are accepted, so git's
  `file://`, `git://`, `http://`, `ext::` and local-path transports are
  never reachable, and the host must be a plain hostname or IP literal.
- `ensure_repo_uri_allowed` is the network policy: the host must be in
  `git.allowed_hosts` when that list is configured; otherwise every address
  the host resolves to must be publicly routable. It returns the git `-c`
  options that hold the command to that decision: a protocol allowlist and,
  for a hostname checked by address, a pin to the addresses just vetted.
  Without the pin git would resolve the name again on its own, and a
  short-TTL record could answer that second lookup with an internal
  address (DNS rebinding).
"""

import asyncio
import ipaddress
import re
import shlex
import socket
from dataclasses import dataclass
from typing import NoReturn
from urllib.parse import urlsplit

from src.infrastructure.exceptions import InvalidRepoURI
from src.shared.config.system_config import system_config
from src.shared.logger import logging

# Returned for every rejection, whatever the reason, so the response cannot
# be used to tell an unresolvable host from a private one or a closed port.
REJECTED_MESSAGE = (
    "Repository URI is not allowed or the repository is not reachable. "
    "Check the URI and that the repository exists and is accessible."
)

_URL_SCHEMES = frozenset({"https", "ssh"})
_TRANSPORT_ERROR = (
    "repo_uri must use https:// or ssh:// (or the scp-style `user@host:path` form)."
)
_DNS_TIMEOUT_SECONDS = 5
_HTTPS_DEFAULT_PORT = 443

# git-level mirror of the scheme check in `parse_repo_uri`, so a URI that
# reaches git without passing through it still cannot use another transport.
_PROTOCOL_OPTIONS = (
    "-c",
    "protocol.allow=never",
    "-c",
    "protocol.https.allow=always",
    "-c",
    "protocol.ssh.allow=always",
)

# scp-style remote: `[user@]host:path`, where the path must not start with a
# second `:` (that is git's `<transport>::<address>` remote-helper syntax).
_SCP_RE = re.compile(
    r"^(?:(?P<user>[^@/]+)@)?(?P<host>\[[^\]/]+\]|[^:/\[\]@]+):(?P<path>[^:].*)$"
)
_HOSTNAME_RE = re.compile(
    r"^[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?(?:\.[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?)*\.?$"
)

_NUMERIC_LABEL_RE = re.compile(r"^(?:[0-9]+|0x[0-9a-f]*)$")


@dataclass(frozen=True)
class RepoRemote:
    host: str
    port: int | None
    ssh: bool = False


def parse_repo_uri(repo_uri: str) -> RepoRemote:
    """Return the remote host of a supported repository URI.

    Raises ValueError when the URI uses an unsupported transport or its host
    is not a plain hostname or IP literal.
    """
    if not repo_uri or any(c.isspace() or not c.isprintable() for c in repo_uri):
        raise ValueError("repo_uri must be a non-empty URI without whitespace.")

    if "://" in repo_uri:
        parts = urlsplit(repo_uri)
        if parts.scheme.lower() not in _URL_SCHEMES:
            raise ValueError(_TRANSPORT_ERROR)
        user, host = parts.username, parts.hostname
        ssh = parts.scheme.lower() == "ssh"
        try:
            port = parts.port
        except ValueError as e:
            raise ValueError("repo_uri has an invalid port.") from e
        # Port 0 is never a real remote, and it would slip past the address
        # pin, which is keyed on the port git actually connects to.
        if port == 0:
            raise ValueError("repo_uri has an invalid port.")
    else:
        match = _SCP_RE.match(repo_uri)
        if match is None:
            raise ValueError(_TRANSPORT_ERROR)
        user, host, port = match["user"], match["host"].strip("[]").lower(), None
        ssh = True

    # A leading `-` would reach ssh as an option (`-oProxyCommand=...`).
    if user is not None and user.startswith("-"):
        raise ValueError("repo_uri has an invalid username.")
    if not host:
        raise ValueError("repo_uri must name a host.")
    return RepoRemote(host=_normalise_host(host), port=port, ssh=ssh)


def _normalise_host(host: str) -> str:
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(host):
        raise ValueError("repo_uri has an invalid host.")
    # No real TLD is numeric, so a numeric last label means an IPv4 address
    # in a non-canonical spelling (`2130706433`, `0x7f.1`, `0177.0.0.1`)
    # that resolvers and curl may each read differently. Canonical
    # dotted-quad literals were already returned above.
    if _NUMERIC_LABEL_RE.match(host.rstrip(".").rsplit(".", 1)[-1]):
        raise ValueError("repo_uri has an invalid host.")
    return host.rstrip(".")


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def ensure_repo_uri_allowed(repo_uri: str) -> tuple[str, ...]:
    """Reject a repository URI git must not be pointed at.

    Returns the git `-c` options every git command against this URI must
    carry. Raises InvalidRepoURI (HTTP 400) with a generic message; the
    specific reason is only logged.
    """
    try:
        remote = parse_repo_uri(repo_uri)
    except ValueError as e:
        _reject(repo_uri, str(e))

    allowed_hosts = {h.lower().rstrip(".") for h in system_config.git.allowed_hosts}
    if allowed_hosts:
        # The operator vouches for these hosts, internal addresses included.
        if remote.host not in allowed_hosts:
            _reject(repo_uri, f"host {remote.host!r} is not in git.allowed_hosts")
        return _PROTOCOL_OPTIONS

    try:
        addresses = await _resolve(remote)
    except (OSError, TimeoutError) as e:
        _reject(repo_uri, f"host {remote.host!r} did not resolve: {e}")

    blocked = sorted(a for a in addresses if not _is_public(a))
    if not addresses or blocked:
        _reject(repo_uri, f"host {remote.host!r} resolves to non-public {blocked}")
    return _PROTOCOL_OPTIONS + _pin_options(remote, addresses)


def _pin_options(remote: RepoRemote, addresses: set[str]) -> tuple[str, ...]:
    """git options that connect to `addresses` instead of resolving again."""
    if _is_ip_literal(remote.host):
        return ()  # nothing to resolve, so nothing to rebind
    # IPv4 first, then a stable order, so the pinned config is deterministic.
    ordered = sorted(addresses, key=lambda a: (":" in a, a))
    if remote.ssh:
        # ssh takes a single target; HostKeyAlias keeps known_hosts keyed by
        # the name rather than the address. GIT_SSH_COMMAND would override it.
        ssh_command = shlex.join(
            ["ssh", "-o", f"HostName={ordered[0]}", "-o", f"HostKeyAlias={remote.host}"]
        )
        return ("-c", f"core.sshCommand={ssh_command}")
    port = remote.port or _HTTPS_DEFAULT_PORT
    targets = ",".join(f"[{a}]" if ":" in a else a for a in ordered)
    return ("-c", f"http.curloptResolve={remote.host}:{port}:{targets}")


def _is_ip_literal(host: str) -> bool:
    try:
        _ = ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def _resolve(remote: RepoRemote) -> set[str]:
    infos = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(
            remote.host, remote.port, type=socket.SOCK_STREAM
        ),
        timeout=_DNS_TIMEOUT_SECONDS,
    )
    return {str(info[4][0]) for info in infos}


def _reject(repo_uri: str, reason: str) -> NoReturn:
    logging.warning(f"Rejected repo_uri {repo_uri}: {reason}")
    raise InvalidRepoURI(message=REJECTED_MESSAGE, error_code=400)
