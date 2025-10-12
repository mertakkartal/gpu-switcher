#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GPU Switcher – Simple NVIDIA/Intel switch & display finetune helper
Author: Mert Akkartal
License: MIT

Runtime deps (Ubuntu):
  sudo apt install -y python3-gi gir1.2-gtk-3.0 x11-xserver-utils \
                      nvidia-driver-550 (veya sistemine uygun), nvidia-settings \
                      inxi (opsiyonel), prime-select (ubuntu-drivers-common paketiyle gelir)

This app:
- Lets you choose GPU mode: intel / on-demand / nvidia (via prime-select)
- Applies NVIDIA display tweaks (ForceCompositionPipeline, Full Color Range, RGB ColorSpace)
- Optional: set persistence mode and (min,max) locked clocks
- Shows lightweight telemetry (nvidia-smi) if available
- Has a log/output panel with adjustable log level
- Can autostart the composition pipeline command on login

Works best under Xorg when using NVIDIA for output. Wayland users still can use prime-select,
but nvidia-settings metamode tweaks apply on X.
"""

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, GLib, Gio  # GObject flags pitfalls avoided; we use Gio

APP_ID = "com.m4k.gpu_switcher"
APP_TAG = "[gpu-switcher]"

AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_DESKTOP = os.path.join(AUTOSTART_DIR, "nvidia-comp-pipeline.desktop")


# ------------------------------ small helpers -------------------------------

def which(cmd: str) -> Optional[str]:
    """Return absolute path for an executable or None."""
    for p in os.environ.get("PATH", "").split(os.pathsep):
        fp = os.path.join(p, cmd)
        if os.path.isfile(fp) and os.access(fp, os.X_OK):
            return fp
    return None


def run_cmd(cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
    """Run shell command safely and return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            shlex.split(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            check=False,
            env=os.environ.copy()
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def have(cmd: str) -> bool:
    return which(cmd) is not None


def ensure_dir(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


# ------------------------------ detection -----------------------------------

def detect_display_output() -> str:
    """
    Pick a likely external display output first (HDMI/DP), else fall back to first connected,
    else "HDMI-0".
    """
    if not have("xrandr"):
        return "HDMI-0"
    rc, out, _ = run_cmd("xrandr --verbose")
    if rc != 0 or not out:
        return "HDMI-0"
    lines = out.splitlines()
    connected = []
    for ln in lines:
        # lines like: HDMI-0 connected primary 3840x2160+0+0 ...
        if " connected" in ln:
            name = ln.split()[0]
            if "disconnected" not in ln:
                connected.append(name)
    # Prefer external (HDMI|DP|DVI|DisplayPort)
    for n in connected:
        if n.startswith(("HDMI", "DP", "DVI", "DisplayPort")):
            return n
    # else fallback to first connected
    if connected:
        return connected[0]
    return "HDMI-0"


def detect_prime_mode() -> str:
    """
    Return prime-select current mode if available; else 'unknown'.
    """
    if not have("prime-select"):
        return "unknown"
    rc, out, _ = run_cmd("prime-select query")
    if rc == 0 and out:
        return out.strip()
    return "unknown"


# --------------------------- NVIDIA telemetry --------------------------------

@dataclass
class Telemetry:
    tempC: Optional[float] = None
    clkMHz: Optional[float] = None
    fanPct: Optional[float] = None
    pwrW: Optional[float] = None
    pwrCap: Optional[float] = None
    fanRaw: Optional[str] = None


def parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def fetch_nvidia_telemetry() -> Telemetry:
    """
    Use nvidia-smi csv,noheader,nounits
    """
    tele = Telemetry()
    if not have("nvidia-smi"):
        return tele
    q = ("nvidia-smi --query-gpu=temperature.gpu,clocks.gr,fan.speed,"
         "power.draw,power.limit --format=csv,noheader,nounits")
    rc, out, err = run_cmd(q, timeout=3)
    if rc != 0 or not out:
        return tele
    # Expect one line: "temp,clock,fan,power,powerlimit"
    line = out.splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 5:
        tele.tempC = parse_float_safe(parts[0])
        tele.clkMHz = parse_float_safe(parts[1])
        # fan may be "N/A" on laptops; keep raw
        tele.fanRaw = parts[2]
        tele.fanPct = parse_float_safe(parts[2])  # will be None if "N/A"
        tele.pwrW = parse_float_safe(parts[3])
        tele.pwrCap = parse_float_safe(parts[4])
    return tele


# ------------------------------ Apply ops -----------------------------------

def apply_force_comp_pipeline(output_name: str, logger) -> bool:
    """
    Enable ForceCompositionPipeline + FullCompositionPipeline for the given output.
    """
    if not have("nvidia-settings"):
        logger("nvidia-settings not found; cannot apply composition pipeline.")
        return False

    # Build meta mode string; 60 Hz suffix is typical; if unknown, omit Hz and rely on current mode
    meta = f'{output_name}: {output_name} {{"ForceCompositionPipeline=On, ForceFullCompositionPipeline=On"}}'
    # NOTE: On most setups, specifying mode as 3840x2160_60 works; but to be safer, omit explicit size:
    cmd = f'nvidia-settings --assign CurrentMetaMode="{output_name}: {{"ForceCompositionPipeline=On, ForceFullCompositionPipeline=On"}}"'
    # However the safer one needs exact syntax per X screen. Fallback to mode-qualified line if needed.
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        # fallback: assume 60 Hz mode string exists
        cmd2 = (f'nvidia-settings --assign CurrentMetaMode="{output_name}: 3840x2160_60 +0+0 '
                '{ForceCompositionPipeline=On, ForceFullCompositionPipeline=On}"')
        rc2, out2, err2 = run_cmd(cmd2)
        if rc2 != 0:
            logger(f"Failed to set ForceCompositionPipeline: {err2 or err}")
            return False
        logger("ForceCompositionPipeline applied (fallback meta).")
        return True

    logger("ForceCompositionPipeline applied.")
    return True


def apply_full_rgb(logger) -> bool:
    """
    Set ColorSpace=RGB (0), ColorRange=Full (0) for DPY:0 (active X screen)
    """
    if not have("nvidia-settings"):
        logger("nvidia-settings not found; cannot apply color space/range.")
        return False
    ok = True
    rc, out, err = run_cmd("nvidia-settings --assign ColorSpace=0")
    if rc != 0:
        ok = False
    rc, out, err = run_cmd("nvidia-settings --assign ColorRange=0")
    if rc != 0:
        ok = False
    if ok:
        logger("Color space set to RGB, full range enabled.")
    else:
        logger("Failed to set ColorSpace/ColorRange (may be harmless on some setups).")
    return ok


def set_persistence_mode(enable: bool, logger) -> bool:
    if not have("nvidia-smi"):
        logger("nvidia-smi not found; cannot set persistence mode.")
        return False
    flag = "1" if enable else "0"
    rc, out, err = run_cmd(f"sudo nvidia-smi -pm {flag}")
    if rc == 0:
        logger(f"Persistence mode {'enabled' if enable else 'disabled'}.")
        return True
    logger(f"Failed to set persistence mode: {err or out}")
    return False


def set_locked_clocks(min_mhz: Optional[int], max_mhz: Optional[int], logger) -> bool:
    if min_mhz is None or max_mhz is None:
        logger("Locked clocks not requested (empty fields).")
        return True
    if not have("nvidia-smi"):
        logger("nvidia-smi not found; cannot lock clocks.")
        return False
    rc, out, err = run_cmd(f"sudo nvidia-smi -lgc {min_mhz},{max_mhz}")
    if rc == 0:
        logger(f"Locked graphics clocks set to {min_mhz}-{max_mhz} MHz.")
        return True
    logger(f"Failed to set locked clocks: {err or out}")
    return False


def apply_prime(mode: str, logger) -> bool:
    """
    mode in {'intel','on-demand','nvidia'} for Ubuntu prime-select.
    Requires pkexec/sudo; we try pkexec first for GUI auth.
    """
    if not have("prime-select"):
        logger("prime-select not found; skipping PRIME mode switching.")
        return False
    if mode not in {"intel", "on-demand", "nvidia"}:
        logger(f"Invalid PRIME mode: {mode}")
        return False
    # Try pkexec first (graphical auth)
    cmd = f"pkexec prime-select {mode}"
    rc, out, err = run_cmd(cmd, timeout=30)
    if rc != 0:
        # fallback to sudo (will likely prompt in terminal)
        rc2, out2, err2 = run_cmd(f"sudo prime-select {mode}", timeout=30)
        if rc2 != 0:
            logger(f"Failed to switch prime-select: {err2 or err or out2 or out}")
            return False
    logger(f"prime-select set to '{mode}'. A reboot or logout/login may be required.")
    return True


# ------------------------------ autostart ------------------------------------

AUTOSTART_CMD = (
    'nvidia-settings --assign '
    'CurrentMetaMode="{}: 3840x2160_60 +0+0 {{ForceCompositionPipeline=On, ForceFullCompositionPipeline=On}}"'
)


def install_autostart(output_name: str, logger) -> bool:
    ensure_dir(AUTOSTART_DIR)
    cmdline = AUTOSTART_CMD.format(output_name)
    desktop = f"""[Desktop Entry]
Type=Application
Exec={cmdline}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=ForceCompositionPipeline
"""
    try:
        with open(AUTOSTART_DESKTOP, "w") as f:
            f.write(desktop)
        logger(f"Autostart entry written: {AUTOSTART_DESKTOP}")
        return True
    except Exception as e:
        logger(f"Failed to write autostart entry: {e}")
        return False


def remove_autostart(logger) -> bool:
    try:
        if os.path.exists(AUTOSTART_DESKTOP):
            os.remove(AUTOSTART_DESKTOP)
            logger("Autostart entry removed.")
        else:
            logger("Autostart entry not present.")
        return True
    except Exception as e:
        logger(f"Failed to remove autostart entry: {e}")
        return False


def autostart_exists() -> bool:
    return os.path.exists(AUTOSTART_DESKTOP)


# ------------------------------ UI ------------------------------------------

class LogBuffer:
    """Simple log buffer that appends to a Gtk.TextBuffer safely from GLib.idle_add."""

    def __init__(self, textview: Gtk.TextView):
        self.textview = textview
        self.buf: Gtk.TextBuffer = textview.get_buffer()
        self.levels = ["DEBUG", "INFO", "WARN", "ERROR"]
        self.min_level = 1  # default INFO

    def set_level_by_name(self, name: str):
        try:
            self.min_level = self.levels.index(name)
            self.log("INFO", f"Log level set to {name}")
        except ValueError:
            pass

    def log(self, level: str, msg: str):
        if self.levels.index(level) < self.min_level:
            return
        line = f"{APP_TAG} [{level}] {msg}\n"

        def _append():
            self.buf.insert(self.buf.get_end_iter(), line)
            self.textview.scroll_mark_onscreen(self.buf.create_mark(None, self.buf.get_end_iter(), True))
            return False

        GLib.idle_add(_append)


class GPUSwitcherApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: Optional[Gtk.ApplicationWindow] = None

        # runtime state
        self.output_name = detect_display_output()
        self.prime_mode = detect_prime_mode()

        # widgets
        self.rb_intel = None
        self.rb_ondemand = None
        self.rb_nvidia = None

        self.chk_comp = None
        self.chk_fullrgb = None
        self.chk_autostart = None
        self.chk_persist = None

        self.ent_min = None
        self.ent_max = None

        self.lbl_out = None
        self.lbl_prime = None

        self.lbl_temp = None
        self.lbl_clk = None
        self.lbl_fan = None
        self.lbl_pwr = None

        self.logview = None
        self.logbuf = None

        self.telemetry_timer_id = None

    # ------------------------ GTK lifecycle ---------------------------------

    def do_activate(self, *args, **kwargs):
        if not self.window:
            self.window = Gtk.ApplicationWindow(application=self)
            self.window.set_title("GPU Switcher")
            self.window.set_default_size(840, 560)

            # Headerbar (GTK3 classic titlebar + box)
            hb = Gtk.HeaderBar()
            hb.set_title("GPU Switcher")
            hb.set_show_close_button(True)
            self.window.set_titlebar(hb)

            # Root
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            root.set_border_width(10)
            self.window.add(root)

            # ----- System & Display (Frame) -----
            frame_sys = Gtk.Frame()
            lbl_sys = Gtk.Label()
            lbl_sys.set_use_markup(True)
            lbl_sys.set_markup("<big><b>System &amp; Display</b></big>")
            frame_sys.set_label_widget(lbl_sys)
            root.pack_start(frame_sys, False, False, 0)

            box_sys = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            # margins (GTK3: start/end)
            if hasattr(box_sys, "set_margin_start"):
                box_sys.set_margin_start(8)
                box_sys.set_margin_end(8)
            box_sys.set_margin_top(8)
            box_sys.set_margin_bottom(8)
            frame_sys.add(box_sys)

            grid_sys = Gtk.Grid(column_spacing=10, row_spacing=6)
            box_sys.pack_start(grid_sys, False, False, 0)

            # Detected output name
            grid_sys.attach(Gtk.Label(label="Active display output:"), 0, 0, 1, 1)
            self.lbl_out = Gtk.Label(label=self.output_name)
            self.lbl_out.set_selectable(True)
            grid_sys.attach(self.lbl_out, 1, 0, 1, 1)

            # PRIME mode
            grid_sys.attach(Gtk.Label(label="Current PRIME mode:"), 0, 1, 1, 1)
            self.lbl_prime = Gtk.Label(label=self.prime_mode)
            grid_sys.attach(self.lbl_prime, 1, 1, 1, 1)

            # PRIME radio buttons
            rb_box = Gtk.Box(spacing=10)
            self.rb_intel = Gtk.RadioButton.new_with_label_from_widget(None, "intel")
            self.rb_ondemand = Gtk.RadioButton.new_from_widget(self.rb_intel)
            self.rb_ondemand.set_label("on-demand")
            self.rb_nvidia = Gtk.RadioButton.new_from_widget(self.rb_intel)
            self.rb_nvidia.set_label("nvidia")
            rb_box.pack_start(self.rb_intel, False, False, 0)
            rb_box.pack_start(self.rb_ondemand, False, False, 0)
            rb_box.pack_start(self.rb_nvidia, False, False, 0)
            grid_sys.attach(Gtk.Label(label="Select PRIME:"), 0, 2, 1, 1)
            grid_sys.attach(rb_box, 1, 2, 1, 1)

            # set radio according to detected mode
            if self.prime_mode == "intel":
                self.rb_intel.set_active(True)
            elif self.prime_mode == "nvidia":
                self.rb_nvidia.set_active(True)
            else:
                self.rb_ondemand.set_active(True)

            # ----- NVIDIA Tweaks (Frame) -----
            frame_nv = Gtk.Frame()
            lbl_nv = Gtk.Label()
            lbl_nv.set_use_markup(True)
            lbl_nv.set_markup("<big><b>NVIDIA Display Tweaks</b></big>")
            frame_nv.set_label_widget(lbl_nv)
            root.pack_start(frame_nv, False, False, 0)

            box_nv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            if hasattr(box_nv, "set_margin_start"):
                box_nv.set_margin_start(8)
                box_nv.set_margin_end(8)
            box_nv.set_margin_top(8)
            box_nv.set_margin_bottom(8)
            frame_nv.add(box_nv)

            grid_nv = Gtk.Grid(column_spacing=10, row_spacing=6)
            box_nv.pack_start(grid_nv, False, False, 0)

            self.chk_comp = Gtk.CheckButton(label="Force Composition Pipeline (tear-free)")
            self.chk_fullrgb = Gtk.CheckButton(label="Force RGB Full Range")
            self.chk_autostart = Gtk.CheckButton(label="Save composition pipeline to Autostart")
            self.chk_persist = Gtk.CheckButton(label="Enable Persistence Mode")

            self.chk_autostart.set_active(autostart_exists())

            grid_nv.attach(self.chk_comp, 0, 0, 2, 1)
            grid_nv.attach(self.chk_fullrgb, 0, 1, 2, 1)
            grid_nv.attach(self.chk_autostart, 0, 2, 2, 1)
            grid_nv.attach(self.chk_persist, 0, 3, 2, 1)

            # Locked clocks
            grid_nv.attach(Gtk.Label(label="Locked Clocks (MHz, optional):"), 0, 4, 1, 1)
            clk_box = Gtk.Box(spacing=6)
            self.ent_min = Gtk.Entry()
            self.ent_min.set_placeholder_text("min (e.g. 1200)")
            self.ent_max = Gtk.Entry()
            self.ent_max.set_placeholder_text("max (e.g. 1500)")
            clk_box.pack_start(self.ent_min, False, False, 0)
            clk_box.pack_start(self.ent_max, False, False, 0)
            grid_nv.attach(clk_box, 1, 4, 1, 1)

            # Apply button row
            btn_apply = Gtk.Button(label="Apply")
            btn_apply.connect("clicked", self.on_apply_clicked)
            box_nv.pack_start(btn_apply, False, False, 0)

            # ----- Telemetry (Frame) -----
            frame_tm = Gtk.Frame()
            lbl_tm = Gtk.Label()
            lbl_tm.set_use_markup(True)
            lbl_tm.set_markup("<big><b>Telemetry</b></big>")
            frame_tm.set_label_widget(lbl_tm)
            root.pack_start(frame_tm, False, False, 0)

            box_tm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            if hasattr(box_tm, "set_margin_start"):
                box_tm.set_margin_start(8)
                box_tm.set_margin_end(8)
            box_tm.set_margin_top(8)
            box_tm.set_margin_bottom(8)
            frame_tm.add(box_tm)

            grid_tm = Gtk.Grid(column_spacing=10, row_spacing=6)
            box_tm.pack_start(grid_tm, False, False, 0)

            self.lbl_temp = Gtk.Label(label="Temp: -")
            self.lbl_clk = Gtk.Label(label="Clock: -")
            self.lbl_fan = Gtk.Label(label="Fan: -")
            self.lbl_pwr = Gtk.Label(label="Power: -")

            grid_tm.attach(self.lbl_temp, 0, 0, 1, 1)
            grid_tm.attach(self.lbl_clk, 1, 0, 1, 1)
            grid_tm.attach(self.lbl_fan, 2, 0, 1, 1)
            grid_tm.attach(self.lbl_pwr, 3, 0, 1, 1)

            # ----- Output/Log (Frame) -----
            frame_out = Gtk.Frame()
            lbl_outf = Gtk.Label()
            lbl_outf.set_use_markup(True)
            lbl_outf.set_markup("<big><b>Output</b></big>")
            frame_out.set_label_widget(lbl_outf)
            root.pack_start(frame_out, True, True, 0)

            box_out = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            if hasattr(box_out, "set_margin_start"):
                box_out.set_margin_start(8)
                box_out.set_margin_end(8)
            box_out.set_margin_top(8)
            box_out.set_margin_bottom(8)
            frame_out.add(box_out)

            # log level selector
            level_box = Gtk.Box(spacing=6)
            level_box.pack_start(Gtk.Label(label="Log level:"), False, False, 0)
            cmb = Gtk.ComboBoxText()
            for lv in ["DEBUG", "INFO", "WARN", "ERROR"]:
                cmb.append_text(lv)
            cmb.set_active(1)  # INFO
            cmb.connect("changed", self.on_log_level_changed)
            level_box.pack_start(cmb, False, False, 0)
            box_out.pack_start(level_box, False, False, 0)

            self.logview = Gtk.TextView()
            self.logview.set_editable(False)
            self.logview.set_monospace(True)
            sc = Gtk.ScrolledWindow()
            sc.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            sc.add(self.logview)
            box_out.pack_start(sc, True, True, 0)

            self.logbuf = LogBuffer(self.logview)

            # footer
            footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info = Gtk.Label(label="Tip: Switching PRIME may require reboot or logout/login.")
            footer.pack_start(info, False, False, 0)
            root.pack_start(footer, False, False, 0)

            self.window.connect("destroy", self.on_destroy)
            self.window.show_all()

            # Start telemetry refresh if NVIDIA tools exist
            if have("nvidia-smi"):
                self.telemetry_timer_id = GLib.timeout_add_seconds(2, self.refresh_telemetry)
            else:
                self.logbuf.log("WARN", "nvidia-smi not found; telemetry disabled.")

            # Initial state log
            self.logbuf.log("INFO", f"Detected display: {self.output_name}")
            self.logbuf.log("INFO", f"Detected PRIME mode: {self.prime_mode}")

        self.window.present()

    # ------------------------ signals/handlers -------------------------------

    def on_destroy(self, *args):
        if self.telemetry_timer_id is not None:
            GLib.source_remove(self.telemetry_timer_id)
            self.telemetry_timer_id = None

    def on_log_level_changed(self, combo: Gtk.ComboBoxText):
        txt = combo.get_active_text()
        if txt:
            self.logbuf.set_level_by_name(txt)

    def on_apply_clicked(self, btn):
        # 1) PRIME mode (if changed)
        target_prime = "on-demand"
        if self.rb_intel.get_active():
            target_prime = "intel"
        elif self.rb_nvidia.get_active():
            target_prime = "nvidia"

        if target_prime != self.prime_mode:
            self.logbuf.log("INFO", f"Switching PRIME to '{target_prime}'...")
            apply_prime(target_prime, self.logbuf.log)
            # read back
            self.prime_mode = detect_prime_mode()
            self.lbl_prime.set_text(self.prime_mode)

        # 2) NVIDIA tweaks
        if self.chk_comp.get_active():
            self.logbuf.log("INFO", f"Applying ForceCompositionPipeline on {self.output_name}...")
            apply_force_comp_pipeline(self.output_name, self.logbuf.log)

        if self.chk_fullrgb.get_active():
            self.logbuf.log("INFO", "Applying Full RGB range...")
            apply_full_rgb(self.logbuf.log)

        # 3) Autostart
        if self.chk_autostart.get_active():
            install_autostart(self.output_name, self.logbuf.log)
        else:
            remove_autostart(self.logbuf.log)

        # 4) Persistence mode
        set_persistence_mode(self.chk_persist.get_active(), self.logbuf.log)

        # 5) Locked clocks
        min_txt = self.ent_min.get_text().strip()
        max_txt = self.ent_max.get_text().strip()
        min_mhz = int(min_txt) if min_txt.isdigit() else None
        max_mhz = int(max_txt) if max_txt.isdigit() else None
        if min_mhz and max_mhz:
            set_locked_clocks(min_mhz, max_mhz, self.logbuf.log)

        self.logbuf.log("INFO", "Apply finished.")

    def refresh_telemetry(self) -> bool:
        tele = fetch_nvidia_telemetry()
        t = f"Temp: {tele.tempC:.0f} °C" if tele.tempC is not None else "Temp: -"
        c = f"Clock: {tele.clkMHz:.0f} MHz" if tele.clkMHz is not None else "Clock: -"

        # Fan text: show N/A if reported that way
        if tele.fanPct is not None:
            f = f"Fan: {tele.fanPct:.0f} %"
        elif tele.fanRaw and tele.fanRaw.upper() == "N/A":
            f = "Fan: N/A"
        else:
            f = "Fan: -"

        if tele.pwrW is not None and tele.pwrCap is not None:
            p = f"Power: {tele.pwrW:.1f} / {tele.pwrCap:.1f} W"
        elif tele.pwrW is not None:
            p = f"Power: {tele.pwrW:.1f} W"
        else:
            p = "Power: N/A"

        self.lbl_temp.set_text(t)
        self.lbl_clk.set_text(c)
        self.lbl_fan.set_text(f)
        self.lbl_pwr.set_text(p)
        return True


# ------------------------------ main -----------------------------------------

def main():
    app = GPUSwitcherApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
