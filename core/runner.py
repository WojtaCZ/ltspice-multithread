"""Execute LTSpice batch simulations in parallel."""
from __future__ import annotations

import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import logparser, schematic, stepping

TEMP_PREFIX = 'ltsweep_'

# Windows ERROR_PAGEFILE_TOO_SMALL — raised by Popen when the commit limit
# (RAM + pagefile) is temporarily exhausted even if physical RAM is free.
# Retrying after a short back-off lets Windows reclaim commit space.
_WINERROR_PAGEFILE = 1455
_POPEN_RETRIES = 3   # additional attempts after the first failure
_POPEN_RETRY_BASE = 2.0  # seconds; delay doubles each attempt (2 → 4 → 8)

# --- Process registry for instant cancel ---
_active_procs: set[subprocess.Popen] = set()
_active_procs_lock = threading.Lock()
_cancel_flag = threading.Event()


def kill_all_active() -> None:
    """Kill every LTSpice process that is currently running."""
    _cancel_flag.set()
    with _active_procs_lock:
        procs = list(_active_procs)
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except OSError:
            pass


def _register(proc: subprocess.Popen) -> None:
    with _active_procs_lock:
        _active_procs.add(proc)


def _deregister(proc: subprocess.Popen) -> None:
    with _active_procs_lock:
        _active_procs.discard(proc)


def _format_substitutions(values: dict[str, float]) -> dict[str, str]:
    return {k: stepping.format_value(v) for k, v in values.items()}


def _popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    """Spawn a process, retrying on Windows ERROR_PAGEFILE_TOO_SMALL (1455)."""
    last_exc: OSError | None = None
    for attempt in range(_POPEN_RETRIES + 1):
        if attempt:
            time.sleep(_POPEN_RETRY_BASE * (2 ** (attempt - 1)))
        try:
            return subprocess.Popen(cmd, **kwargs)
        except OSError as exc:
            if getattr(exc, 'winerror', None) != _WINERROR_PAGEFILE:
                raise
            last_exc = exc
    raise last_exc  # type: ignore[misc]


def _cleanup(parent: Path, tag: str, retries: int = 5, delay: float = 0.3) -> None:
    """Delete every file whose name starts with `tag` in `parent`.

    Retries with a short delay to handle Windows releasing file handles after
    a process is killed.
    """
    targets = list(parent.glob(f'{tag}*'))
    for _ in range(retries):
        still_locked = []
        for f in targets:
            try:
                if f.is_file():
                    f.unlink()
            except OSError:
                still_locked.append(f)
        targets = still_locked
        if not targets:
            break
        time.sleep(delay)


_EMPTY_RESULT = {'measurements': {}, 'stepped_measurements': {}, 'step_combos': []}


def run_single(
    asc_template_path: str,
    values: dict[str, float],
    ltspice_exe: str,
    timeout: float = 600,
) -> dict:
    """Run one LTSpice simulation. Returns {values, measurements, stepped_measurements, step_combos, error, stderr}."""
    # Skip immediately if cancel was already requested.
    if _cancel_flag.is_set():
        return {'values': values, **_EMPTY_RESULT, 'error': 'cancelled', 'stderr': ''}

    asc_template = Path(asc_template_path)
    template_text = asc_template.read_text(encoding='utf-8', errors='replace')
    patched = schematic.substitute(template_text, _format_substitutions(values))

    tag = f'{TEMP_PREFIX}{uuid.uuid4().hex[:12]}'
    temp_asc = asc_template.parent / f'{tag}.asc'
    proc: subprocess.Popen | None = None

    try:
        temp_asc.write_text(patched, encoding='utf-8')

        # SW_HIDE (0): suppress the window entirely in batch mode so that
        # LTSpice cannot call SetForegroundWindow and steal keyboard focus.
        _si = subprocess.STARTUPINFO()
        _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        _si.wShowWindow = 0

        proc = _popen(
            [ltspice_exe, '-b', str(temp_asc)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(asc_template.parent),
            startupinfo=_si,
        )
        _register(proc)

        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return {'values': values, **_EMPTY_RESULT, 'error': 'timeout', 'stderr': ''}

        if _cancel_flag.is_set():
            return {'values': values, **_EMPTY_RESULT, 'error': 'cancelled', 'stderr': ''}

        log_file = temp_asc.with_suffix('.log')
        measurements: dict[str, float] = {}
        stepped_measurements: dict[str, list[float]] = {}
        step_combos: list[dict[str, float]] = []
        error: str | None = None
        if log_file.exists():
            log_result = logparser.parse_log(log_file)
            measurements = log_result.scalar
            stepped_measurements = log_result.stepped
            step_combos = log_result.step_combos
            # LTSpice lowercases .step param names in the log; restore the
            # original case from the schematic template.
            step_names = schematic.find_step_param_names(template_text)
            if step_names:
                case_map = {n.lower(): n for n in step_names}
                step_combos = [
                    {case_map.get(k.lower(), k): v for k, v in combo.items()}
                    for combo in step_combos
                ]
        else:
            error = f'No log file produced (exit={proc.returncode})'

        if proc.returncode != 0 and not measurements and not stepped_measurements and not error:
            error = f'LTSpice exited {proc.returncode}'

        return {
            'values': values,
            'measurements': measurements,
            'stepped_measurements': stepped_measurements,
            'step_combos': step_combos,
            'error': error,
            'stderr': (stderr or '')[:500],
        }
    except Exception as e:  # pylint: disable=broad-except
        return {'values': values, **_EMPTY_RESULT, 'error': str(e), 'stderr': ''}
    finally:
        if proc is not None:
            _deregister(proc)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.communicate(timeout=10)
                except Exception:  # pylint: disable=broad-except
                    pass
        _cleanup(asc_template.parent, tag)


def run_all(
    asc_path: str,
    value_combos: list[dict[str, float]],
    ltspice_exe: str,
    max_workers: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
    on_result: Callable[[dict], None] | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = 600,
) -> list[dict]:
    """Run all parameter combinations in parallel. Returns list of result dicts."""
    _cancel_flag.clear()
    results: list[dict] = []
    total = len(value_combos)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        futures = {
            ex.submit(run_single, asc_path, combo, ltspice_exe, timeout): combo
            for combo in value_combos
        }
        for fut in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                _cancel_flag.set()
                continue
            try:
                r = fut.result()
            except Exception as e:  # pylint: disable=broad-except
                r = {'values': futures[fut], **_EMPTY_RESULT, 'error': str(e), 'stderr': ''}
            results.append(r)
            if on_result is not None:
                try:
                    on_result(r)
                except Exception:  # pylint: disable=broad-except
                    pass
            if on_progress is not None:
                try:
                    on_progress(len(results), total)
                except Exception:  # pylint: disable=broad-except
                    pass

    # All workers are done; do a final sweep for any files Windows kept locked
    # while LTSpice processes were still alive (common with .db cache files).
    _cleanup(Path(asc_path).parent, TEMP_PREFIX, retries=10, delay=0.5)

    return results
