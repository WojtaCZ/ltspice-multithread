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


def run_single(
    asc_template_path: str,
    values: dict[str, float],
    ltspice_exe: str,
    timeout: float = 600,
) -> dict:
    """Run one LTSpice simulation. Returns {values, measurements, error, stderr}."""
    # Skip immediately if cancel was already requested.
    if _cancel_flag.is_set():
        return {'values': values, 'measurements': {}, 'error': 'cancelled', 'stderr': ''}

    asc_template = Path(asc_template_path)
    template_text = asc_template.read_text(encoding='utf-8', errors='replace')
    patched = schematic.substitute(template_text, _format_substitutions(values))

    tag = f'{TEMP_PREFIX}{uuid.uuid4().hex[:12]}'
    temp_asc = asc_template.parent / f'{tag}.asc'
    proc: subprocess.Popen | None = None

    try:
        temp_asc.write_text(patched, encoding='utf-8')

        # SW_SHOWMINNOACTIVE (7): start minimized without stealing focus.
        _si = subprocess.STARTUPINFO()
        _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        _si.wShowWindow = 7

        proc = subprocess.Popen(
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
            return {'values': values, 'measurements': {}, 'error': 'timeout', 'stderr': ''}

        if _cancel_flag.is_set():
            return {'values': values, 'measurements': {}, 'error': 'cancelled', 'stderr': ''}

        log_file = temp_asc.with_suffix('.log')
        measurements: dict[str, float] = {}
        error: str | None = None
        if log_file.exists():
            measurements = logparser.parse_log(log_file)
        else:
            error = f'No log file produced (exit={proc.returncode})'

        if proc.returncode != 0 and not measurements and not error:
            error = f'LTSpice exited {proc.returncode}'

        return {
            'values': values,
            'measurements': measurements,
            'error': error,
            'stderr': (stderr or '')[:500],
        }
    except Exception as e:  # pylint: disable=broad-except
        return {'values': values, 'measurements': {}, 'error': str(e), 'stderr': ''}
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
                r = {'values': futures[fut], 'measurements': {}, 'error': str(e), 'stderr': ''}
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
    return results
