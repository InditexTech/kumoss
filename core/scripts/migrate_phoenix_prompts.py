#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Move Kumoss prompts from Phoenix to Langfuse, in two steps.

    export  read every prompt version and its tags from Phoenix into a file
            (run it while the old stack, with Phoenix, is still up)
    import  replay that file into Langfuse, oldest version first, each
            Phoenix tag becoming a Langfuse label (run it on the new stack)

Kumoss prompts are renamed on the way: Phoenix's ``aws-guidelines-networking``
becomes ``aws/guidelines/networking``, which Langfuse shows as folders and
which is the name the core now reads. Other prompts keep their name.

Only what the core reads is moved: versions holding a single text (a
string template, or a chat template of one text message). Others are
listed and skipped. Importing again skips the versions already imported,
so a failed import can simply be rerun.

Standard library only, so it runs with any Python 3.10+, on the host or
in a container:

    python3 core/scripts/migrate_phoenix_prompts.py export \\
        --phoenix-url http://localhost/monitoring/ --out phoenix-prompts.json
    LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-... \\
    python3 core/scripts/migrate_phoenix_prompts.py import \\
        --langfuse-url http://localhost:3000/ --in phoenix-prompts.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

# Langfuse labels: lowercase letters, digits, "_", "-" and ".".
_LABEL_RE = re.compile(r"^[a-z0-9_.-]{1,36}$")
# Langfuse's limit on a version's commit message.
_COMMIT_MESSAGE_MAX = 500
# Put in the commit message of each imported version; how a rerun knows it.
_MARKER = "phoenix-version:"
# A Kumoss prompt name in Phoenix: <scope>-<type>-<name>, where only the
# scope may contain "-", so the split is unambiguous.
_KUMOSS_NAME = re.compile(
    r"^(?P<scope>[a-z0-9][a-z0-9_-]*)-(?P<type>guidelines|resources|compliance)-(?P<name>[a-z0-9_]+)$"
)


def langfuse_name(phoenix_name: str) -> str:
    """The Langfuse name of a Phoenix prompt: Kumoss prompts move into
    their <scope>/<type> folders, others keep their name."""
    match = _KUMOSS_NAME.match(phoenix_name)
    if match is None:
        return phoenix_name
    return f"{match['scope']}/{match['type']}/{match['name']}"


class _Http:
    def __init__(self, base_url: str, headers: dict[str, str] | None = None):
        # urllib would also open file:// and other schemes.
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise SystemExit(f"Not an http(s) URL: {base_url}")
        self.base_url = base_url.rstrip("/") + "/"
        self.headers = {"Accept": "application/json", **(headers or {})}

    def call(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> tuple[int, Any]:
        query = urllib.parse.urlencode(
            {k: v for k, v in (params or {}).items() if v is not None}
        )
        url = self.base_url + path + (f"?{query}" if query else "")
        data = None if body is None else json.dumps(body).encode()
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            # The scheme is checked to be http(s) in __init__.
            with (
                urllib.request.urlopen(request, timeout=30) as response
            ):  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")

    def ok(self, method: str, path: str, **kwargs: Any) -> Any:
        status, payload = self.call(method, path, **kwargs)
        if not 200 <= status < 300:
            raise SystemExit(
                f"{method} {self.base_url}{path} failed: {status} {payload}"
            )
        return payload


# --- export ----------------------------------------------------------------


def _pages(phoenix: _Http, path: str) -> Iterator[dict[str, Any]]:
    cursor = None
    while True:
        page = phoenix.ok("GET", path, params={"cursor": cursor, "limit": 100})
        yield from page["data"]
        cursor = page.get("next_cursor")
        if not cursor:
            return


def _sequence(version_id: str) -> int:
    """Phoenix ids are base64 of ``PromptVersion:<n>``; n orders versions."""
    try:
        return int(base64.b64decode(version_id).decode().rsplit(":", 1)[1])
    except Exception:
        return 0


def _text(template: dict[str, Any]) -> str | None:
    if template.get("type") == "string":
        text = template.get("template")
        return text if isinstance(text, str) else None
    messages = template.get("messages") or []
    if len(messages) != 1:
        return None
    content = messages[0].get("content")
    if isinstance(content, str):
        return content
    if (
        isinstance(content, list)
        and len(content) == 1
        and content[0].get("type") == "text"
        and isinstance(content[0].get("text"), str)
    ):
        return content[0]["text"]
    return None


def export(args: argparse.Namespace) -> None:
    phoenix = _Http(args.phoenix_url)
    prompts = []
    for prompt in _pages(phoenix, "v1/prompts"):
        name = prompt["name"]
        quoted = urllib.parse.quote(name, safe="")
        versions = []
        for version in _pages(phoenix, f"v1/prompts/{quoted}/versions"):
            tags = [
                t["name"]
                for t in _pages(phoenix, f"v1/prompt_versions/{version['id']}/tags")
            ]
            versions.append(
                {
                    "id": version["id"],
                    "description": version.get("description"),
                    "text": _text(version.get("template") or {}),
                    "tags": tags,
                    "template": version.get("template"),
                }
            )
        versions.sort(key=lambda v: _sequence(v["id"]))
        prompts.append(
            {
                "name": name,
                "description": prompt.get("description"),
                "versions": versions,
            }
        )
        print(f"exported {name}: {len(versions)} version(s)")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {"source": "phoenix", "prompts": prompts}, f, indent=2, ensure_ascii=False
        )
    print(f"wrote {len(prompts)} prompt(s) to {args.out}")


# --- import ----------------------------------------------------------------


def _imported(langfuse: _Http, name: str) -> set[str]:
    """The Phoenix version ids already imported into prompt ``name``."""
    quoted = urllib.parse.quote(name, safe="")
    status, latest = langfuse.call(
        "GET", f"v2/prompts/{quoted}", params={"label": "latest"}
    )
    if status == 404:
        return set()
    if status != 200:
        raise SystemExit(f"Reading {name} from Langfuse failed: {status} {latest}")
    found = set()
    for number in range(1, latest["version"] + 1):
        status, version = langfuse.call(
            "GET", f"v2/prompts/{quoted}", params={"version": number}
        )
        if status == 404:
            continue  # version deleted in Langfuse
        if status != 200:
            # Writing without knowing what is there could import twice.
            raise SystemExit(
                f"Reading {name} version {number} from Langfuse failed: "
                + f"{status} {version}"
            )
        message = version.get("commitMessage") or ""
        found.update(re.findall(rf"{_MARKER}(\S+)", message))
    return found


def _seed_fallback(name: str, versions: list[dict[str, Any]]) -> None:
    """Put ``seed`` on the oldest readable version when no version has it.

    A Phoenix install older than the seed tag has none. Without it the
    seeder would take the latest version as its own, which may be an
    operator's, and move its environment labels to the shipped text. The
    oldest version is the one the seeder created.
    """
    readable = [v for v in versions if v["text"] is not None]
    if not readable or any("seed" in v["tags"] for v in versions):
        return
    readable[0]["tags"] = [*readable[0]["tags"], "seed"]
    print(
        f"note {name}: no version tagged seed; labelling the oldest one {readable[0]['id']} seed"
    )


def _commit_message(name: str, version: dict[str, Any]) -> str:
    """The description, cut to leave room for the import marker."""
    marker = f"{_MARKER}{version['id']}"
    description = version.get("description") or ""
    room = _COMMIT_MESSAGE_MAX - len(marker) - 1
    if len(description) > room:
        print(
            f"note {name} {version['id']}: description cut to fit Langfuse's commit message"
        )
        description = description[: room - 1] + "…"
    return f"{description} {marker}" if description else marker


def import_(args: argparse.Namespace) -> None:
    public_key = args.public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = args.secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        raise SystemExit(
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (or pass the flags)."
        )
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    langfuse = _Http(
        args.langfuse_url.rstrip("/") + "/api/public/",
        {"Authorization": f"Basic {token}"},
    )
    langfuse.ok("GET", "v2/prompts", params={"limit": 1})  # reachable, keys accepted

    with open(args.input, encoding="utf-8") as f:
        prompts = json.load(f)["prompts"]

    created = skipped = done = 0
    for prompt in prompts:
        name = langfuse_name(prompt["name"])
        if name != prompt["name"]:
            print(f"rename {prompt['name']} -> {name}")
        imported = _imported(langfuse, name)
        _seed_fallback(name, prompt["versions"])
        for version in prompt["versions"]:
            if version["id"] in imported:
                done += 1
                continue
            if version["text"] is None:
                print(
                    f"skip {name} {version['id']}: not a single text, the core cannot read it"
                )
                skipped += 1
                continue
            labels = [
                t for t in version["tags"] if _LABEL_RE.match(t) and t != "latest"
            ]
            for tag in set(version["tags"]) - set(labels):
                print(
                    f"note {name} {version['id']}: tag {tag!r} is not a valid Langfuse label, dropped"
                )
            message = _commit_message(name, version)
            body = {
                "type": "text",
                "name": name,
                "prompt": version["text"],
                "labels": labels,
                "commitMessage": message,
            }
            if args.dry_run:
                print(f"would create {name} labels={labels}")
            else:
                result = langfuse.ok("POST", "v2/prompts", body=body)
                print(f"created {name} v{result['version']} labels={labels}")
            created += 1
    print(
        f"{'would create' if args.dry_run else 'created'} {created} version(s), "
        + f"{done} already imported, {skipped} skipped"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export", help="Phoenix prompts to a file")
    p.add_argument(
        "--phoenix-url", required=True, help="e.g. http://localhost/monitoring/"
    )
    p.add_argument("--out", required=True)
    p.set_defaults(run=export)

    p = sub.add_parser("import", help="a file of Phoenix prompts into Langfuse")
    p.add_argument("--langfuse-url", required=True, help="e.g. http://localhost:3000/")
    p.add_argument("--in", dest="input", required=True)
    p.add_argument("--public-key", help="default: $LANGFUSE_PUBLIC_KEY")
    p.add_argument("--secret-key", help="default: $LANGFUSE_SECRET_KEY")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(run=import_)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    sys.exit(main())
