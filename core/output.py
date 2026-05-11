"""Write CSV output(s) from sweep results based on per-parameter axis assignment."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Literal

from .stepping import format_value

Axis = Literal['rows', 'cols', 'file']


def _safe_filename_part(v) -> str:
    s = format_value(v) if isinstance(v, (int, float)) else str(v)
    safe = s.replace('.', 'p').replace('-', 'm').replace('+', '')
    return ''.join(c for c in safe if c.isalnum() or c in '_-') or 'x'


def _collect_measurements(results: list[dict]) -> list[str]:
    seen: list[str] = []
    s: set[str] = set()
    for r in results:
        for m in r.get('measurements', {}):
            if m not in s:
                s.add(m)
                seen.append(m)
    return seen


def write_csv(
    results: list[dict],
    axes: dict[str, Axis],
    output_dir: str | Path,
    base_name: str = 'sweep',
) -> list[Path]:
    """Write CSV file(s) based on per-parameter axis assignment.

    Each entry in `results` has shape: {'values': {name: float}, 'measurements': {name: float}, ...}
    `axes` maps each parameter name to one of 'rows' | 'cols' | 'file'.
    Returns list of written file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_params = [p for p, a in axes.items() if a == 'file']
    row_params = [p for p, a in axes.items() if a == 'rows']
    col_params = [p for p, a in axes.items() if a == 'cols']

    all_meas = _collect_measurements(results)

    # Group by file params
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        key = tuple(r['values'].get(p) for p in file_params)
        groups[key].append(r)

    written: list[Path] = []
    for fkey, grp in groups.items():
        if file_params:
            tag = '_'.join(
                f'{p}={_safe_filename_part(v)}' for p, v in zip(file_params, fkey)
            )
            fname = f'{base_name}__{tag}.csv'
        else:
            fname = f'{base_name}.csv'
        path = output_dir / fname

        row_keys = sorted({tuple(r['values'].get(p) for p in row_params) for r in grp})
        col_keys = sorted({tuple(r['values'].get(p) for p in col_params) for r in grp})

        # Header
        header: list[str] = list(row_params)
        if col_params:
            for ck in col_keys:
                ck_label = ', '.join(
                    f'{p}={format_value(v)}' for p, v in zip(col_params, ck)
                )
                for m in all_meas:
                    header.append(f'{m} @ {ck_label}')
        else:
            header.extend(all_meas)

        # Optional: include any error info as a final column when no measurements at all
        # (kept simple — errors are reported in the GUI log)

        idx: dict[tuple, dict[str, float]] = {}
        for r in grp:
            rk = tuple(r['values'].get(p) for p in row_params)
            ck = tuple(r['values'].get(p) for p in col_params)
            idx[(rk, ck)] = r.get('measurements', {})

        cks = col_keys if col_params else [()]

        with open(path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for rk in row_keys:
                row: list = [format_value(v) if isinstance(v, float) else (v if v is not None else '') for v in rk]
                for ck in cks:
                    meas = idx.get((rk, ck), {})
                    for m in all_meas:
                        v = meas.get(m, '')
                        row.append(format_value(v) if isinstance(v, float) else v)
                w.writerow(row)
        written.append(path)

    return written
