# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the repo_uri SSRF guard (vuln-0009)."""

import unittest
from unittest.mock import AsyncMock, patch

from src.infrastructure.exceptions import InvalidRepoURI
from src.infrastructure.filesystem.git.git_utils import GitUtils
from src.infrastructure.filesystem.git.repo_uri_guard import (
    REJECTED_MESSAGE,
    RepoRemote,
    ensure_repo_uri_allowed,
    parse_repo_uri,
)
from src.shared.config import system_config
from src.shared.constants import GitProviderName

_GUARD = "src.infrastructure.filesystem.git.repo_uri_guard"


class TestParseRepoUri(unittest.TestCase):
    def test_accepts_supported_remote_forms(self):
        cases = {
            "https://github.com/foo/bar.git": RepoRemote("github.com", None),
            "Https://Org@dev.azure.com/org/p/_git/r": RepoRemote("dev.azure.com", None),
            "https://git.example.com:8443/foo/bar.git": RepoRemote(
                "git.example.com", 8443
            ),
            "ssh://git@github.com/foo/bar.git": RepoRemote("github.com", None, True),
            "ssh://git@github.com:2222/foo/bar.git": RepoRemote(
                "github.com", 2222, True
            ),
            "git@github.com:foo/bar.git": RepoRemote("github.com", None, True),
            "git@[2001:db8::1]:foo/bar.git": RepoRemote("2001:db8::1", None, True),
            "https://0xcafe.example.com/x.git": RepoRemote("0xcafe.example.com", None),
        }
        for uri, expected in cases.items():
            with self.subTest(uri=uri):
                self.assertEqual(parse_repo_uri(uri), expected)

    def test_rejects_unsupported_transports(self):
        for uri in (
            "file:///etc/passwd",
            "FILE:///etc/passwd",
            "http://core:8000/x",
            "git://github.com/foo/bar",
            "ftp://example.com/x",
            "git+ssh://github.com/foo/bar",
            "ext::sh -c id",
            "ext::sh%20-c%20id",
            "fd::3",
            "/etc/passwd",
            "./repo",
            "--upload-pack=id",
            "",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                _ = parse_repo_uri(uri)

    def test_rejects_obfuscated_or_malformed_hosts(self):
        for uri in (
            "https://2130706433/x",  # decimal 127.0.0.1
            "https://0x7f000001/x",  # hex 127.0.0.1
            "https://0x7f.1/x",
            "https://0177.0.0.1/x",  # octal 127.0.0.1
            "https://127.1/x",
            "https://%31%32%37.0.0.1/x",
            "https://-evil.example.com/x",
            "https:///no-host",
            "https://github.com:99999/x",
            "https://github.com:0/x",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                _ = parse_repo_uri(uri)

    def test_rejects_whitespace_and_control_characters(self):
        for uri in (
            "https://github.com/foo/bar.git\n",
            "https://github.com/foo bar",
            "https://github.com/\x00",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                _ = parse_repo_uri(uri)

    def test_rejects_ssh_option_injection(self):
        for uri in (
            "ssh://-oProxyCommand=id@github.com/x",
            "-oProxyCommand=id@github.com:x",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                _ = parse_repo_uri(uri)


class TestEnsureRepoUriAllowed(unittest.IsolatedAsyncioTestCase):
    async def _assert_rejected(self, uri: str):
        with self.assertRaises(InvalidRepoURI) as ctx:
            await ensure_repo_uri_allowed(uri)
        self.assertEqual(ctx.exception.error_code, 400)
        self.assertEqual(ctx.exception.message, REJECTED_MESSAGE)

    async def test_rejects_non_public_ip_literals(self):
        for uri in (
            "https://127.0.0.1/x",
            "https://10.0.0.1/x",
            "https://172.18.0.10:8000/x",
            "https://192.168.1.1/x",
            "https://169.254.169.254/latest/meta-data/",
            "https://100.64.0.1/x",
            "https://0.0.0.0/x",
            "https://[::1]/x",
            "https://[fd00::1]/x",
            "https://[fe80::1%25eth0]/x",
            "https://[::ffff:10.0.0.1]/x",
            "https://224.0.0.1/x",
        ):
            with self.subTest(uri=uri):
                await self._assert_rejected(uri)

    async def test_rejects_hostnames_resolving_to_internal_addresses(self):
        for addresses in ({"172.18.0.10"}, {"127.0.0.1"}, {"140.82.112.3", "10.0.0.5"}):
            with (
                self.subTest(addresses=addresses),
                patch(f"{_GUARD}._resolve", AsyncMock(return_value=addresses)),
            ):
                await self._assert_rejected("https://core:8000/api/v1/auth/config")

    async def test_rejects_unresolvable_hosts_with_the_same_message(self):
        with patch(f"{_GUARD}._resolve", AsyncMock(side_effect=OSError("NXDOMAIN"))):
            await self._assert_rejected("https://notifications:8080")

    async def test_rejects_unsupported_transport(self):
        await self._assert_rejected("file:///etc/passwd")

    async def test_accepts_hostnames_resolving_to_public_addresses(self):
        resolve = AsyncMock(return_value={"140.82.112.3", "2606:50c0:8000::153"})
        with patch(f"{_GUARD}._resolve", resolve):
            await ensure_repo_uri_allowed("git@github.com:foo/bar.git")
        resolve.assert_awaited_once_with(RepoRemote("github.com", None, True))

    async def test_allowed_hosts_pins_the_host_and_trusts_private_addresses(self):
        resolve = AsyncMock(return_value={"140.82.112.3"})
        with (
            patch.object(system_config.git, "allowed_hosts", ["GitLab.Corp.Local."]),
            patch(f"{_GUARD}._resolve", resolve),
        ):
            options = await ensure_repo_uri_allowed(
                "https://gitlab.corp.local/team/iac.git"
            )
            await self._assert_rejected("https://github.com/foo/bar.git")
        resolve.assert_not_awaited()
        # Operator-vouched hosts keep the protocol allowlist but are not pinned.
        self.assertIn("protocol.allow=never", options)
        self.assertFalse(any("curloptResolve" in o for o in options))


class TestPinsGitToTheVettedAddresses(unittest.IsolatedAsyncioTestCase):
    """git must connect to the addresses the guard checked, not re-resolve
    the name: a TTL-0 record could answer the second lookup with an internal
    address (DNS rebinding)."""

    async def _options(self, uri: str, addresses: set[str]) -> tuple[str, ...]:
        with patch(f"{_GUARD}._resolve", AsyncMock(return_value=addresses)):
            return await ensure_repo_uri_allowed(uri)

    async def test_every_result_carries_the_protocol_allowlist(self):
        options = await self._options("https://github.com/a/b", {"140.82.112.3"})
        self.assertEqual(
            options[:6],
            (
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.https.allow=always",
                "-c",
                "protocol.ssh.allow=always",
            ),
        )

    async def test_https_pins_every_vetted_address_on_the_default_port(self):
        options = await self._options(
            "https://github.com/a/b", {"2606:50c0:8000::153", "140.82.112.3"}
        )
        self.assertEqual(
            options[-2:],
            (
                "-c",
                "http.curloptResolve=github.com:443:140.82.112.3,[2606:50c0:8000::153]",
            ),
        )

    async def test_https_pins_the_explicit_port(self):
        options = await self._options(
            "https://git.example.com:8443/a/b", {"93.184.216.34"}
        )
        self.assertEqual(
            options[-1], "http.curloptResolve=git.example.com:8443:93.184.216.34"
        )

    async def test_ssh_pins_the_address_and_keeps_known_hosts_keyed_by_name(self):
        for uri in ("git@github.com:a/b.git", "ssh://git@github.com:22/a/b"):
            with self.subTest(uri=uri):
                options = await self._options(uri, {"140.82.112.3"})
                self.assertEqual(
                    options[-1],
                    "core.sshCommand=ssh -o HostName=140.82.112.3 "
                    + "-o HostKeyAlias=github.com",
                )

    async def test_ip_literals_are_not_pinned(self):
        options = await self._options("https://140.82.112.3/a/b", {"140.82.112.3"})
        self.assertFalse(any("curloptResolve" in o for o in options))


class TestGitNetworkCommandsRefuseRedirects(unittest.IsolatedAsyncioTestCase):
    """A validated remote must not be able to redirect git to another host."""

    def _git(self) -> tuple[GitUtils, AsyncMock]:
        git = GitUtils(
            uri="https://github.com/foo/bar.git",
            git_provider=GitProviderName.GITHUB,
            remote_options=(),
        )
        execute = AsyncMock()
        execute.return_value.returncode = 0
        execute.return_value.stdout = b"ref: refs/heads/main\tHEAD\n"
        git._GitUtils__cli.execute = execute
        return git, execute

    async def test_ls_remote(self):
        git, execute = self._git()
        _ = await git.ls_remote()
        cmd = execute.await_args.args[0]
        self.assertEqual(cmd[:3], ["git", "-c", "http.followRedirects=false"])
        self.assertEqual(cmd[-2:], ["--", "https://github.com/foo/bar.git"])

    async def test_default_branch_ls_remote(self):
        git, execute = self._git()
        _ = await git.get_default_branch(ls_remote=True)
        cmd = execute.await_args.args[0]
        self.assertEqual(cmd[:3], ["git", "-c", "http.followRedirects=false"])

    async def test_clone_persists_the_setting_for_later_push_and_fetch(self):
        git, execute = self._git()
        _ = await git.clone_repository("https://github.com/foo/bar.git", "repo")
        cmd = execute.await_args.args[0]
        # `git clone -c` (not `git -c clone`) writes it into .git/config.
        self.assertEqual(cmd[:4], ["git", "clone", "-c", "http.followRedirects=false"])
        self.assertEqual(cmd[-3:], ["--", "https://github.com/foo/bar.git", "repo"])

    async def test_without_remote_options_each_command_runs_the_guard(self):
        """Callers that did not validate (clone in a session iteration, the
        default-branch lookup behind create_pr) still get checked and pinned."""
        git = GitUtils(
            uri="https://github.com/foo/bar.git", git_provider=GitProviderName.GITHUB
        )
        execute = AsyncMock()
        execute.return_value.returncode = 0
        git._GitUtils__cli.execute = execute
        pin = ("-c", "http.curloptResolve=github.com:443:140.82.112.3")
        with patch(
            "src.infrastructure.filesystem.git.git_utils.ensure_repo_uri_allowed",
            AsyncMock(return_value=pin),
        ) as guard:
            _ = await git.clone_repository("https://github.com/foo/bar.git", "repo")
        guard.assert_awaited_once_with("https://github.com/foo/bar.git")
        cmd = execute.await_args.args[0]
        self.assertEqual(cmd[1:6], ["clone", "-c", "http.followRedirects=false", *pin])

    async def test_a_rejected_uri_never_reaches_git(self):
        git = GitUtils(uri="https://127.0.0.1/x", git_provider=GitProviderName.GITHUB)
        execute = AsyncMock()
        git._GitUtils__cli.execute = execute
        with self.assertRaises(InvalidRepoURI):
            _ = await git.clone_repository("https://127.0.0.1/x", "repo")
        execute.assert_not_awaited()
