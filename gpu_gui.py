#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_gui.py — GTK GUI katmanı
Tüm arayüz kodu burada; business logic için gpu_core'u çağırır.
"""

# M4K: GUI kodu gpu-switcher.py'den ayrı bir modüle taşındı; sadece UI mantığı içerir
import sys
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, GLib, Gio

# M4K: tüm business logic gpu_core'dan import ediliyor
import gpu_core as core
from gpu_config import load_config

# M4K: config değerleri modül yüklenirken okunuyor
_cfg = load_config()
APP_ID: str = _cfg.get("app_id", "com.m4k.gpu_switcher")
_WIN_W: int = _cfg.get("window_width", 840)
_WIN_H: int = _cfg.get("window_height", 560)
_TELE_REFRESH: int = _cfg.get("telemetry_refresh_seconds", 2)


# ---------------------------------------------------------------------------
# LogBuffer
# ---------------------------------------------------------------------------

class LogBuffer:
    """GLib.idle_add üzerinden GTK TextBuffer'a güvenli log yazar."""

    # M4K: LogBuffer gpu-switcher.py'den aynen taşındı
    def __init__(self, textview: Gtk.TextView):
        self.textview = textview
        self.buf: Gtk.TextBuffer = textview.get_buffer()
        self.levels = ["DEBUG", "INFO", "WARN", "ERROR"]
        self.min_level = 1  # varsayılan INFO

    def set_level_by_name(self, name: str):
        try:
            self.min_level = self.levels.index(name)
            self.log("INFO", f"Log level set to {name}")
        except ValueError:
            pass

    def log(self, level: str, msg: str):
        if self.levels.index(level) < self.min_level:
            return
        line = f"{core.APP_TAG} [{level}] {msg}\n"

        def _append():
            self.buf.insert(self.buf.get_end_iter(), line)
            self.textview.scroll_mark_onscreen(
                self.buf.create_mark(None, self.buf.get_end_iter(), True)
            )
            return False

        GLib.idle_add(_append)


# ---------------------------------------------------------------------------
# GPUSwitcherApp
# ---------------------------------------------------------------------------

class GPUSwitcherApp(Gtk.Application):
    # M4K: GPUSwitcherApp gpu-switcher.py'den taşındı; sabitler config'den geliyor

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: Optional[Gtk.ApplicationWindow] = None

        # M4K: runtime state business logic katmanından alınıyor
        self.output_name = core.detect_display_output()
        self.prime_mode = core.detect_prime_mode()

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
            # M4K: pencere boyutu config'den okunuyor
            self.window.set_default_size(_WIN_W, _WIN_H)

            hb = Gtk.HeaderBar()
            hb.set_title("GPU Switcher")
            hb.set_show_close_button(True)
            self.window.set_titlebar(hb)

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            root.set_border_width(10)
            self.window.add(root)

            # ----- System & Display -----
            frame_sys = Gtk.Frame()
            lbl_sys = Gtk.Label()
            lbl_sys.set_use_markup(True)
            lbl_sys.set_markup("<big><b>System &amp; Display</b></big>")
            frame_sys.set_label_widget(lbl_sys)
            root.pack_start(frame_sys, False, False, 0)

            box_sys = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            if hasattr(box_sys, "set_margin_start"):
                box_sys.set_margin_start(8)
                box_sys.set_margin_end(8)
            box_sys.set_margin_top(8)
            box_sys.set_margin_bottom(8)
            frame_sys.add(box_sys)

            grid_sys = Gtk.Grid(column_spacing=10, row_spacing=6)
            box_sys.pack_start(grid_sys, False, False, 0)

            grid_sys.attach(Gtk.Label(label="Active display output:"), 0, 0, 1, 1)
            self.lbl_out = Gtk.Label(label=self.output_name)
            self.lbl_out.set_selectable(True)
            grid_sys.attach(self.lbl_out, 1, 0, 1, 1)

            grid_sys.attach(Gtk.Label(label="Current PRIME mode:"), 0, 1, 1, 1)
            self.lbl_prime = Gtk.Label(label=self.prime_mode)
            grid_sys.attach(self.lbl_prime, 1, 1, 1, 1)

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

            if self.prime_mode == "intel":
                self.rb_intel.set_active(True)
            elif self.prime_mode == "nvidia":
                self.rb_nvidia.set_active(True)
            else:
                self.rb_ondemand.set_active(True)

            # ----- NVIDIA Tweaks -----
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

            # M4K: autostart_exists() artık gpu_core'dan çağrılıyor
            self.chk_autostart.set_active(core.autostart_exists())

            grid_nv.attach(self.chk_comp, 0, 0, 2, 1)
            grid_nv.attach(self.chk_fullrgb, 0, 1, 2, 1)
            grid_nv.attach(self.chk_autostart, 0, 2, 2, 1)
            grid_nv.attach(self.chk_persist, 0, 3, 2, 1)

            grid_nv.attach(Gtk.Label(label="Locked Clocks (MHz, optional):"), 0, 4, 1, 1)
            clk_box = Gtk.Box(spacing=6)
            self.ent_min = Gtk.Entry()
            self.ent_min.set_placeholder_text("min (e.g. 1200)")
            self.ent_max = Gtk.Entry()
            self.ent_max.set_placeholder_text("max (e.g. 1500)")
            clk_box.pack_start(self.ent_min, False, False, 0)
            clk_box.pack_start(self.ent_max, False, False, 0)
            grid_nv.attach(clk_box, 1, 4, 1, 1)

            btn_apply = Gtk.Button(label="Apply")
            btn_apply.connect("clicked", self.on_apply_clicked)
            box_nv.pack_start(btn_apply, False, False, 0)

            # ----- Telemetry -----
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

            # ----- Output/Log -----
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

            level_box = Gtk.Box(spacing=6)
            level_box.pack_start(Gtk.Label(label="Log level:"), False, False, 0)
            cmb = Gtk.ComboBoxText()
            for lv in ["DEBUG", "INFO", "WARN", "ERROR"]:
                cmb.append_text(lv)
            cmb.set_active(1)
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

            footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info = Gtk.Label(label="Tip: Switching PRIME may require reboot or logout/login.")
            footer.pack_start(info, False, False, 0)
            root.pack_start(footer, False, False, 0)

            self.window.connect("destroy", self.on_destroy)
            self.window.show_all()

            # M4K: telemetri yenileme aralığı config'den okunuyor
            if core.have("nvidia-smi"):
                self.telemetry_timer_id = GLib.timeout_add_seconds(
                    _TELE_REFRESH, self.refresh_telemetry
                )
            else:
                self.logbuf.log("WARN", "nvidia-smi not found; telemetry disabled.")

            self.logbuf.log("INFO", f"Detected display: {self.output_name}")
            self.logbuf.log("INFO", f"Detected PRIME mode: {self.prime_mode}")

        self.window.present()

    # ------------------------ Sinyal işleyiciler ----------------------------

    def on_destroy(self, *args):
        if self.telemetry_timer_id is not None:
            GLib.source_remove(self.telemetry_timer_id)
            self.telemetry_timer_id = None

    def on_log_level_changed(self, combo: Gtk.ComboBoxText):
        txt = combo.get_active_text()
        if txt:
            self.logbuf.set_level_by_name(txt)

    def on_apply_clicked(self, btn):
        # M4K: tüm apply çağrıları artık gpu_core modülünden yapılıyor
        target_prime = "on-demand"
        if self.rb_intel.get_active():
            target_prime = "intel"
        elif self.rb_nvidia.get_active():
            target_prime = "nvidia"

        if target_prime != self.prime_mode:
            self.logbuf.log("INFO", f"Switching PRIME to '{target_prime}'...")
            core.apply_prime(target_prime, self.logbuf.log)
            self.prime_mode = core.detect_prime_mode()
            self.lbl_prime.set_text(self.prime_mode)

        if self.chk_comp.get_active():
            self.logbuf.log("INFO", f"Applying ForceCompositionPipeline on {self.output_name}...")
            core.apply_force_comp_pipeline(self.output_name, self.logbuf.log)

        if self.chk_fullrgb.get_active():
            self.logbuf.log("INFO", "Applying Full RGB range...")
            core.apply_full_rgb(self.logbuf.log)

        if self.chk_autostart.get_active():
            core.install_autostart(self.output_name, self.logbuf.log)
        else:
            core.remove_autostart(self.logbuf.log)

        core.set_persistence_mode(self.chk_persist.get_active(), self.logbuf.log)

        min_txt = self.ent_min.get_text().strip()
        max_txt = self.ent_max.get_text().strip()
        min_mhz = int(min_txt) if min_txt.isdigit() else None
        max_mhz = int(max_txt) if max_txt.isdigit() else None
        if min_mhz and max_mhz:
            core.set_locked_clocks(min_mhz, max_mhz, self.logbuf.log)

        self.logbuf.log("INFO", "Apply finished.")

    def refresh_telemetry(self) -> bool:
        # M4K: telemetri verisi gpu_core.fetch_nvidia_telemetry() üzerinden alınıyor
        tele = core.fetch_nvidia_telemetry()
        t = f"Temp: {tele.tempC:.0f} °C" if tele.tempC is not None else "Temp: -"
        c = f"Clock: {tele.clkMHz:.0f} MHz" if tele.clkMHz is not None else "Clock: -"

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


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------

def main():
    # M4K: main() gpu_gui'ye taşındı; gpu-switcher.py sadece bunu çağırır
    app = GPUSwitcherApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
