"""Project Q02 — versioned message templates with variable substitution.

Templates are versioned: creating a template with an existing name writes a
new row (version = max + 1) and deactivates the old ones, so template
history is preserved. Every render validates that all required variables
are present and fails loudly on missing ones (never renders a half-filled
message). A ``test_send`` renders against a fixture context without
queueing anything.

Template syntax: ``{{variable_name}}``. Variables are [A-Za-z0-9_] only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .validation import ValidationError

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
MAX_NAME_LEN = 80
MAX_SUBJECT_LEN = 200
MAX_BODY_LEN = 10000


class TemplateRenderError(Exception):
    """Raised when a template cannot be rendered for a context."""


def _now_iso(now: Optional[datetime]) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def extract_variables(text: str) -> list[str]:
    """Variable names used in ``{{...}}`` placeholders, first-use order."""
    seen: list[str] = []
    for m in _VAR_RE.finditer(text or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def create_template(
    conn: sqlite3.Connection,
    name: str,
    subject: str,
    body: str,
    *,
    variables: Optional[list[str]] = None,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Create a template, or a new version of an existing name.

    ``variables`` defaults to the union of placeholders found in the
    subject and body. Unknown names, empty subject/body, and oversize
    fields are rejected with ValidationError.
    """
    errors: dict[str, str] = {}
    name = (name or "").strip()
    if not name:
        errors["name"] = "Template name is required."
    elif len(name) > MAX_NAME_LEN:
        errors["name"] = f"Must be at most {MAX_NAME_LEN} characters."
    elif not re.fullmatch(r"[A-Za-z0-9_]+", name):
        errors["name"] = "Letters, digits and underscores only."
    subject = subject or ""
    body = body or ""
    if not subject.strip():
        errors["subject"] = "Subject is required."
    elif len(subject) > MAX_SUBJECT_LEN:
        errors["subject"] = f"Must be at most {MAX_SUBJECT_LEN} characters."
    if not body.strip():
        errors["body"] = "Body is required."
    elif len(body) > MAX_BODY_LEN:
        errors["body"] = f"Must be at most {MAX_BODY_LEN} characters."
    if variables is not None:
        if not isinstance(variables, list) or not all(
            isinstance(v, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v)
            for v in variables
        ):
            errors["variables"] = "Must be a list of variable names."
    if errors:
        raise ValidationError(errors)

    if variables is None:
        variables = extract_variables(subject) + [
            v for v in extract_variables(body) if v not in extract_variables(subject)
        ]

    row = conn.execute(
        "SELECT MAX(version) AS v FROM message_templates WHERE name = ?", (name,)
    ).fetchone()
    version = (row["v"] or 0) + 1
    created = _now_iso(now)
    if version > 1:
        conn.execute(
            "UPDATE message_templates SET is_active = 0 WHERE name = ?", (name,)
        )
    cur = conn.execute(
        """
        INSERT INTO message_templates
            (name, version, subject, body, variables, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (name, version, subject, body, json.dumps(variables, sort_keys=True), created),
    )
    conn.commit()
    print(
        json.dumps(
            {
                "ts": created,
                "event": "template.version_created",
                "template_id": cur.lastrowid,
                "name": name,
                "version": version,
                "actor": actor,
            },
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
    return get_template(conn, name, version=version)


def get_template(
    conn: sqlite3.Connection, name: str, *, version: Optional[int] = None
) -> Optional[dict]:
    """Fetch a template: the active version by default, a specific one if asked."""
    if version is None:
        row = conn.execute(
            "SELECT * FROM message_templates WHERE name = ? AND is_active = 1",
            (name,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM message_templates WHERE name = ? AND version = ?",
            (name, version),
        ).fetchone()
    return dict(row) if row else None


def template_history(conn: sqlite3.Connection, name: str) -> list[dict]:
    """All versions of a template, newest first. History is never deleted."""
    rows = conn.execute(
        "SELECT * FROM message_templates WHERE name = ? ORDER BY version DESC",
        (name,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_templates(conn: sqlite3.Connection) -> list[dict]:
    """The active version of every template, ordered by name."""
    rows = conn.execute(
        "SELECT * FROM message_templates WHERE is_active = 1 ORDER BY name ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def _substitute(text: str, context: Mapping[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        return str(context[m.group(1)])

    return _VAR_RE.sub(repl, text)


def render_template(
    conn: sqlite3.Connection, name: str, context: Mapping[str, Any],
    *, version: Optional[int] = None,
) -> dict:
    """Render the active (or pinned) version of ``name`` against ``context``.

    Raises TemplateRenderError when the template does not exist (or has no
    active version) or when any required variable is missing. Missing values
    are a hard failure — no partial renders leave this function.
    """
    if not isinstance(context, Mapping):
        raise TemplateRenderError("Render context must be a mapping.")
    template = get_template(conn, name, version=version)
    if template is None:
        raise TemplateRenderError(
            f"No {'active ' if version is None else ''}template named {name!r}."
        )
    required = json.loads(template["variables"])
    missing = [v for v in required if v not in context or context[v] is None]
    if missing:
        raise TemplateRenderError(
            f"Template {name!r} v{template['version']} is missing required "
            f"variable(s): {', '.join(sorted(missing))}."
        )
    return {
        "name": name,
        "version": template["version"],
        "subject": _substitute(template["subject"], context),
        "body": _substitute(template["body"], context),
    }


def test_send(
    conn: sqlite3.Connection, name: str, context: Mapping[str, Any],
    *, version: Optional[int] = None,
) -> dict:
    """Render a template against a fixture context without queueing anything.

    This is the render-time validation gate called out in the failure
    analysis: a wrong-variable template fails here, in tests, instead of
    silently filling the outbox with broken messages.
    """
    rendered = render_template(conn, name, context, version=version)
    leftover = extract_variables(rendered["subject"]) + extract_variables(
        rendered["body"]
    )
    if leftover:
        raise TemplateRenderError(
            f"Unsubstituted placeholder(s) after render: {', '.join(leftover)}."
        )
    return rendered
