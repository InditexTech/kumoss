# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the repository-URI SSRF guard.

DNS is faked by patching ``socket.getaddrinfo`` (what the event loop's
resolver calls), so the suite runs without network access.
"""

import ipaddress
import socket
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, override
from unittest.mock import patch

from src.infrastructure.exceptions import InvalidRepoURI
from src.infrastructure.filesystem.git.remote_guard import CheckedRemote, check_remote


def _resolves_to(*addresses: str):
    def fake(_host: str, port: int, *_args: object, **_kwargs: object):
        return [
            (
                socket.AF_INET6 if ":" in a else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (a, port),
            )
            for a in addresses
        ]

    return patch("socket.getaddrinfo", side_effect=fake)


class TestSchemes(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_https_and_ssh_forms(self):
        cases = {
            "https://github.com/org/repo.git": ("https", "github.com", 443),
            "https://org@dev.azure.com:8443/org/p/_git/r": (
                "https",
                "dev.azure.com",
                8443,
            ),
            "ssh://git@github.com/org/repo.git": ("ssh", "github.com", 22),
            "git+ssh://git@github.com/org/repo.git": ("ssh", "github.com", 22),
            "git@github.com:org/repo.git": ("ssh", "github.com", 22),
            "GitHub.com:org/repo.git": ("ssh", "github.com", 22),
        }
        for uri, (scheme, host, port) in cases.items():
            with self.subTest(uri=uri), _resolves_to("140.82.121.3"):
                remote = await check_remote(uri)
                self.assertEqual(
                    (remote.scheme, remote.host, remote.port), (scheme, host, port)
                )

    async def test_rejects_other_transports_and_shapes(self):
        for uri in (
            "file:///etc/passwd",
            "git://github.com/org/repo.git",
            "http://github.com/org/repo.git",
            "ftp://github.com/repo",
            "ext::sh -c touch% /tmp/pwned",
            "ext::sh",
            "fd::17",
            "/srv/git/repo.git",
            "./repo",
            "../repo:x",
            "--upload-pack=touch /tmp/x",
            "-oProxyCommand=x:repo",
            "ssh://-oProxyCommand=x/repo",
            "ssh://-host/repo",
            "git@-host:repo",
            "-u@host:repo",
            "https://github.com:99999/repo",
            "https:///repo",
            "https://github.com/repo\nfoo",
            "https://github.com/re po",
            "",
        ):
            with (
                self.subTest(uri=uri),
                _resolves_to("140.82.121.3"),
                self.assertRaises(InvalidRepoURI) as ctx,
            ):
                _ = await check_remote(uri)
            self.assertEqual(ctx.exception.error_code, 400)


class TestResolvedAddresses(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_public_addresses(self):
        for address in (
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "169.254.170.2",
            "100.100.100.200",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "240.0.0.1",
            "::1",
            "::",
            "fe80::1",
            "fd00:ec2::254",
            "fc00::1",
            "::ffff:127.0.0.1",
            "::ffff:169.254.169.254",
            "64:ff9b::a9fe:a9fe",  # NAT64 -> 169.254.169.254
            "2002:a9fe:a9fe::1",  # 6to4 -> 169.254.169.254
            "ff02::1",
        ):
            with (
                self.subTest(address=address),
                _resolves_to(address),
                self.assertRaises(InvalidRepoURI),
            ):
                _ = await check_remote("https://evil.example/repo.git")

    async def test_rejects_when_any_resolved_address_is_internal(self):
        with (
            _resolves_to("140.82.121.3", "10.0.0.5"),
            self.assertRaises(InvalidRepoURI),
        ):
            _ = await check_remote("https://mixed.example/repo.git")

    async def test_rejects_unresolvable_host_with_the_same_message(self):
        with (
            patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")),
            self.assertRaises(InvalidRepoURI) as unresolvable,
        ):
            _ = await check_remote("https://nope.invalid/repo.git")
        with _resolves_to("10.0.0.5"), self.assertRaises(InvalidRepoURI) as internal:
            _ = await check_remote("https://internal.example/repo.git")
        # Same answer either way, so the endpoint is no oracle for which
        # internal names exist.
        self.assertEqual(unresolvable.exception.message, internal.exception.message)
        self.assertNotIn("nope", unresolvable.exception.message)

    async def test_numeric_shorthands_are_resolved_not_trusted(self):
        # Real resolver: these never touch DNS.
        for uri in (
            "https://127.1/repo.git",
            "https://2130706433/repo.git",
            "https://0x7f.0.0.1/repo.git",
            "https://[::ffff:7f00:1]/repo.git",
            "https://localhost/repo.git",
            "ssh://[::1]/repo.git",
            "git@[::1]:repo.git",
        ):
            with self.subTest(uri=uri), self.assertRaises(InvalidRepoURI):
                _ = await check_remote(uri)

    async def test_accepts_public_addresses(self):
        with _resolves_to("140.82.121.3", "2606:50c0:8000::153"):
            remote = await check_remote("https://github.com/org/repo.git")
        self.assertEqual(
            remote.addresses,
            (
                ipaddress.ip_address("140.82.121.3"),
                ipaddress.ip_address("2606:50c0:8000::153"),
            ),
        )


class TestGitConfig(unittest.IsolatedAsyncioTestCase):
    async def test_https_pins_every_checked_address_and_disables_redirects(self):
        with _resolves_to("140.82.121.3", "2606:50c0:8000::153"):
            remote = await check_remote("https://github.com/org/repo.git")
        self.assertEqual(
            remote.git_config,
            (
                "http.followRedirects=false",
                "http.curloptResolve=github.com:443:140.82.121.3,[2606:50c0:8000::153]",
            ),
        )
        self.assertEqual(
            remote.command_options,
            ["-c", remote.git_config[0], "-c", remote.git_config[1]],
        )
        self.assertEqual(
            remote.clone_options, [f"--config={c}" for c in remote.git_config]
        )

    async def test_ip_literal_host_needs_no_pin(self):
        remote = await check_remote("https://140.82.121.3/org/repo.git")
        self.assertEqual(remote.git_config, ("http.followRedirects=false",))

    async def test_ssh_has_no_http_config(self):
        with _resolves_to("140.82.121.3"):
            remote = await check_remote("git@github.com:org/repo.git")
        self.assertEqual(remote.git_config, ())


class _RedirectHandler(BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []

    def do_GET(self):
        type(self).hits.append(self.path)
        self.send_response(302)
        self.send_header("Location", "/elsewhere/info/refs?service=git-upload-pack")
        self.end_headers()

    @override
    def log_message(self, format: str, *args: object) -> None:
        pass


class TestGitHonoursTheConfig(unittest.TestCase):
    """Runs real git against a local server to prove the emitted config
    actually pins resolution and stops redirects (not just that we emit it)."""

    server: HTTPServer

    def setUp(self):
        _RedirectHandler.hits = []
        self.server = HTTPServer(("127.0.0.1", 0), _RedirectHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_pinned_host_reaches_checked_address_and_redirect_is_not_followed(self):
        port = self.server.server_address[1]
        # A name that cannot resolve: git only reaches the server via the pin.
        remote = CheckedRemote(
            scheme="https",
            host="nebula-pin.invalid",
            port=port,
            addresses=(ipaddress.ip_address("127.0.0.1"),),
        )
        result = subprocess.run(
            [
                "git",
                *remote.command_options,
                "ls-remote",
                "--",
                f"http://nebula-pin.invalid:{port}/repo.git",
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(_RedirectHandler.hits), 1, _RedirectHandler.hits)
        self.assertTrue(_RedirectHandler.hits[0].startswith("/repo.git/info/refs"))
