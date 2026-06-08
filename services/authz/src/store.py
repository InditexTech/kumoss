# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""JSON-file backed user/role store.

Schema:

    {
      "users": {
        "<user_id>": {
          "id": "<user_id>",
          "email": "...",
          "name": "...",
          "roles": ["admin", ...]
        },
        ...
      }
    }

The file is read on every request (small, synchronous) and rewritten
under a process-wide lock on every mutation. This is enough for OSS
single-replica deployments; production deploys should swap in a real
backend.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

# Roles available out of the box. Implementations MAY extend this set.
KNOWN_ROLES: dict[str, str] = {
    "admin": "Full administrative access (manage users and roles, run any operation).",
    "user": "Standard authenticated user. May invoke generation/drift/import.",
}

_lock = threading.Lock()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"users": {}}
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "users" not in data:
            return {"users": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"users": {}}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


def bootstrap_root_admin(path: Path, email: str) -> None:
    """Ensure the bootstrap admin exists with the ``admin`` role."""
    if not email:
        return
    with _lock:
        data = _load(path)
        users = data.setdefault("users", {})
        record = users.setdefault(
            email,
            {"id": email, "email": email, "name": None, "roles": []},
        )
        roles = record.setdefault("roles", [])
        if "admin" not in roles:
            roles.append("admin")
        _save(path, data)


def get_or_create_user(path: Path, user_id: str, email: str | None) -> dict[str, Any]:
    with _lock:
        data = _load(path)
        users = data.setdefault("users", {})
        record = users.get(user_id)
        if record is None:
            record = {"id": user_id, "email": email, "name": None, "roles": []}
            users[user_id] = record
            _save(path, data)
        elif email and not record.get("email"):
            record["email"] = email
            _save(path, data)
        return dict(record)


def list_users(path: Path) -> list[dict[str, Any]]:
    data = _load(path)
    return [dict(u) for u in data.get("users", {}).values()]


def has_role(path: Path, user_id: str, role: str) -> bool:
    data = _load(path)
    user = data.get("users", {}).get(user_id)
    return bool(user and role in user.get("roles", []))


def assign_role(path: Path, user_id: str, role: str) -> None:
    if role not in KNOWN_ROLES:
        raise KeyError(role)
    with _lock:
        data = _load(path)
        users = data.setdefault("users", {})
        record = users.setdefault(
            user_id, {"id": user_id, "email": None, "name": None, "roles": []}
        )
        roles = record.setdefault("roles", [])
        if role not in roles:
            roles.append(role)
        _save(path, data)


def revoke_role(path: Path, user_id: str, role: str) -> None:
    with _lock:
        data = _load(path)
        users = data.setdefault("users", {})
        record = users.get(user_id)
        if record is None:
            return
        roles = record.get("roles", [])
        if role in roles:
            roles.remove(role)
            _save(path, data)
