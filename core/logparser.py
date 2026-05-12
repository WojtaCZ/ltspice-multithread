"""Parse LTSpice .log files to extract .meas results."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_NUM = r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?'

# Scalar measurement patterns:
#   name: func(expr)=value ...
#   name=value ...   (trailing " at 1.23us" is allowed)
_PAT_FUNC = re.compile(rf'^\s*(\w+)\s*:\s*[^=\n]*=\s*({_NUM})')
_PAT_EQ   = re.compile(rf'^\s*(\w+)\s*=\s*({_NUM})')

# ".step name=val  name2=val2 ..."  lines in the log header
_PAT_STEP = re.compile(r'^\s*\.step\s+(.+)$', re.IGNORECASE)
# "Measurement: name" block header
_PAT_MEAS = re.compile(r'^\s*Measurement:\s*(\w+)\s*$', re.IGNORECASE)


@dataclass
class LogResult:
    """Parsed content of one LTSpice .log file."""
    scalar: dict[str, float] = field(default_factory=dict)
    # stepped[name] = [val_step1, val_step2, ...] in step-index order
    stepped: dict[str, list[float]] = field(default_factory=dict)
    # step_combos[i] = {param_name: value} for step i (0-based)
    step_combos: list[dict[str, float]] = field(default_factory=list)


def parse_log(log_path: str | Path) -> LogResult:
    """Extract scalar and stepped .meas results plus step-parameter combos."""
    text = Path(log_path).read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    result = LogResult()

    # Phase 1: collect one .step line per executed step combination.
    # Format: ".step param1=val1 param2=val2 ..."
    for line in lines:
        m = _PAT_STEP.match(line)
        if m:
            combo: dict[str, float] = {}
            for kv in re.finditer(rf'(\w+)=({_NUM})', m.group(1)):
                try:
                    combo[kv.group(1)] = float(kv.group(2))
                except ValueError:
                    pass
            if combo:
                result.step_combos.append(combo)

    # Phase 2: parse measurements.
    # Stepped block format (LTSpice uses this when .step is active):
    #   Measurement: name
    #     step\texpr\tat
    #        1\t1.23\t4.56e-7
    #        2\t...
    # Scalar format:
    #   name=value [at ...]
    i = 0
    while i < len(lines):
        line = lines[i]

        mh = _PAT_MEAS.match(line)
        if mh:
            meas_name = mh.group(1)
            i += 2  # skip the column-header row
            vals: list[float] = []
            while i < len(lines):
                parts = lines[i].split('\t')
                if len(parts) < 2:
                    break
                try:
                    int(parts[0])  # first column must be a step integer
                except ValueError:
                    break
                try:
                    vals.append(float(parts[1]))
                except ValueError:
                    vals.append(float('nan'))
                i += 1
            if vals:
                result.stepped[meas_name] = vals
            continue

        for pat in (_PAT_FUNC, _PAT_EQ):
            mm = pat.match(line)
            if mm:
                try:
                    result.scalar[mm.group(1)] = float(mm.group(2))
                except ValueError:
                    pass
                break

        i += 1

    return result
