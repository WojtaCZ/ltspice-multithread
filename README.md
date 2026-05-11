# LTSpice Multi-Sweep

A GUI tool that runs LTSpice parameter sweeps in parallel across multiple CPU cores, exports results to CSV or Octave/MATLAB `.mat` files, and lets you save/load sweep configurations.

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey)

---

## Features

- **Parallel execution** — runs N LTSpice instances simultaneously (configurable worker count)
- **Flexible step specs** — `list`, `lin`, `dec`, `oct` with full LTSpice engineering suffix support (`1k`, `4n7`, `2k2`, `10Meg`, …)
- **Axis assignment** — map each parameter to rows, columns, separate files, or leave it at the schematic default (`—`)
- **CSV and MAT export** — results written as structured CSV tables or multi-dimensional Octave/MATLAB arrays
- **Save / load setups** — sweep configurations stored as `.sweep.json` files (Ctrl+S / Ctrl+O)
- **Instant cancel** — kills all in-flight LTSpice processes immediately
- **No focus stealing** — spawned LTSpice windows start minimised and never steal keyboard focus
- **Runtime timer** — total elapsed time logged at the end of every sweep

---

## Requirements

- Windows (LTSpice is Windows-only)
- Python 3.8+
- LTSpice XVII or LTSpice (ADI version)
- `scipy` — optional, required only for `.mat` export (`pip install scipy`)

---

## Installation

```
git clone https://github.com/your-username/ltspice-multithread.git
cd ltspice-multithread
python app.py
```

No extra packages are needed beyond the standard library for basic use. Install `scipy` if you want Octave/MATLAB export:

```
pip install scipy
```

---

## Usage

1. **Select schematic** — browse to your `.asc` file; parameters are detected automatically from `.param` directives and bare `{NAME}` tokens.
2. **Configure parameters** — double-click any row to set the sweep kind, spec, and axis assignment.
3. **Set workers** — defaults to half the logical CPU count; increase for faster sweeps at the cost of RAM.
4. **Choose output** — pick a directory, base filename, and output format (CSV and/or MAT).
5. **Run sweep** — progress is shown in the status bar; errors appear in the log. Total runtime is printed when all simulations finish.

### Step spec syntax

| Kind | Spec format | Example |
|------|-------------|---------|
| `list` | space- or comma-separated values | `1k 2k2 4k7 10k` |
| `lin` | `start stop N` | `100 1k 10` (10 points, linear) |
| `dec` | `start stop pts/decade` | `1 1Meg 5` |
| `oct` | `start stop pts/octave` | `1k 32k 3` |

Engineering suffixes accepted: `T G Meg k m u µ n p f` and embedded/IEC form (`4R7`, `1k5`, `R47`).

### Axis assignment

| Axis | Effect |
|------|--------|
| `—` | Skip sweep; keep schematic default value |
| `rows` | One row per value in the CSV |
| `cols` | One column group per value in the CSV |
| `file` | One separate output file per value |

---

## Project structure

```
app.py              — Tkinter GUI
core/
  runner.py         — parallel simulation executor
  schematic.py      — .asc parameter detection and substitution
  stepping.py       — step spec parsing and value generation
  output.py         — CSV and MAT file writing
  logparser.py      — LTSpice .log file parser
examples/
  rc_lowpass.asc    — simple RC low-pass filter example
  cin_vs_lsb_error.asc / .json — ADC input RC error sweep example
  plot_cin_vs_lsb_error.m     — Octave heatmap plot script
```

---

## Sweep config format

Configs are plain JSON and can be edited by hand:

```json
{
  "version": 1,
  "schematic": "path/to/design.asc",
  "ltspice_exe": "C:/Program Files/ADI/LTspice/LTspice.exe",
  "output_dir": "path/to/output",
  "basename": "sweep",
  "workers": 8,
  "timeout": 600,
  "params": [
    { "name": "Rin", "kind": "list", "spec": "1k 10k 100k", "axis": "rows" },
    { "name": "Cin", "kind": "dec",  "spec": "100p 100n 5",  "axis": "cols" }
  ]
}
```

---

## License

MIT
