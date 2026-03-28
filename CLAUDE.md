# CLAUDE.md — GPU Switcher

> AI assistant guide for understanding, navigating, and modifying this repository.

---

## Project Overview

**GPU Switcher** is a lightweight Ubuntu/Xorg tool that lets users:

- Switch between NVIDIA, Intel, and on-demand PRIME modes via `prime-select`
- Apply `ForceCompositionPipeline` and `ForceFullCompositionPipeline` NVIDIA display tweaks
- Set full-range RGB color output
- Enable NVIDIA persistence mode and lock GPU clocks
- Manage an XDG autostart `.desktop` entry for applying settings at login
- Monitor live GPU telemetry (temperature, clock, fan, power) via `nvidia-smi`

It has two interfaces that share the same underlying logic:
- A **GTK3 GUI** (`gpu-switcher.py`)
- A **headless CLI** (`gpu-switch-apply.sh`)

**Target platform:** Ubuntu 24.04, Xorg (X11) sessions only. Wayland is not supported.

---

## Repository Structure

```
gpu-switcher/
├── gpu-switcher.py          # Main GTK3 GUI application (Python 3.12+)
├── gpu-switch-apply.sh      # Headless bash CLI for all GPU operations
├── setup.sh                 # Dependency installer + optional autostart setup
├── uninstall.sh             # Removes autostart entries, optionally resets GPU state
├── docs/
│   └── gui.png              # GUI screenshot
├── .gitignore
├── LICENSE                  # MIT
└── README.md
```

---

## Key Files

### `gpu-switcher.py`

The primary entry point. A single-file GTK3 application (`Gtk.Application`, app ID `com.m4k.gpu_switcher`).

**Structure:**
- **Helper functions** (top of file): `which()`, `run_cmd()`, `have()`, `ensure_dir()`
- **Detection functions**: `detect_display_output()`, `detect_prime_mode()`
- **Telemetry**: `fetch_nvidia_telemetry()` returns a `Telemetry` dataclass parsed from `nvidia-smi --query-gpu`
- **Apply operations**: `apply_force_comp_pipeline()`, `apply_full_rgb()`, `set_persistence_mode()`, `set_locked_clocks()`, `apply_prime()`
- **Autostart management**: `install_autostart()`, `remove_autostart()`, `autostart_exists()`
- **UI**: `LogBuffer` class wraps a `Gtk.TextView` for thread-safe log appending; `GPUSwitcherApp` is the `Gtk.Application` subclass
- **Entry point**: `main()` at the bottom

All subprocess calls go through `run_cmd(cmd, timeout)` which uses `shlex.split()` for safe argument parsing. Never construct commands via string concatenation.

### `gpu-switch-apply.sh`

Bash CLI mirror of the Python apply functions. Accepts flags:

| Flag | Default | Description |
|---|---|---|
| `--apply` | off | Apply `nvidia-settings` MetaMode + color |
| `--persist` | off | Enable `nvidia-smi -pm 1` and optional clock lock |
| `--autostart on\|off` | off | Write or remove `~/.config/autostart/nvidia-comp-pipeline.desktop` |
| `--output NAME` | auto | Override display output name (else auto-detected) |
| `--mode WxH_Hz` | `3840x2160_60` | Resolution/refresh for MetaMode string |
| `--clk-min N` | - | Minimum locked clock MHz |
| `--clk-max N` | - | Maximum locked clock MHz |
| `--force On\|Off` | `On` | `ForceCompositionPipeline` value |
| `--fforce On\|Off` | `On` | `ForceFullCompositionPipeline` value |
| `--colorspace 0\|1` | `0` | 0=RGB, 1=YCbCr444 |
| `--colorrange 0\|1` | `0` | 0=Full, 1=Limited |

Uses `set -Eeuo pipefail`. Auto-detects display via `xrandr --query` with preference for external outputs (HDMI/DP/DVI).

### `setup.sh`

One-time setup script. Runs `apt install` for GTK3/Python bindings and NVIDIA tools, then optionally writes an XDG autostart entry calling `gpu-switch-apply.sh`.

### `uninstall.sh`

Reverses `setup.sh`. Removes autostart entries. Optional `--gpu-reset` flag disables persistence and resets locked clocks.

---

## Architecture & Conventions

### Python Style
- Python 3.12+, no external pip dependencies (only system GTK bindings via `gi`)
- `from gi.repository import Gtk, GLib, Gio` — uses GLib main loop
- UI updates from background callbacks must go through `GLib.idle_add()` (see `LogBuffer.log()`)
- `@dataclass` used for `Telemetry`; prefer dataclasses for new data structures
- No type aliases needed; use `Optional[T]` from `typing` for nullable values
- `run_cmd()` is the single authoritative subprocess wrapper — always use it, never call `subprocess` directly

### Shell Style
- All shell scripts use `set -Eeuo pipefail`
- `have()` guards every external tool check before invoking it
- `log()` prefix is `[gpu-switcher]` for the main script, `[gpu-switcher:setup]` for setup
- `mapfile` used for arrays from command substitution (bash 4+ required)

### Autostart File Paths
- Autostart desktop file: `~/.config/autostart/nvidia-comp-pipeline.desktop` (apply script)
- Setup script autostart: `~/.config/autostart/gpu-switcher-autostart.desktop`

### Privilege Model
- `prime-select` is called via `pkexec` first (graphical auth dialog), falling back to `sudo`
- `nvidia-smi -pm` (persistence) and `nvidia-smi -lgc` (clock lock) require `sudo`
- All other operations (nvidia-settings, xrandr) run as the current user under Xorg

---

## Development Workflows

### Running the GUI
```bash
python3 gpu-switcher.py
```
Requires an active Xorg session with `$DISPLAY` set.

### Running the CLI
```bash
./gpu-switch-apply.sh --apply
./gpu-switch-apply.sh --apply --persist --autostart on --mode 3840x2160_60
sudo ./gpu-switch-apply.sh --persist --clk-min 1200 --clk-max 1500
```

### Installing Dependencies
```bash
chmod +x setup.sh
./setup.sh
```

### Uninstalling
```bash
chmod +x uninstall.sh
./uninstall.sh --gpu-reset
```

### Linting / Testing
There is no automated test suite or CI pipeline. Manual testing requires:
- An Ubuntu 24.04+ system with Xorg session
- NVIDIA proprietary drivers (550.x recommended)
- `nvidia-settings`, `nvidia-smi`, `xrandr`, `prime-select` installed

For Python syntax checking: `python3 -m py_compile gpu-switcher.py`
For shell linting: `shellcheck gpu-switch-apply.sh setup.sh uninstall.sh`

---

## Common Modification Patterns

### Adding a new CLI flag to `gpu-switch-apply.sh`
1. Add a `--flag-name)` case in the `while [[ $# -gt 0 ]]` loop inside `main()`
2. Declare the variable with a default before the loop
3. Call the relevant function after argument parsing

### Adding a new operation to the Python GUI
1. Write the logic as a standalone function following the `apply_*(logger)` pattern — accept a `logger` callable, return `bool`
2. Add any needed widget to `do_activate()` in `GPUSwitcherApp`
3. Call the function in `on_apply_clicked()` with `self.logbuf.log` as the logger

### Adding a new telemetry field
1. Add the field to the `Telemetry` dataclass
2. Add the `nvidia-smi` query column to the `--query-gpu` call in `fetch_nvidia_telemetry()`
3. Parse the new column by index from `parts`
4. Display it in `refresh_telemetry()` and add a label widget in `do_activate()`

---

## External Tools & Dependencies

| Tool | Package | Required for |
|---|---|---|
| `nvidia-settings` | `nvidia-settings` | MetaMode, color space/range |
| `nvidia-smi` | `nvidia-utils-550` | Telemetry, persistence, clock lock |
| `prime-select` | `ubuntu-drivers-common` | PRIME mode switching |
| `xrandr` | `x11-xserver-utils` | Display output detection |
| `pkexec` | `policykit-1` | Graphical privilege escalation |
| `python3-gi` | `python3-gi` | GTK3 Python bindings |
| `gir1.2-gtk-3.0` | `gir1.2-gtk-3.0` | GTK3 typelib |

---

## Known Constraints & Gotchas

- **Xorg only**: `nvidia-settings --assign CurrentMetaMode` has no effect under Wayland
- **Display resolution hardcoded in autostart**: The autostart `.desktop` entry hardcodes `3840x2160_60`; it will silently fail on monitors with different native resolutions
- **Fan telemetry**: Laptops often report `N/A` for fan speed via `nvidia-smi`; the code handles this explicitly
- **Fallback MetaMode**: `apply_force_comp_pipeline()` tries a generic MetaMode first, then falls back to the hardcoded `3840x2160_60` variant
- **PRIME switch needs reboot**: `prime-select` changes take effect only after logout/login or full reboot — the UI informs the user but cannot enforce it
- **`GLib.idle_add` for UI updates**: Any log message or label update triggered from a timer or background context must use `GLib.idle_add()`; direct widget calls from non-main-thread contexts will crash GTK
