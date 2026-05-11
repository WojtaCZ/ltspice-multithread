"""Parse LTSpice .log files to extract .meas results."""
from __future__ import annotations

import re
from pathlib import Path

_NUM = r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?'

# Two patterns covering the common .meas output forms:
#   name: func(expr)=value FROM ...
#   name: trig=value targ=value  (we take the first value)
#   name=value
_PAT_FUNC = re.compile(rf'^\s*(\w+)\s*:\s*[^=\n]*=\s*({_NUM})')
_PAT_EQ = re.compile(rf'^\s*(\w+)\s*=\s*({_NUM})\s*$')


def parse_log(log_path: str | Path) -> dict[str, float]:
    """Extract {meas_name: value} from a .log file. Best-effort; skips unparseable lines."""
    text = Path(log_path).read_text(encoding='utf-8', errors='replace')
    out: dict[str, float] = {}
    for line in text.splitlines():
        for pat in (_PAT_FUNC, _PAT_EQ):
            m = pat.match(line)
            if m:
                try:
                    out[m.group(1)] = float(m.group(2))
                except ValueError:
                    pass
                break
    return out
