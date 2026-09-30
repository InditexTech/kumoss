# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Server-side SSRF guard for user-supplied repository URIs.

Runs before git ever sees the URI. Only `https://` and SSH (`ssh://`,
`git+ssh://`, `ssh+git://` and scp-style `[user@]host:path`) are accepted;
every other transport — `file://`, `git://`, `http://`, `ext::`, local
paths — is rejected. The host is then resolved and *every* address it
resolves to must be public: loopback, RFC1918, link-local (cloud metadata
at 169.254.169.254 included), CGNAT, ULA, multicast, reserved and
unspecified addresses are rejected, also when smuggled inside an
IPv4-mapped, NAT64, 6to4 or Teredo IPv6 address.

For https the checked addresses are handed back as git config that pins
curl's resolution to them and disables redirects, so neither DNS
rebinding between check and connect nor a redirect to an internal host
can move the request elsewhere. SSH gets no pin: ssh resolves the host
itself and git has no equivalent knob.
"""

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.infrastructure.exceptions import InvalidRepoURI
from src.shared.logger import logging

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_HTTPS_SCHEMES = frozenset({"https"})
_SSH_SCHEMES = frozenset({"ssh", "git+ssh", "ssh+git"})
_DEFAULT_PORTS = {"https": 443, "ssh": 22}
_DNS_TIMEOUT_SECONDS = 5.0

_SCHEME_RE = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://")
# git's scp-like syntax: no slash before the first colon. A path starting
# with ':' is git's `<transport>::<address>` remote-helper syntax (`ext::`).
_SCP_RE = re.compile(
    r"^(?:(?P<user>[^@/:]+)@)?(?P<host>\[[0-9A-Fa-f:.]+\]|[^@/:\[\]]+):(?P<path>[^:].*)$"
)
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")

# Already non-global, so the generic check rejects them; listed so the
# blocklist is auditable. AWS/GCP/Azure/OCI, AWS IPv6, ECS task, Alibaba.
_METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "fd00:ec2::254", "169.254.170.2", "100.100.100.200")
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

_MALFORMED = "Repository URI must be an https:// or ssh:// git URL."
_FORBIDDEN_HOST = "Repository host is not allowed."


@dataclass(frozen=True)
class CheckedRemote:
    """A repository URI that passed the guard, plus what it resolved to."""

    scheme: str  # "https" or "ssh"
    host: str
    port: int
    addresses: tuple[IPAddress, ...]

    @property
    def git_config(self) -> tuple[str, ...]:
        """`key=value` git config that keeps git on the checked addresses."""
        if self.scheme != "https":
            return ()
        config = ["http.followRedirects=false"]
        if not _is_ip_literal(self.host):
            pinned = ",".join(
                f"[{a}]" if a.version == 6 else str(a) for a in self.addresses
            )
            config.append(f"http.curloptResolve={self.host}:{self.port}:{pinned}")
        return tuple(config)

    @property
    def command_options(self) -> list[str]:
        """`-c key=value` pairs for `git <options> <subcommand>`."""
        return [arg for c in self.git_config for arg in ("-c", c)]

    @property
    def clone_options(self) -> list[str]:
        """`--config=key=value` for `git clone`; persisted into the clone's
        own config, so later fetch/push to origin keep the pin."""
        return [f"--config={c}" for c in self.git_config]


async def check_remote(repo_uri: str) -> CheckedRemote:
    """Validate `repo_uri` and resolve its host; raise InvalidRepoURI (400)
    with a generic message on rejection. The reason is logged server-side."""
    scheme, host, port = _parse(repo_uri)
    if not host:
        raise _reject(_MALFORMED, "no host", repo_uri)
    addresses = await _resolve(host, port, repo_uri)
    forbidden = [a for a in addresses if _is_forbidden(a)]
    if forbidden:
        raise _reject(
            _FORBIDDEN_HOST,
            f"{host} resolves to non-public {', '.join(map(str, forbidden))}",
            repo_uri,
        )
    return CheckedRemote(scheme=scheme, host=host, port=port, addresses=addresses)


def _parse(repo_uri: str) -> tuple[str, str, int]:
    if not repo_uri or any(c.isspace() or not c.isprintable() for c in repo_uri):
        raise _reject(
            _MALFORMED, "empty or contains whitespace/control chars", repo_uri
        )
    if repo_uri.startswith("-"):
        raise _reject(_MALFORMED, "looks like a command-line option", repo_uri)

    if match := _SCHEME_RE.match(repo_uri):
        scheme = match["scheme"].lower()
        if scheme in _HTTPS_SCHEMES:
            normalized = "https"
        elif scheme in _SSH_SCHEMES:
            normalized = "ssh"
        else:
            raise _reject(_MALFORMED, f"scheme {scheme!r} not allowed", repo_uri)
        parsed = urlsplit(repo_uri)
        try:
            port = parsed.port or _DEFAULT_PORTS[normalized]
        except ValueError:
            raise _reject(_MALFORMED, "invalid port", repo_uri) from None
        if parsed.username is not None and parsed.username.startswith("-"):
            raise _reject(_MALFORMED, "user looks like an option", repo_uri)
        return normalized, _validate_host(parsed.hostname or "", repo_uri), port

    # No `scheme://`: scp-style SSH, or something git would treat as a
    # local path or remote helper — reject those.
    if (match := _SCP_RE.match(repo_uri)) is None:
        raise _reject(_MALFORMED, "not an https, ssh or scp-style URI", repo_uri)
    if (match["user"] or "").startswith("-"):
        raise _reject(_MALFORMED, "user looks like an option", repo_uri)
    host = match["host"].removeprefix("[").removesuffix("]").lower()
    return "ssh", _validate_host(host, repo_uri), _DEFAULT_PORTS["ssh"]


def _validate_host(host: str, repo_uri: str) -> str:
    if not host or _is_ip_literal(host) or _HOSTNAME_RE.match(host):
        return host
    raise _reject(_MALFORMED, f"invalid host {host!r}", repo_uri)


def _is_ip_literal(host: str) -> bool:
    try:
        _ = ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def _resolve(host: str, port: int, repo_uri: str) -> tuple[IPAddress, ...]:
    # Always go through getaddrinfo, literals included: it is what turns
    # the shorthand forms git/curl would also accept (`2130706433`,
    # `0x7f.1`, `127.1`) into the address actually dialled.
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=_DNS_TIMEOUT_SECONDS,
        )
    except (OSError, TimeoutError) as e:
        raise _reject(
            _FORBIDDEN_HOST, f"cannot resolve {host}: {e}", repo_uri
        ) from None
    addresses = tuple(
        dict.fromkeys(
            ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos
        )
    )
    if not addresses:
        raise _reject(_FORBIDDEN_HOST, f"{host} resolved to nothing", repo_uri)
    return addresses


def _is_forbidden(address: IPAddress) -> bool:
    if address in _METADATA_ADDRESSES or address.is_multicast or not address.is_global:
        return True
    embedded = _embedded_ipv4(address)
    return embedded is not None and _is_forbidden(embedded)


def _embedded_ipv4(address: IPAddress) -> ipaddress.IPv4Address | None:
    if isinstance(address, ipaddress.IPv4Address):
        return None
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    if address in _NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def _reject(message: str, reason: str, repo_uri: str) -> InvalidRepoURI:
    parsed = urlsplit(repo_uri)
    safe_uri = (
        parsed._replace(netloc=parsed.hostname or "").geturl()
        if parsed.netloc
        else repo_uri
    )
    logging.warning(f"repo_uri rejected ({reason}): {safe_uri!r}")
    return InvalidRepoURI(message=message, error_code=400)
