# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlsplit

from src.infrastructure.exceptions import InvalidRepoURI
from src.shared.logger import logging


@dataclass(frozen=True)
class CheckedRemote:
    scheme: str
    host: str
    port: int
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]

    @property
    def git_config(self) -> tuple[str, ...]:
        if self.scheme != "https":
            return ()
        config = ["http.followRedirects=false"]
        if not RemoteGuard.is_ip_literal(self.host):
            pinned = ",".join(
                f"[{a}]" if a.version == 6 else str(a) for a in self.addresses
            )
            config.append(f"http.curloptResolve={self.host}:{self.port}:{pinned}")
        return tuple(config)

    @property
    def command_options(self) -> list[str]:
        return [arg for c in self.git_config for arg in ("-c", c)]

    @property
    def clone_options(self) -> list[str]:
        return [f"--config={c}" for c in self.git_config]


class RemoteGuard:
    HTTPS_SCHEMES: ClassVar[frozenset[str]] = frozenset({"https"})
    SSH_SCHEMES: ClassVar[frozenset[str]] = frozenset({"ssh", "git+ssh", "ssh+git"})
    DEFAULT_PORTS: ClassVar[dict[str, int]] = {"https": 443, "ssh": 22}
    DNS_TIMEOUT_SECONDS: ClassVar[float] = 5.0

    SCHEME_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://"
    )
    # A path starting with ':' is git's `<transport>::<address>` syntax (`ext::`).
    SCP_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:(?P<user>[^@/:]+)@)?(?P<host>\[[0-9A-Fa-f:.]+\]|[^@/:\[\]]+):(?P<path>[^:].*)$"
    )
    HOSTNAME_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$"
    )

    METADATA_ADDRESSES: ClassVar[
        frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]
    ] = frozenset(
        ipaddress.ip_address(a)
        for a in (
            "169.254.169.254",
            "fd00:ec2::254",
            "169.254.170.2",
            "100.100.100.200",
        )
    )
    NAT64: ClassVar[ipaddress.IPv6Network] = ipaddress.IPv6Network("64:ff9b::/96")

    MALFORMED: ClassVar[str] = "Repository URI must be an https:// or ssh:// git URL."
    FORBIDDEN_HOST: ClassVar[str] = "Repository host is not allowed."

    @classmethod
    async def check(cls, repo_uri: str) -> CheckedRemote:
        scheme, host, port = cls._parse(repo_uri)
        if not host:
            raise cls._reject(cls.MALFORMED, "no host", repo_uri)
        addresses = await cls._resolve(host, port, repo_uri)
        forbidden = [a for a in addresses if cls._is_forbidden(a)]
        if forbidden:
            raise cls._reject(
                cls.FORBIDDEN_HOST,
                f"{host} resolves to non-public {', '.join(map(str, forbidden))}",
                repo_uri,
            )
        return CheckedRemote(scheme=scheme, host=host, port=port, addresses=addresses)

    @staticmethod
    def is_ip_literal(host: str) -> bool:
        try:
            _ = ipaddress.ip_address(host)
        except ValueError:
            return False
        return True

    @classmethod
    def _parse(cls, repo_uri: str) -> tuple[str, str, int]:
        if not repo_uri or any(c.isspace() or not c.isprintable() for c in repo_uri):
            raise cls._reject(
                cls.MALFORMED, "empty or contains whitespace/control chars", repo_uri
            )
        if repo_uri.startswith("-"):
            raise cls._reject(
                cls.MALFORMED, "looks like a command-line option", repo_uri
            )

        if match := cls.SCHEME_RE.match(repo_uri):
            scheme = match["scheme"].lower()
            if scheme in cls.HTTPS_SCHEMES:
                normalized = "https"
            elif scheme in cls.SSH_SCHEMES:
                normalized = "ssh"
            else:
                raise cls._reject(
                    cls.MALFORMED, f"scheme {scheme!r} not allowed", repo_uri
                )
            parsed = urlsplit(repo_uri)
            try:
                port = parsed.port or cls.DEFAULT_PORTS[normalized]
            except ValueError:
                raise cls._reject(cls.MALFORMED, "invalid port", repo_uri) from None
            if parsed.username is not None and parsed.username.startswith("-"):
                raise cls._reject(cls.MALFORMED, "user looks like an option", repo_uri)
            return normalized, cls._validate_host(parsed.hostname or "", repo_uri), port

        if (match := cls.SCP_RE.match(repo_uri)) is None:
            raise cls._reject(
                cls.MALFORMED, "not an https, ssh or scp-style URI", repo_uri
            )
        if (match["user"] or "").startswith("-"):
            raise cls._reject(cls.MALFORMED, "user looks like an option", repo_uri)
        host = match["host"].removeprefix("[").removesuffix("]").lower()
        return "ssh", cls._validate_host(host, repo_uri), cls.DEFAULT_PORTS["ssh"]

    @classmethod
    def _validate_host(cls, host: str, repo_uri: str) -> str:
        if not host or cls.is_ip_literal(host) or cls.HOSTNAME_RE.match(host):
            return host
        raise cls._reject(cls.MALFORMED, f"invalid host {host!r}", repo_uri)

    @classmethod
    async def _resolve(
        cls, host: str, port: int, repo_uri: str
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        # Literals too: getaddrinfo expands shorthands git would also accept
        # (`2130706433`, `0x7f.1`, `127.1`) into the address actually dialled.
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                timeout=cls.DNS_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError) as e:
            raise cls._reject(
                cls.FORBIDDEN_HOST, f"cannot resolve {host}: {e}", repo_uri
            ) from None
        addresses = tuple(
            dict.fromkeys(
                ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos
            )
        )
        if not addresses:
            raise cls._reject(
                cls.FORBIDDEN_HOST, f"{host} resolved to nothing", repo_uri
            )
        return addresses

    @classmethod
    def _is_forbidden(
        cls, address: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> bool:
        if (
            address in cls.METADATA_ADDRESSES
            or address.is_multicast
            or not address.is_global
        ):
            return True
        embedded = cls._embedded_ipv4(address)
        return embedded is not None and cls._is_forbidden(embedded)

    @classmethod
    def _embedded_ipv4(
        cls, address: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> ipaddress.IPv4Address | None:
        if isinstance(address, ipaddress.IPv4Address):
            return None
        if address.ipv4_mapped is not None:
            return address.ipv4_mapped
        if address.sixtofour is not None:
            return address.sixtofour
        if address.teredo is not None:
            return address.teredo[1]
        if address in cls.NAT64:
            return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        return None

    @staticmethod
    def _reject(message: str, reason: str, repo_uri: str) -> InvalidRepoURI:
        parsed = urlsplit(repo_uri)
        safe_uri = (
            parsed._replace(netloc=parsed.hostname or "").geturl()
            if parsed.netloc
            else repo_uri
        )
        logging.warning(f"repo_uri rejected ({reason}): {safe_uri!r}")
        return InvalidRepoURI(message=message, error_code=400)
