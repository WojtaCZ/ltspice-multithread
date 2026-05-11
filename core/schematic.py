"""Detect and substitute LTSpice parameters in .asc files.

Two parameter sources:
- Bare {NAME} tokens (typically used in component values)
- Names declared via `.param NAME=...` directives in TEXT lines

Substitution updates BOTH: rewrites `.param NAME=value` in place AND replaces
bare `{NAME}` tokens. This covers names used inside expressions like
`{NAME*2}`, which can't be textually replaced (no bare-token match) but
resolve correctly once the underlying `.param` declaration changes.
"""
from __future__ import annotations

import re
from pathlib import Path

# Bare {NAME} token (a single bare identifier in braces).
BRACE_RE = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')

# A `.param ...` directive (case-insensitive). Body is the rest of the line.
PARAM_DIRECTIVE_RE = re.compile(r'\.param\b\s+(.+)', re.IGNORECASE)

# Within a .param body: NAME=value where value is either {expression} or a
# non-whitespace token that does NOT include a literal \n (the two-char sequence
# backslash + n used by LTSpice to encode newlines inside TEXT directives).
PARAM_NAME_VALUE_RE = re.compile(r'(\w+)\s*=\s*(\{[^}]*\}|(?:(?!\\n)\S)+)')

# Back-compat alias for any external callers.
PARAM_RE = BRACE_RE


def _param_names_in_text(text: str) -> list[str]:
    """Names declared via `.param NAME=...`, in order of first appearance."""
    seen: list[str] = []
    s: set[str] = set()
    for line in text.splitlines():
        m = PARAM_DIRECTIVE_RE.search(line)
        if not m:
            continue
        for nm in PARAM_NAME_VALUE_RE.finditer(m.group(1)):
            name = nm.group(1)
            if name not in s:
                s.add(name)
                seen.append(name)
    return seen


def _brace_names_in_text(text: str) -> list[str]:
    """Bare `{NAME}` tokens, in order of first appearance."""
    seen: list[str] = []
    s: set[str] = set()
    for m in BRACE_RE.finditer(text):
        name = m.group(1)
        if name not in s:
            s.add(name)
            seen.append(name)
    return seen


def find_parameters(asc_path: str | Path) -> list[str]:
    """Return all parameter names found in the schematic.

    Order: `.param`-declared first (most likely user-intended), then any
    `{NAME}` references not already declared.
    """
    return list(find_parameters_with_defaults(asc_path).keys())


def find_parameters_with_defaults(asc_path: str | Path) -> dict[str, str | None]:
    """Return ordered {name: default_value_string} for every detected parameter.

    `.param`-declared names carry their declared default (e.g. '12', '3.3', '{A*B}').
    Bare `{NAME}`-only references get None (no declared default found).
    """
    text = Path(asc_path).read_text(encoding='utf-8', errors='replace')
    result: dict[str, str | None] = {}
    # .param declarations first — preserve declaration order
    for line in text.splitlines():
        m = PARAM_DIRECTIVE_RE.search(line)
        if not m:
            continue
        for nm in PARAM_NAME_VALUE_RE.finditer(m.group(1)):
            name = nm.group(1)
            if name not in result:
                result[name] = nm.group(2)
    # Bare {NAME} references not already captured
    for m in BRACE_RE.finditer(text):
        name = m.group(1)
        if name not in result:
            result[name] = None
    return result


def substitute(text: str, values: dict[str, str]) -> str:
    """Apply sweep values to the schematic text.

    For each (name, value):
      1. Rewrite every `.param NAME=...` declaration to `.param NAME=value`
      2. Replace remaining bare `{NAME}` tokens with `value`

    Unknown names are left untouched.
    """
    if not values:
        return text

    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = PARAM_DIRECTIVE_RE.search(line)
        if not m:
            continue
        body_start, body_end = m.span(1)
        body = line[body_start:body_end]

        def repl_decl(mm: re.Match) -> str:
            name = mm.group(1)
            return f'{name}={values[name]}' if name in values else mm.group(0)

        new_body = PARAM_NAME_VALUE_RE.sub(repl_decl, body)
        if new_body != body:
            lines[i] = line[:body_start] + new_body + line[body_end:]
    text = ''.join(lines)

    def repl_brace(m: re.Match) -> str:
        n = m.group(1)
        return values.get(n, m.group(0))

    return BRACE_RE.sub(repl_brace, text)
