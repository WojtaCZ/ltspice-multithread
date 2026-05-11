"""LTSpice multi-sweep GUI (Tkinter)."""
from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent))

from core import output, runner, schematic, stepping  # noqa: E402

CONFIG_VERSION = 1
DEFAULT_CONFIG_EXT = '.sweep.json'


def find_ltspice_exe() -> str | None:
    candidates = [
        r'C:\Program Files\ADI\LTspice\LTspice.exe',
        str(Path.home() / r'AppData\Local\Programs\ADI\LTspice\LTspice.exe'),
        r'C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe',
        r'C:\Program Files (x86)\LTC\LTspiceXVII\XVIIx64.exe',
        r'C:\Program Files (x86)\LTC\LTspiceIV\scad3.exe',
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title('LTSpice Multi-Sweep')
        root.geometry('1000x680')

        self.params: list[dict] = []
        self._cancel = threading.Event()

        self._build_ui()
        self.exe_var.set(find_ltspice_exe() or '')

        root.bind_all('<Control-s>', lambda _e: self.save_setup())
        root.bind_all('<Control-S>', lambda _e: self.save_setup())
        root.bind_all('<Control-o>', lambda _e: self.load_setup())
        root.bind_all('<Control-O>', lambda _e: self.load_setup())

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill='x')
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text='Schematic (.asc):').grid(row=0, column=0, sticky='w', pady=2)
        self.asc_path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.asc_path_var).grid(row=0, column=1, sticky='ew', padx=5)
        ttk.Button(top, text='Browse…', command=self.browse_asc).grid(row=0, column=2)
        ttk.Button(top, text='Reload', command=self.load_params).grid(row=0, column=3, padx=(5, 0))

        ttk.Label(top, text='LTSpice executable:').grid(row=1, column=0, sticky='w', pady=2)
        self.exe_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.exe_var).grid(row=1, column=1, sticky='ew', padx=5)
        ttk.Button(top, text='Browse…', command=self.browse_exe).grid(row=1, column=2)

        ttk.Label(top, text='Output directory:').grid(row=2, column=0, sticky='w', pady=2)
        self.out_var = tk.StringVar(value=str(Path.cwd()))
        ttk.Entry(top, textvariable=self.out_var).grid(row=2, column=1, sticky='ew', padx=5)
        ttk.Button(top, text='Browse…', command=self.browse_out).grid(row=2, column=2)

        mid = ttk.LabelFrame(self.root, text='Parameters (double-click row to edit)', padding=10)
        mid.pack(fill='both', expand=True, padx=10, pady=5)

        cols = ('Name', 'Kind', 'Spec', 'Axis', 'Preview')
        self.tree = ttk.Treeview(mid, columns=cols, show='headings', height=10)
        for c, w in zip(cols, (120, 70, 220, 80, 420)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True, side='left')
        self.tree.tag_configure('skipped', foreground='#999')

        sb = ttk.Scrollbar(mid, orient='vertical', command=self.tree.yview)
        sb.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=sb.set)
        self.tree.bind('<Double-1>', self.edit_selected)
        self.tree.bind('<Return>', self.edit_selected)

        hint = ttk.Label(
            self.root,
            foreground='#666',
            text=(
                'Kinds: list ("1k 2.2k 10k") · lin/dec/oct ("start stop N"). '
                'Axis — = skip (keep schematic default) · rows · cols · file (separate CSV per value).'
            ),
        )
        hint.pack(anchor='w', padx=10)

        bot = ttk.Frame(self.root, padding=(10, 5, 10, 0))
        bot.pack(fill='x')

        ttk.Label(bot, text='Workers:').grid(row=0, column=0)
        self.workers_var = tk.IntVar(value=max(1, (os.cpu_count() or 4) // 2))
        ttk.Spinbox(bot, from_=1, to=64, textvariable=self.workers_var, width=5).grid(
            row=0, column=1, padx=(2, 15)
        )

        ttk.Label(bot, text='Output basename:').grid(row=0, column=2)
        self.basename_var = tk.StringVar(value='sweep')
        ttk.Entry(bot, textvariable=self.basename_var, width=20).grid(row=0, column=3, padx=(2, 15))

        ttk.Label(bot, text='Timeout (s):').grid(row=0, column=4)
        self.timeout_var = tk.IntVar(value=600)
        ttk.Spinbox(bot, from_=10, to=86400, textvariable=self.timeout_var, width=7).grid(
            row=0, column=5, padx=(2, 15)
        )

        ttk.Button(bot, text='Save setup…', command=self.save_setup).grid(row=0, column=6, padx=2)
        ttk.Button(bot, text='Load setup…', command=self.load_setup).grid(row=0, column=7, padx=2)

        ttk.Separator(bot, orient='vertical').grid(row=0, column=8, sticky='ns', padx=8)

        self.fmt_csv_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bot, text='CSV', variable=self.fmt_csv_var).grid(row=0, column=9, padx=2)

        self.fmt_mat_var = tk.BooleanVar(value=False)
        mat_cb = ttk.Checkbutton(bot, text='MAT (Octave)', variable=self.fmt_mat_var)
        mat_cb.grid(row=0, column=10, padx=2)
        if not output.SCIPY_AVAILABLE:
            self.fmt_mat_var.set(False)
            mat_cb.config(state='disabled')
            mat_cb.config(text='MAT (needs scipy)')

        ttk.Separator(bot, orient='vertical').grid(row=0, column=11, sticky='ns', padx=8)

        self.run_btn = ttk.Button(bot, text='Run sweep', command=self.run_sweep)
        self.run_btn.grid(row=0, column=12)

        self.cancel_btn = ttk.Button(bot, text='Cancel', command=self.cancel_sweep, state='disabled')
        self.cancel_btn.grid(row=0, column=13, padx=5)

        self.status_var = tk.StringVar(value='Idle')
        ttk.Label(bot, textvariable=self.status_var).grid(row=0, column=14, padx=10, sticky='w')
        bot.columnconfigure(14, weight=1)

        # Progress bar on its own row, full width
        prog_frame = ttk.Frame(self.root, padding=(10, 2, 10, 8))
        prog_frame.pack(fill='x')
        self.progress = ttk.Progressbar(prog_frame, mode='determinate')
        self.progress.pack(fill='x')

        log_frame = ttk.LabelFrame(self.root, text='Log', padding=5)
        log_frame.pack(fill='both', expand=False, padx=10, pady=(0, 10))
        self.log_txt = tk.Text(log_frame, height=8, wrap='word', state='disabled')
        self.log_txt.pack(fill='both', expand=True, side='left')
        sb2 = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_txt.yview)
        sb2.pack(side='right', fill='y')
        self.log_txt.config(yscrollcommand=sb2.set)

    # ----- File pickers -----
    def browse_asc(self):
        p = filedialog.askopenfilename(
            filetypes=[('LTSpice schematic', '*.asc'), ('All files', '*.*')]
        )
        if p:
            self.asc_path_var.set(p)
            self.load_params()

    def browse_exe(self):
        p = filedialog.askopenfilename(
            filetypes=[('Executable', '*.exe'), ('All files', '*.*')]
        )
        if p:
            self.exe_var.set(p)

    def browse_out(self):
        p = filedialog.askdirectory()
        if p:
            self.out_var.set(p)

    # ----- Param management -----
    def load_params(self):
        path = self.asc_path_var.get()
        if not path or not Path(path).exists():
            return
        try:
            params_defaults = schematic.find_parameters_with_defaults(path)
        except Exception as e:  # pylint: disable=broad-except
            messagebox.showerror('Error', f'Failed to read schematic: {e}')
            return
        if not params_defaults:
            self.log('No parameters found in schematic.')
        existing = {p['name']: p for p in self.params}
        self.params = []
        for name, default in params_defaults.items():
            if name in existing:
                self.params.append(existing[name])
            else:
                # New param: default spec from schematic value, axis=— (skip)
                self.params.append({
                    'name': name,
                    'kind': 'list',
                    'spec': default if default is not None else '1',
                    'axis': '—',
                })
        self.refresh_tree()
        names = list(params_defaults.keys())
        self.log(f'Loaded {len(names)} parameter(s): {", ".join(names) or "—"}')

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for p in self.params:
            skipped = p['axis'] == '—'
            preview = '(schematic default)' if skipped else self.preview(p)
            tag = ('skipped',) if skipped else ()
            self.tree.insert(
                '',
                'end',
                values=(p['name'], p['kind'], p['spec'], p['axis'], preview),
                tags=tag,
            )

    def preview(self, p) -> str:
        try:
            vals = stepping.generate(stepping.parse_spec(p['kind'], p['spec']))
            if not vals:
                return '(no values)'
            if len(vals) > 6:
                head = ', '.join(stepping.format_value(v) for v in vals[:3])
                return f'{head}, …, {stepping.format_value(vals[-1])}  [{len(vals)} pts]'
            return ', '.join(stepping.format_value(v) for v in vals)
        except Exception as e:  # pylint: disable=broad-except
            return f'ERR: {e}'

    def edit_selected(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        self._open_editor(self.params[idx])

    def _open_editor(self, p):
        dlg = tk.Toplevel(self.root)
        dlg.title(f'Edit "{p["name"]}"')
        dlg.geometry('520x270')
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=p['name'], font=('TkDefaultFont', 11, 'bold')).pack(pady=(10, 5))

        body = ttk.Frame(dlg, padding=10)
        body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text='Kind:').grid(row=0, column=0, sticky='w', pady=3)
        kind_var = tk.StringVar(value=p['kind'])
        ttk.Combobox(
            body, textvariable=kind_var,
            values=['list', 'lin', 'dec', 'oct'], state='readonly', width=12,
        ).grid(row=0, column=1, sticky='w', pady=3)

        ttk.Label(body, text='Spec:').grid(row=1, column=0, sticky='w', pady=3)
        spec_var = tk.StringVar(value=p['spec'])
        ttk.Entry(body, textvariable=spec_var).grid(row=1, column=1, sticky='ew', pady=3)

        hint_var = tk.StringVar()
        ttk.Label(body, textvariable=hint_var, foreground='#666').grid(
            row=2, column=1, sticky='w', pady=3
        )

        def upd_hint(*_):
            hint_var.set({
                'list': 'space/comma-separated values · "1k 2.2k 4.7k 10k"',
                'lin': 'start stop N · "1k 10k 10"',
                'dec': 'start stop pts/decade · "1 1Meg 5"',
                'oct': 'start stop pts/octave · "1 1k 5"',
            }[kind_var.get()])

        kind_var.trace_add('write', upd_hint)
        upd_hint()

        ttk.Label(body, text='Axis:').grid(row=3, column=0, sticky='w', pady=3)
        axis_var = tk.StringVar(value=p['axis'])
        ttk.Combobox(
            body, textvariable=axis_var,
            values=['—', 'rows', 'cols', 'file'], state='readonly', width=12,
        ).grid(row=3, column=1, sticky='w', pady=3)

        preview_var = tk.StringVar()
        ttk.Label(body, textvariable=preview_var, foreground='#048', wraplength=460).grid(
            row=4, column=0, columnspan=2, sticky='w', pady=(8, 0)
        )

        def upd_preview(*_):
            tmp = {
                'name': p['name'],
                'kind': kind_var.get(),
                'spec': spec_var.get(),
                'axis': axis_var.get(),
            }
            preview_var.set('Preview: ' + self.preview(tmp))

        kind_var.trace_add('write', upd_preview)
        spec_var.trace_add('write', upd_preview)
        upd_preview()

        btns = ttk.Frame(dlg, padding=(0, 5))
        btns.pack(pady=8)

        def save():
            p['kind'] = kind_var.get()
            p['spec'] = spec_var.get()
            p['axis'] = axis_var.get()
            self.refresh_tree()
            dlg.destroy()

        ttk.Button(btns, text='OK', command=save).pack(side='left', padx=5)
        ttk.Button(btns, text='Cancel', command=dlg.destroy).pack(side='left', padx=5)
        dlg.bind('<Return>', lambda _e: save())
        dlg.bind('<Escape>', lambda _e: dlg.destroy())

    # ----- Run -----
    def cancel_sweep(self):
        self._cancel.set()
        runner.kill_all_active()
        self.status_var.set('Cancelling…')
        self.log('Cancel requested — killing in-flight processes.')

    def run_sweep(self):
        if not self.asc_path_var.get() or not Path(self.asc_path_var.get()).exists():
            messagebox.showerror('Error', 'Select a valid schematic first.')
            return
        if not self.exe_var.get() or not Path(self.exe_var.get()).exists():
            messagebox.showerror('Error', 'Select LTSpice executable first.')
            return

        value_lists: dict[str, list[float]] = {}
        for p in self.params:
            if p['axis'] == '—':
                continue  # keep schematic default, do not substitute
            try:
                vals = stepping.generate(stepping.parse_spec(p['kind'], p['spec']))
                if not vals:
                    raise ValueError('produced no values')
                value_lists[p['name']] = vals
            except Exception as e:  # pylint: disable=broad-except
                messagebox.showerror('Error', f'Parameter {p["name"]}: {e}')
                return

        names = list(value_lists.keys())
        if names:
            combos: list[dict[str, float]] = [
                dict(zip(names, vs))
                for vs in itertools.product(*(value_lists[n] for n in names))
            ]
        else:
            combos = [{}]
        total = len(combos)

        self._cancel.clear()
        self.run_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        self.progress['maximum'] = total
        self.progress['value'] = 0
        self.status_var.set(f'Running 0/{total}')
        self.log(f'Starting sweep: {total} combinations, {self.workers_var.get()} workers.')

        def on_progress(done, tot):
            self.root.after(0, lambda: self._on_progress(done, tot))

        def on_result(r):
            err = r.get('error')
            if err:
                self.root.after(0, lambda: self.log(f'  ! {self._fmt_run(r["values"])} → {err}'))

        def worker():
            try:
                axes = {p['name']: p['axis'] for p in self.params if p['axis'] != '—'}
                results = runner.run_all(
                    self.asc_path_var.get(),
                    combos,
                    self.exe_var.get(),
                    max_workers=self.workers_var.get(),
                    on_progress=on_progress,
                    on_result=on_result,
                    cancel_event=self._cancel,
                    timeout=self.timeout_var.get(),
                )
                if self._cancel.is_set():
                    self.root.after(0, lambda: self._finish('Cancelled', None))
                    return
                out_dir = Path(self.out_var.get())
                bname = self.basename_var.get() or 'sweep'
                files: list[Path] = []
                export_errors: list[str] = []

                if fmt_csv:
                    files += output.write_csv(results, axes, out_dir, bname)
                if fmt_mat:
                    try:
                        files += output.write_mat(results, axes, out_dir, bname)
                    except Exception as mat_err:  # pylint: disable=broad-except
                        export_errors.append(f'MAT export failed: {mat_err}')

                ok = sum(1 for r in results if not r.get('error') and r.get('measurements'))
                err_count = sum(1 for r in results if r.get('error'))
                msg = f'Done. {ok} ok, {err_count} errors. Wrote {len(files)} file(s).'
                if export_errors:
                    msg += ' (' + '; '.join(export_errors) + ')'
                detail = '\n'.join(f'  {f}' for f in files)
                self.root.after(0, lambda: self._finish(msg, detail))
            except Exception as e:  # pylint: disable=broad-except
                import traceback
                tb = traceback.format_exc()
                self.root.after(0, lambda: self._finish(f'Failed: {e}', tb))

        fmt_csv = self.fmt_csv_var.get()
        fmt_mat = self.fmt_mat_var.get()
        threading.Thread(target=worker, daemon=True).start()

    def _fmt_run(self, values: dict[str, float]) -> str:
        return ', '.join(f'{k}={stepping.format_value(v)}' for k, v in values.items())

    def _on_progress(self, done, tot):
        self.progress['value'] = done
        self.status_var.set(f'Running {done}/{tot}')

    def _finish(self, msg, detail=None):
        self.run_btn.config(state='normal')
        self.cancel_btn.config(state='disabled')
        self.status_var.set(msg)
        self.log(msg)
        if detail:
            self.log(detail)

    def log(self, text: str):
        self.log_txt.config(state='normal')
        self.log_txt.insert('end', text + '\n')
        self.log_txt.see('end')
        self.log_txt.config(state='disabled')

    # ----- Save / load setup -----
    def _initial_config_dir(self) -> str:
        for p in (self.asc_path_var.get(), self.out_var.get()):
            if p and Path(p).exists():
                d = Path(p)
                return str(d if d.is_dir() else d.parent)
        return str(Path.cwd())

    def save_setup(self):
        path = filedialog.asksaveasfilename(
            title='Save sweep setup',
            defaultextension=DEFAULT_CONFIG_EXT,
            initialdir=self._initial_config_dir(),
            filetypes=[('LTSpice sweep config', '*.json *.sweep.json'), ('All files', '*.*')],
        )
        if not path:
            return
        cfg = {
            'version': CONFIG_VERSION,
            'schematic': self.asc_path_var.get(),
            'ltspice_exe': self.exe_var.get(),
            'output_dir': self.out_var.get(),
            'basename': self.basename_var.get(),
            'workers': self.workers_var.get(),
            'timeout': self.timeout_var.get(),
            'params': self.params,
        }
        try:
            Path(path).write_text(json.dumps(cfg, indent=2), encoding='utf-8')
        except OSError as e:
            messagebox.showerror('Error', f'Could not save: {e}')
            return
        self.log(f'Saved setup → {path}')

    def load_setup(self):
        path = filedialog.askopenfilename(
            title='Load sweep setup',
            initialdir=self._initial_config_dir(),
            filetypes=[('LTSpice sweep config', '*.json *.sweep.json'), ('All files', '*.*')],
        )
        if not path:
            return
        try:
            cfg = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror('Error', f'Could not load: {e}')
            return

        if not isinstance(cfg, dict) or 'params' not in cfg:
            messagebox.showerror('Error', 'File does not look like a sweep config.')
            return

        self.asc_path_var.set(cfg.get('schematic', ''))
        exe = cfg.get('ltspice_exe', '')
        if exe and not Path(exe).exists():
            fallback = find_ltspice_exe() or ''
            if fallback:
                self.log(f'Saved LTSpice exe missing ({exe}); using {fallback}')
                exe = fallback
        self.exe_var.set(exe)
        self.out_var.set(cfg.get('output_dir', str(Path.cwd())))
        self.basename_var.set(cfg.get('basename', 'sweep'))
        self.workers_var.set(int(cfg.get('workers', max(1, (os.cpu_count() or 4) // 2))))
        self.timeout_var.set(int(cfg.get('timeout', 600)))

        params = cfg.get('params') or []
        normalized: list[dict] = []
        for p in params:
            if not isinstance(p, dict) or 'name' not in p:
                continue
            normalized.append({
                'name': str(p['name']),
                'kind': p.get('kind', 'list'),
                'spec': str(p.get('spec', '1')),
                'axis': p.get('axis', 'rows'),
            })
        self.params = normalized
        self.refresh_tree()
        self.log(f'Loaded setup ← {path} ({len(self.params)} param(s))')

        # If schematic exists, sanity-check that saved params still match it.
        asc = self.asc_path_var.get()
        if asc and Path(asc).exists():
            try:
                detected = set(schematic.find_parameters(asc))
                saved = {p['name'] for p in self.params}
                missing = sorted(saved - detected)
                extra = sorted(detected - saved)
                if missing:
                    self.log(f'  warning: saved params not in schematic: {", ".join(missing)}')
                if extra:
                    self.log(f'  note: schematic has new params not in setup: {", ".join(extra)}')
            except Exception:  # pylint: disable=broad-except
                pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
