"""Parse step specs (list / lin / dec / oct) and generate value sequences."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

StepKind = Literal['list', 'lin', 'dec', 'oct']

# LTSpice engineering suffixes (case-insensitive). 'meg' must beat 'm'.
# 'r' is IEC-60062 ohms marker (no multiplier) — supported only because it's
# commonly used in resistor codes like 4R7 / 100R / R47.
_SUFFIXES: dict[str, float] = {
    't': 1e12, 'g': 1e9, 'meg': 1e6, 'k': 1e3, 'r': 1.0,
    'm': 1e-3, 'u': 1e-6, 'µ': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15,
}

# Embedded/IEC-style suffix: <left><suffix><right>
# e.g. "1k5" -> 1.5k, "4R7" -> 4.7, "R47" -> 0.47, "K47" -> 470
# `meg` is listed first so it wins over `m` in the alternation.
_ENG_SUFFIX_RE = re.compile(
    r'^([+-]?\d*\.?\d*)(meg|t|g|k|m|u|µ|n|p|f|r)(\d*)$',
    re.IGNORECASE,
)


def parse_eng(s: str) -> float:
    """Parse a number with optional engineering suffix.

    Accepts:
      - plain numbers, including scientific (1, 2.5, 1e-9, -3.3)
      - trailing suffix (1k, 2.2u, 10Meg, 4n)
      - embedded / IEC-style suffix where the suffix takes the place of the
        decimal point (1k5 = 1500, 4R7 = 4.7, K47 = 470, R47 = 0.47, 1Meg5 = 1.5e6)
    """
    raw = s.strip()
    if not raw:
        raise ValueError("Empty value")
    try:
        return float(raw)
    except ValueError:
        pass
    m = _ENG_SUFFIX_RE.match(raw)
    if not m:
        raise ValueError(f"Cannot parse number: {raw!r}")
    left, suf, right = m.group(1), m.group(2), m.group(3)
    mult = _SUFFIXES[suf.lower()]

    # Just the suffix alone (e.g. "k") — treat as 1 × suffix.
    if not left and not right:
        return mult
    # Lone sign on left is the same as "0" / "-0".
    if left in ('', '+', '-'):
        sign = -1.0 if left == '-' else 1.0
        left_abs = '0'
    else:
        sign = 1.0
        left_abs = left
    if right:
        # Embedded form: stitch <left>.<right>
        if left_abs.endswith('.'):
            left_abs = left_abs[:-1] or '0'
        combined = f'{left_abs}.{right}'
    else:
        combined = left_abs
    try:
        return sign * float(combined) * mult
    except ValueError as exc:
        raise ValueError(f"Cannot parse number: {raw!r}") from exc


def parse_list(text: str) -> list[float]:
    """Parse comma- or whitespace-separated list of values."""
    parts = [p for p in text.replace(',', ' ').split() if p]
    return [parse_eng(p) for p in parts]


@dataclass
class StepSpec:
    kind: StepKind
    values: list[float] | None = None
    start: float | None = None
    stop: float | None = None
    points: int | None = None  # N total (lin) or per-decade/octave (dec/oct)


def parse_spec(kind: StepKind, text: str) -> StepSpec:
    """Parse the user's spec string for a given kind."""
    if kind == 'list':
        return StepSpec(kind='list', values=parse_list(text))
    parts = [p for p in text.replace(',', ' ').split() if p]
    if len(parts) < 3:
        raise ValueError("Need: <start> <stop> <N>")
    try:
        points = int(parts[2])
    except ValueError:
        raise ValueError(f"N must be integer, got {parts[2]!r}")
    return StepSpec(
        kind=kind,
        start=parse_eng(parts[0]),
        stop=parse_eng(parts[1]),
        points=points,
    )


def generate(spec: StepSpec) -> list[float]:
    """Generate the value sequence for a spec."""
    if spec.kind == 'list':
        return list(spec.values or [])

    if spec.points is None or spec.points < 1:
        raise ValueError("N must be >= 1")
    if spec.start is None or spec.stop is None:
        raise ValueError("start/stop required")

    if spec.kind == 'lin':
        if spec.points == 1:
            return [spec.start]
        return [
            spec.start + (spec.stop - spec.start) * i / (spec.points - 1)
            for i in range(spec.points)
        ]

    if spec.kind in ('dec', 'oct'):
        if spec.start <= 0 or spec.stop <= 0:
            raise ValueError(f"{spec.kind} requires positive start/stop")
        base = 10 if spec.kind == 'dec' else 2
        if spec.stop == spec.start:
            return [spec.start]
        ratio_log = (math.log(spec.stop) - math.log(spec.start)) / math.log(base)
        n_total = int(round(ratio_log * spec.points)) + 1
        if n_total < 1:
            n_total = 1
        return [spec.start * base ** (i / spec.points) for i in range(n_total)]

    raise ValueError(f"Unknown kind: {spec.kind!r}")


def format_value(v: float) -> str:
    """Format a float for LTSpice substitution. Compact, unambiguous."""
    if v == 0:
        return '0'
    return f'{v:.6g}'
