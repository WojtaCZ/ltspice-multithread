"""Write CSV / MAT output(s) from sweep results based on per-parameter axis assignment."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Literal

from .stepping import format_value

Axis = Literal['rows', 'cols', 'file']

try:
    import numpy as np
    from scipy.io import savemat as _savemat
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def _safe_filename_part(v) -> str:
    s = format_value(v) if isinstance(v, (int, float)) else str(v)
    safe = s.replace('.', 'p').replace('-', 'm').replace('+', '')
    return ''.join(c for c in safe if c.isalnum() or c in '_-') or 'x'


def _collect_scalar_meas(results: list[dict]) -> list[str]:
    seen: list[str] = []
    s: set[str] = set()
    for r in results:
        for m in r.get('measurements', {}):
            if m not in s:
                s.add(m)
                seen.append(m)
    return seen


def _collect_stepped_meas(results: list[dict]) -> list[str]:
    seen: list[str] = []
    s: set[str] = set()
    for r in results:
        for m in r.get('stepped_measurements', {}):
            if m not in s:
                s.add(m)
                seen.append(m)
    return seen


def _collect_measurements(results: list[dict]) -> list[str]:
    """All measurement names (scalar first, then stepped) in encounter order."""
    seen: list[str] = []
    s: set[str] = set()
    for r in results:
        for m in r.get('measurements', {}):
            if m not in s:
                s.add(m)
                seen.append(m)
    for r in results:
        for m in r.get('stepped_measurements', {}):
            if m not in s:
                s.add(m)
                seen.append(m)
    return seen


def _get_step_combos(results: list[dict]) -> list[dict[str, float]]:
    """Return the most complete step_combos list found across all results."""
    best: list[dict[str, float]] = []
    for r in results:
        sc = r.get('step_combos', [])
        if len(sc) > len(best):
            best = sc
    return best


def _step_label(combo: dict[str, float]) -> str:
    return ','.join(f'{k}={format_value(v)}' for k, v in combo.items())


def write_csv(
    results: list[dict],
    axes: dict[str, Axis],
    output_dir: str | Path,
    base_name: str = 'sweep',
) -> list[Path]:
    """Write CSV file(s) based on per-parameter axis assignment.

    Each entry in `results` has shape: {'values': {name: float}, 'measurements': {name: float},
    'stepped_measurements': {name: [float,...]}, 'step_combos': [{name: float}, ...], ...}
    `axes` maps each parameter name to one of 'rows' | 'cols' | 'file'.
    Returns list of written file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_params = [p for p, a in axes.items() if a == 'file']
    row_params = [p for p, a in axes.items() if a == 'rows']
    col_params = [p for p, a in axes.items() if a == 'cols']

    scalar_names = _collect_scalar_meas(results)
    stepped_names = _collect_stepped_meas(results)
    step_combos_all = _get_step_combos(results)

    # Build the flat list of column measurement keys.
    # Scalar: just the name.  Stepped: "name@step_label" for each step.
    col_meas_keys: list[str] = list(scalar_names)
    for m in stepped_names:
        for combo in step_combos_all:
            col_meas_keys.append(f'{m}@{_step_label(combo)}')

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

        header: list[str] = list(row_params)
        if col_params:
            for ck in col_keys:
                ck_label = ', '.join(
                    f'{p}={format_value(v)}' for p, v in zip(col_params, ck)
                )
                for mk in col_meas_keys:
                    header.append(f'{mk} @ {ck_label}')
        else:
            header.extend(col_meas_keys)

        # Build per-(rk, ck) flat measurement dict that includes stepped values.
        idx: dict[tuple, dict[str, float | str]] = {}
        for r in grp:
            rk = tuple(r['values'].get(p) for p in row_params)
            ck = tuple(r['values'].get(p) for p in col_params)
            flat: dict[str, float | str] = dict(r.get('measurements', {}))
            sc = r.get('step_combos', step_combos_all)
            for meas_name, vals in r.get('stepped_measurements', {}).items():
                for si, val in enumerate(vals):
                    if si < len(sc):
                        flat[f'{meas_name}@{_step_label(sc[si])}'] = val
            idx[(rk, ck)] = flat

        cks = col_keys if col_params else [()]

        with open(path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for rk in row_keys:
                row: list = [format_value(v) if isinstance(v, float) else (v if v is not None else '') for v in rk]
                for ck in cks:
                    meas = idx.get((rk, ck), {})
                    for mk in col_meas_keys:
                        v = meas.get(mk, '')
                        row.append(format_value(v) if isinstance(v, float) else v)
                w.writerow(row)
        written.append(path)

    return written


def _mat_safe_name(name: str) -> str:
    """Sanitise a string to a valid MATLAB/Octave variable name."""
    s = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if s and s[0].isdigit():
        s = 'v_' + s
    return s or 'v'


def write_mat(
    results: list[dict],
    axes: dict[str, Axis],
    output_dir: str | Path,
    base_name: str = 'sweep',
) -> list[Path]:
    """Write Octave/MATLAB .mat file(s) from sweep results.

    Runner-swept parameters and any .step parameters found in the schematics
    all become independent dimensions of the output arrays.

    Variables written into each .mat:
      - One vector per dimension parameter (unique sorted values)
      - One N-D array per measurement, indexed by all dimension vectors
      - ``param_order``: char array of dimension names in index order
          (runner params first, then schematic .step params)

    Requires scipy (scipy.io.savemat) and numpy.
    """
    if not SCIPY_AVAILABLE:
        raise ImportError(
            "scipy is required for .mat export.  Install it with:  pip install scipy"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_params = [p for p, a in axes.items() if a == 'file']
    # All non-file swept params become array dimensions, in declaration order.
    dim_params = [p for p, a in axes.items() if a != 'file']

    scalar_names = _collect_scalar_meas(results)
    stepped_names = _collect_stepped_meas(results)
    # Deduplicated union: scalar first, then any stepped names not already present.
    scalar_set = set(scalar_names)
    all_meas = scalar_names + [m for m in stepped_names if m not in scalar_set]

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
            fname = f'{base_name}__{tag}.mat'
        else:
            fname = f'{base_name}.mat'
        path = output_dir / fname

        # Unique sorted values for each runner dimension parameter.
        dim_values: dict[str, list[float]] = {}
        for p in dim_params:
            vals = sorted({r['values'][p] for r in grp if p in r['values']})
            dim_values[p] = vals

        runner_shape: tuple[int, ...] = (
            tuple(len(dim_values[p]) for p in dim_params) if dim_params else ()
        )
        idx_map: dict[str, dict[float, int]] = (
            {p: {v: i for i, v in enumerate(vals)} for p, vals in dim_values.items()}
            if dim_params else {}
        )

        # Step params from the schematic .step directives (consistent across all runs).
        step_combos_all = _get_step_combos(grp)
        step_param_names: list[str] = list(step_combos_all[0].keys()) if step_combos_all else []
        step_param_values: dict[str, list[float]] = {}
        step_idx_map: dict[str, dict[float, int]] = {}
        if step_param_names:
            for key in step_param_names:
                uniq = sorted({c[key] for c in step_combos_all})
                step_param_values[key] = uniq
                step_idx_map[key] = {v: i for i, v in enumerate(uniq)}

        step_shape: tuple[int, ...] = tuple(len(step_param_values[p]) for p in step_param_names)

        # All measurement arrays share the same shape = runner_shape + step_shape.
        full_shape = runner_shape + step_shape
        if not full_shape:
            full_shape = (1,)

        meas_arrays: dict[str, object] = {m: np.full(full_shape, np.nan) for m in all_meas}

        for r in grp:
            # Runner-param indices into meas_arrays.
            if dim_params:
                runner_indices: tuple[int, ...] = tuple(
                    idx_map[p][r['values'][p]]
                    for p in dim_params
                    if p in r['values'] and r['values'][p] in idx_map[p]
                )
                if len(runner_indices) != len(dim_params):
                    continue
            else:
                runner_indices = ()

            # Scalar measurements: broadcast across all step positions.
            for m in scalar_names:
                val = r.get('measurements', {}).get(m)
                if val is None:
                    continue
                if step_param_names:
                    sl: tuple = runner_indices + (slice(None),) * len(step_param_names)
                    meas_arrays[m][sl] = val  # type: ignore[index]
                else:
                    meas_arrays[m][runner_indices if runner_indices else (0,)] = val  # type: ignore[index]

            # Stepped measurements: one value per step combo.
            r_step_combos = r.get('step_combos', step_combos_all)
            for m in stepped_names:
                vals_list = r.get('stepped_measurements', {}).get(m, [])
                for si, val in enumerate(vals_list):
                    if si >= len(r_step_combos):
                        break
                    combo = r_step_combos[si]
                    try:
                        step_indices: tuple[int, ...] = tuple(
                            step_idx_map[p][combo[p]] for p in step_param_names
                        )
                    except KeyError:
                        continue
                    full_index = runner_indices + step_indices
                    meas_arrays[m][full_index] = val  # type: ignore[index]

        mat: dict[str, object] = {}
        for p in dim_params:
            mat[_mat_safe_name(p)] = np.array(dim_values[p])
        for p in step_param_names:
            mat[_mat_safe_name(p)] = np.array(step_param_values[p])
        for m in all_meas:
            mat[_mat_safe_name(m)] = meas_arrays[m]
        mat['param_order'] = np.array(
            [_mat_safe_name(p) for p in dim_params + step_param_names], dtype=object
        )

        _savemat(str(path), mat, do_compression=True)
        written.append(path)

    return written
