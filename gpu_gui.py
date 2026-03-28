#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_gui.py — GTK4 + libadwaita enterprise arayüz katmanı
MVC View: sadece UI. Business logic için gpu_controller kullanır.

Gereksinimler:
  sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi
"""

# M4K: gpu_gui.py GTK3'ten GTK4 + libadwaita'ya tamamen yeniden yazıldı / gpu_gui.py fully rewritten from GTK3 to GTK4 + libadwaita
import sys
import threading
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gio, GLib, Gtk

from gpu_config import load_config
from gpu_controller import ApplySettings, GpuController, GpuProfile

_cfg = load_config()

# M4K: uygulama sabitleri config'den okunuyor / application constants read from config
APP_ID: str = _cfg.get("app_id", "com.m4k.gpu_switcher")
_WIN_W: int = _cfg.get("window_width", 700)
_WIN_H: int = _cfg.get("window_height", 820)
_TELE_REFRESH: int = _cfg.get("telemetry_refresh_seconds", 2)

_LOG_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
# M4K: tray_enabled config'den okunuyor; False ise tepsi ikonu devre dışı / tray_enabled read from config; if False, tray icon is disabled
_TRAY_ENABLED: bool = _cfg.get("tray_enabled", True)


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------

class GpuSwitcherWindow(Adw.ApplicationWindow):
    """Ana uygulama penceresi — GTK4 + libadwaita."""

    def __init__(self, app: Adw.Application, controller: GpuController):
        super().__init__(application=app)
        # M4K: controller referansı tutuldu; window doğrudan core'a erişmiyor / controller reference stored; window does not access core directly
        self._ctrl = controller
        self._applying = False
        self._min_log_level = 1  # INFO
        self._telemetry_timer_id: Optional[int] = None
        self._profile_rows: list = []

        self.set_title("GPU Switcher")
        self.set_default_size(_WIN_W, _WIN_H)

        # M4K: _tray başlangıçta None; _setup_tray() pystray varsa atar / _tray is None initially; _setup_tray() assigns it if pystray is available
        self._tray = None

        self._build_ui()
        self._refresh_profiles_list()
        self._start_telemetry()
        if _TRAY_ENABLED:
            self._setup_tray()

    # -----------------------------------------------------------------------
    # UI kurulumu
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        # M4K: Adw.ToastOverlay ile bildirim sistemi eklendi / notification system added via Adw.ToastOverlay
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # M4K: Adw.ToolbarView ile header + içerik ayrımı sağlandı / header and content separation achieved via Adw.ToolbarView
        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        # --- Header Bar ---
        self._build_header(toolbar_view)

        # --- Scrollable içerik ---
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        toolbar_view.set_content(scroll)

        # M4K: Adw.Clamp ile max genişlik kısıtlandı; enterprise tek sütun layout / max width constrained via Adw.Clamp; single-column enterprise layout
        clamp = Adw.Clamp()
        clamp.set_maximum_size(760)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(20)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(box)

        self._build_system_group(box)
        self._build_tweaks_group(box)
        self._build_telemetry_group(box)
        self._build_profiles_group(box)
        self._build_log_group(box)

    def _build_header(self, toolbar_view: Adw.ToolbarView) -> None:
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # M4K: profil seçici dropdown header'a eklendi; enterprise UX için / profile selector dropdown added to header for enterprise UX
        self._profile_string_list = Gtk.StringList.new(["— Select Profile —"])
        self._profile_dropdown = Gtk.DropDown(model=self._profile_string_list)
        self._profile_dropdown.set_tooltip_text("Load a saved profile")
        self._profile_dropdown.connect("notify::selected", self._on_profile_dropdown_changed)
        header.pack_start(self._profile_dropdown)

        save_btn = Gtk.Button(icon_name="document-save-symbolic")
        save_btn.set_tooltip_text("Save current settings as profile")
        save_btn.add_css_class("flat")
        save_btn.connect("clicked", self._on_save_profile_clicked)
        header.pack_start(save_btn)

        # M4K: Gtk.Spinner apply sırasında header'da döner; async işlem görselleştirildi / Gtk.Spinner spins in the header during apply; async operation is visually indicated
        self._spinner = Gtk.Spinner()
        header.pack_end(self._spinner)

        self._apply_btn = Gtk.Button(label="Apply")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.connect("clicked", self._on_apply_clicked)
        header.pack_end(self._apply_btn)

    def _build_system_group(self, parent: Gtk.Box) -> None:
        # M4K: Adw.PreferencesGroup ile bölüm başlıkları ve açıklamaları eklendi / section titles and descriptions added via Adw.PreferencesGroup
        group = Adw.PreferencesGroup()
        group.set_title("System & Display")
        group.set_description("Current GPU configuration and display output")
        parent.append(group)

        # Ekran çıkış satırı
        self._display_row = Adw.ActionRow()
        self._display_row.set_title("Active Display Output")
        self._display_row.set_subtitle(self._ctrl.output_name)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.add_css_class("flat")
        refresh_btn.set_tooltip_text("Re-detect display and PRIME mode")
        refresh_btn.connect("clicked", lambda _: self._refresh_system_info())
        self._display_row.add_suffix(refresh_btn)
        group.add(self._display_row)

        # PRIME modu satırı
        prime_row = Adw.ActionRow()
        prime_row.set_title("PRIME GPU Mode")
        prime_row.set_subtitle("Logout or reboot required after change")

        # M4K: GTK4'te RadioButton kaldırıldı; CheckButton(group=) kullanıldı / RadioButton removed in GTK4; CheckButton(group=) used instead
        prime_box = Gtk.Box(spacing=12)
        prime_box.set_valign(Gtk.Align.CENTER)
        self._rb_intel = Gtk.CheckButton(label="intel")
        self._rb_ondemand = Gtk.CheckButton(label="on-demand", group=self._rb_intel)
        self._rb_nvidia = Gtk.CheckButton(label="nvidia", group=self._rb_intel)
        prime_box.append(self._rb_intel)
        prime_box.append(self._rb_ondemand)
        prime_box.append(self._rb_nvidia)
        prime_row.add_suffix(prime_box)
        group.add(prime_row)

        self._set_prime_radio(self._ctrl.prime_mode)

    def _build_tweaks_group(self, parent: Gtk.Box) -> None:
        group = Adw.PreferencesGroup()
        group.set_title("NVIDIA Display Tweaks")
        group.set_description("Applied immediately to the current X session")
        parent.append(group)

        # M4K: Adw.ActionRow + Gtk.Switch kullanıldı; Adw.SwitchRow libadwaita 1.4+ gerektirir / Adw.ActionRow + Gtk.Switch used; Adw.SwitchRow requires libadwaita 1.4+
        self._sw_comp, _ = self._make_switch_row(
            group, "Force Composition Pipeline", "Eliminates screen tearing (ForceCompositionPipeline=On)"
        )
        self._sw_fullrgb, _ = self._make_switch_row(
            group, "Force RGB Full Range", "ColorSpace=RGB · ColorRange=Full"
        )
        self._sw_autostart, _ = self._make_switch_row(
            group, "Autostart on Login", "Writes .desktop entry to ~/.config/autostart"
        )
        self._sw_persist, _ = self._make_switch_row(
            group, "Persistence Mode", "Keeps NVIDIA driver loaded between sessions (sudo)"
        )

        import gpu_core as core
        self._sw_autostart.set_active(core.autostart_exists())

        # Kilitli saat satırı
        clocks_row = Adw.ActionRow()
        clocks_row.set_title("Locked Clocks (MHz)")
        clocks_row.set_subtitle("Optional: pin GPU frequency range (sudo nvidia-smi -lgc)")
        clocks_box = Gtk.Box(spacing=8)
        clocks_box.set_valign(Gtk.Align.CENTER)
        self._ent_min = Gtk.Entry()
        self._ent_min.set_placeholder_text("min")
        self._ent_min.set_max_width_chars(7)
        sep = Gtk.Label(label="–")
        sep.add_css_class("dim-label")
        self._ent_max = Gtk.Entry()
        self._ent_max.set_placeholder_text("max")
        self._ent_max.set_max_width_chars(7)
        clocks_box.append(self._ent_min)
        clocks_box.append(sep)
        clocks_box.append(self._ent_max)
        clocks_row.add_suffix(clocks_box)
        group.add(clocks_row)

    def _build_telemetry_group(self, parent: Gtk.Box) -> None:
        group = Adw.PreferencesGroup()
        group.set_title("Telemetry")
        group.set_description(f"Live GPU metrics · refreshes every {_TELE_REFRESH}s")
        parent.append(group)

        # M4K: her telemetri değeri ayrı Adw.ActionRow'da gösteriliyor; okunabilirlik arttı / each telemetry value shown in its own Adw.ActionRow; readability improved
        self._lbl_temp = self._make_telemetry_row(group, "Temperature", "temp-symbolic")
        self._lbl_clk = self._make_telemetry_row(group, "Core Clock", "utilities-system-monitor-symbolic")
        self._lbl_fan = self._make_telemetry_row(group, "Fan Speed", "weather-windy-symbolic")
        self._lbl_pwr = self._make_telemetry_row(group, "Power Draw", "battery-symbolic")

    def _build_profiles_group(self, parent: Gtk.Box) -> None:
        # M4K: profiller dinamik Adw.PreferencesGroup satırları olarak listeleniyor / profiles listed as dynamic Adw.PreferencesGroup rows
        self._profiles_group = Adw.PreferencesGroup()
        self._profiles_group.set_title("Profiles")
        self._profiles_group.set_description("Saved GPU setting presets")
        parent.append(self._profiles_group)

    def _build_log_group(self, parent: Gtk.Box) -> None:
        log_group = Adw.PreferencesGroup()
        log_group.set_title("Output Log")
        parent.append(log_group)

        log_row = Adw.ActionRow()
        log_row.set_activatable(False)

        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        log_box.set_margin_top(8)
        log_box.set_margin_bottom(8)

        # Log seviye seçici
        level_box = Gtk.Box(spacing=8)
        level_box.append(Gtk.Label(label="Log level:"))
        # M4K: GTK4'te ComboBoxText kaldırıldı; Gtk.DropDown + Gtk.StringList kullanıldı / ComboBoxText removed in GTK4; Gtk.DropDown + Gtk.StringList used instead
        level_model = Gtk.StringList.new(_LOG_LEVELS)
        self._log_dropdown = Gtk.DropDown(model=level_model)
        self._log_dropdown.set_selected(1)  # INFO
        self._log_dropdown.connect("notify::selected", self._on_log_level_changed)
        level_box.append(self._log_dropdown)
        log_box.append(level_box)

        self._logview = Gtk.TextView()
        self._logview.set_editable(False)
        self._logview.set_monospace(True)
        self._logview.set_size_request(-1, 150)
        self._logbuf = self._logview.get_buffer()

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_child(self._logview)
        log_box.append(log_scroll)

        log_row.set_child(log_box)
        log_group.add(log_row)

    # -----------------------------------------------------------------------
    # Widget fabrika yardımcıları
    # -----------------------------------------------------------------------

    def _make_switch_row(self, group: Adw.PreferencesGroup, title: str, subtitle: str):
        """Adw.ActionRow + Gtk.Switch çifti oluşturur."""
        # M4K: Switch row factory; Adw.SwitchRow yerine kullanıldı (uyumluluk) / switch row factory; used instead of Adw.SwitchRow for compatibility
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_subtitle(subtitle)
        sw = Gtk.Switch()
        sw.set_valign(Gtk.Align.CENTER)
        row.add_suffix(sw)
        row.set_activatable_widget(sw)
        group.add(row)
        return sw, row

    def _make_telemetry_row(self, group: Adw.PreferencesGroup, title: str, icon: str) -> Gtk.Label:
        """Telemetri değer satırı oluşturur; değer etiketi döndürür."""
        row = Adw.ActionRow()
        row.set_title(title)
        lbl = Gtk.Label(label="—")
        lbl.add_css_class("dim-label")
        lbl.add_css_class("numeric")
        row.add_suffix(lbl)
        group.add(row)
        return lbl

    # -----------------------------------------------------------------------
    # Profil UI
    # -----------------------------------------------------------------------

    def _refresh_profiles_list(self) -> None:
        """Profil listesini ve dropdown'ı yeniden çizer."""
        # M4K: mevcut satırlar temizlenip yeniden oluşturuluyor; dinamik profil listesi / existing rows cleared and rebuilt; dynamic profile list
        for row in self._profile_rows:
            self._profiles_group.remove(row)
        self._profile_rows = []

        profiles = self._ctrl.get_profiles()

        # Dropdown güncelle
        names = ["— Select Profile —"] + [p.name for p in profiles]
        new_model = Gtk.StringList.new(names)
        self._profile_dropdown.set_model(new_model)
        self._profile_string_list = new_model

        if not profiles:
            empty = Adw.ActionRow()
            empty.set_title("No profiles yet")
            empty.set_subtitle("Click the save icon in the header to create one")
            self._profiles_group.add(empty)
            self._profile_rows.append(empty)
            return

        for profile in profiles:
            row = Adw.ActionRow()
            row.set_title(profile.name)
            row.set_subtitle(f"PRIME: {profile.prime_mode}  ·  comp: {'✓' if profile.comp_pipeline else '✗'}  ·  rgb: {'✓' if profile.full_rgb else '✗'}")

            load_btn = Gtk.Button(icon_name="document-open-symbolic")
            load_btn.set_valign(Gtk.Align.CENTER)
            load_btn.add_css_class("flat")
            load_btn.set_tooltip_text(f"Load '{profile.name}'")
            load_btn.connect("clicked", lambda _, p=profile: self._load_profile(p))

            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.add_css_class("flat")
            del_btn.add_css_class("destructive-action")
            del_btn.set_tooltip_text(f"Delete '{profile.name}'")
            del_btn.connect("clicked", lambda _, name=profile.name: self._delete_profile(name))

            row.add_suffix(load_btn)
            row.add_suffix(del_btn)
            self._profiles_group.add(row)
            self._profile_rows.append(row)

    def _load_profile(self, profile: GpuProfile) -> None:
        """Profil ayarlarını widget'lara yansıtır."""
        # M4K: profil yüklenince tüm widget state'leri güncelleniyor / all widget states updated when a profile is loaded
        self._set_prime_radio(profile.prime_mode)
        self._sw_comp.set_active(profile.comp_pipeline)
        self._sw_fullrgb.set_active(profile.full_rgb)
        self._sw_autostart.set_active(profile.autostart)
        self._sw_persist.set_active(profile.persistence)
        self._ent_min.set_text(str(profile.min_clk) if profile.min_clk else "")
        self._ent_max.set_text(str(profile.max_clk) if profile.max_clk else "")
        self._show_toast(f"Profile '{profile.name}' loaded")
        self._log("INFO", f"Profile loaded: {profile.name}")

    def _delete_profile(self, name: str) -> None:
        self._ctrl.delete_profile(name)
        self._refresh_profiles_list()
        self._show_toast(f"Profile '{name}' deleted")

    # -----------------------------------------------------------------------
    # Sinyal işleyiciler
    # -----------------------------------------------------------------------

    def _on_profile_dropdown_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        if idx == 0:
            return
        profiles = self._ctrl.get_profiles()
        if 0 < idx <= len(profiles):
            self._load_profile(profiles[idx - 1])

    def _on_save_profile_clicked(self, _btn) -> None:
        """Mevcut ayarları profil olarak kaydetmek için dialog açar."""
        # M4K: Adw.MessageDialog ile modal kayıt dialog'u oluşturuldu / modal save dialog created via Adw.MessageDialog
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Save Profile",
            body="Enter a name for this GPU profile:",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("e.g. Gaming, Battery Saver, Presentation")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def _on_response(d, response):
            name = entry.get_text().strip()
            if response == "save" and name:
                min_txt = self._ent_min.get_text().strip()
                max_txt = self._ent_max.get_text().strip()
                profile = GpuProfile(
                    name=name,
                    prime_mode=self._get_prime_radio(),
                    comp_pipeline=self._sw_comp.get_active(),
                    full_rgb=self._sw_fullrgb.get_active(),
                    autostart=self._sw_autostart.get_active(),
                    persistence=self._sw_persist.get_active(),
                    min_clk=int(min_txt) if min_txt.isdigit() else None,
                    max_clk=int(max_txt) if max_txt.isdigit() else None,
                )
                self._ctrl.save_profile(profile)
                self._refresh_profiles_list()
                self._show_toast(f"Profile '{name}' saved")
                self._log("INFO", f"Profile saved: {name}")

        dialog.connect("response", _on_response)
        dialog.present()

    def _on_log_level_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        self._min_log_level = dropdown.get_selected()

    def _on_apply_clicked(self, _btn) -> None:
        """Apply butonuna basıldığında async apply başlatır."""
        if self._applying:
            return

        min_txt = self._ent_min.get_text().strip()
        max_txt = self._ent_max.get_text().strip()

        settings = ApplySettings(
            prime_mode=self._get_prime_radio(),
            comp_pipeline=self._sw_comp.get_active(),
            full_rgb=self._sw_fullrgb.get_active(),
            autostart=self._sw_autostart.get_active(),
            persistence=self._sw_persist.get_active(),
            min_clk=int(min_txt) if min_txt.isdigit() else None,
            max_clk=int(max_txt) if max_txt.isdigit() else None,
        )

        self._set_applying(True)

        # M4K: log callback GLib.idle_add içine sarıldı; GUI thread'i dışından çağrı güvenli / log callback wrapped in GLib.idle_add; safe to call from outside the GUI thread
        def _on_log(level: str, msg: str):
            GLib.idle_add(lambda: self._log(level, msg))

        def _on_done(success: bool):
            def _finish():
                self._set_applying(False)
                self._display_row.set_subtitle(self._ctrl.output_name)
                if success:
                    self._show_toast("Settings applied successfully")
                else:
                    self._show_toast("Apply failed — check the log")
            GLib.idle_add(_finish)

        self._ctrl.apply_async(settings, _on_log, _on_done)

    # -----------------------------------------------------------------------
    # Yardımcı metodlar
    # -----------------------------------------------------------------------

    def _set_prime_radio(self, mode: str) -> None:
        if mode == "intel":
            self._rb_intel.set_active(True)
        elif mode == "nvidia":
            self._rb_nvidia.set_active(True)
        else:
            self._rb_ondemand.set_active(True)

    def _get_prime_radio(self) -> str:
        if self._rb_intel.get_active():
            return "intel"
        if self._rb_nvidia.get_active():
            return "nvidia"
        return "on-demand"

    def _set_applying(self, applying: bool) -> None:
        """Apply butonunu ve spinner'ı async durumuyla senkronize eder."""
        # M4K: apply sırasında buton devre dışı bırakılıyor; çift tıklama önleniyor / button disabled during apply; prevents double-click
        self._applying = applying
        self._apply_btn.set_sensitive(not applying)
        if applying:
            self._spinner.start()
        else:
            self._spinner.stop()

    def _log(self, level: str, msg: str) -> None:
        level_idx = _LOG_LEVELS.index(level) if level in _LOG_LEVELS else 1
        if level_idx < self._min_log_level:
            return
        import gpu_core as core
        line = f"{core.APP_TAG} [{level}] {msg}\n"
        end = self._logbuf.get_end_iter()
        self._logbuf.insert(end, line)
        end2 = self._logbuf.get_end_iter()
        self._logview.scroll_to_iter(end2, 0.0, False, 0.0, 1.0)

    def _show_toast(self, msg: str) -> None:
        """Adw.Toast bildirimi gösterir."""
        toast = Adw.Toast(title=msg)
        toast.set_timeout(3)
        self._toast_overlay.add_toast(toast)

    def _refresh_system_info(self) -> None:
        self._ctrl.detect_display()
        self._ctrl.detect_prime()
        self._display_row.set_subtitle(self._ctrl.output_name)
        self._set_prime_radio(self._ctrl.prime_mode)
        self._log("INFO", f"Refreshed: display={self._ctrl.output_name}, PRIME={self._ctrl.prime_mode}")

    def _start_telemetry(self) -> None:
        import gpu_core as core
        if core.have("nvidia-smi"):
            # M4K: telemetri timer arka planda çalışıyor; GUI thread'ini bloklamıyor / telemetry timer runs in the background; does not block the GUI thread
            self._telemetry_timer_id = GLib.timeout_add_seconds(
                _TELE_REFRESH, self._on_telemetry_tick
            )
        else:
            self._log("WARN", "nvidia-smi not found; telemetry disabled.")
        self._log("INFO", f"Display: {self._ctrl.output_name}")
        self._log("INFO", f"PRIME mode: {self._ctrl.prime_mode}")

    def _on_telemetry_tick(self) -> bool:
        """Telemetri değerlerini günceller; GLib timer callback'i."""
        tele = self._ctrl.refresh_telemetry()
        self._lbl_temp.set_text(f"{tele.tempC:.0f} °C" if tele.tempC is not None else "—")
        self._lbl_clk.set_text(f"{tele.clkMHz:.0f} MHz" if tele.clkMHz is not None else "—")

        if tele.fanPct is not None:
            self._lbl_fan.set_text(f"{tele.fanPct:.0f} %")
        elif tele.fanRaw and tele.fanRaw.upper() == "N/A":
            self._lbl_fan.set_text("N/A")
        else:
            self._lbl_fan.set_text("—")

        if tele.pwrW is not None and tele.pwrCap is not None:
            self._lbl_pwr.set_text(f"{tele.pwrW:.1f} / {tele.pwrCap:.1f} W")
        elif tele.pwrW is not None:
            self._lbl_pwr.set_text(f"{tele.pwrW:.1f} W")
        else:
            self._lbl_pwr.set_text("—")

        return True  # timer'ı sürdür

    def _setup_tray(self) -> None:
        """pystray ile sistem tepsisi ikonu oluşturur (opsiyonel) / creates system tray icon via pystray (optional)."""
        # M4K: pystray + Pillow opsiyonel; eksikse sessizce atlanıyor / pystray + Pillow are optional; silently skipped if missing
        try:
            import pystray
            from PIL import Image, ImageDraw

            # M4K: basit yeşil daire ikonu oluşturuluyor; harici dosya gerekmez / simple green circle icon created; no external file needed
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((4, 4, 60, 60), fill=(74, 194, 80, 255))

            menu = pystray.Menu(
                pystray.MenuItem(
                    "Show GPU Switcher",
                    lambda _icon, _item: GLib.idle_add(self.present),
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Quit",
                    lambda _icon, _item: GLib.idle_add(self.get_application().quit),
                ),
            )
            # M4K: pystray.Icon kendi thread'inde çalışıyor; GTK main loop'u bloklamıyor / pystray.Icon runs in its own thread; does not block GTK main loop
            self._tray = pystray.Icon("gpu-switcher", img, "GPU Switcher", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
            self._log("INFO", "Tray icon active (pystray). / Tepsi ikonu etkin (pystray).")
        except ImportError:
            self._tray = None
        except Exception as e:
            self._tray = None
            self._log("WARN", f"Tray icon unavailable: {e}")

    def do_close_request(self) -> bool:
        # M4K: tepsi ikonu aktifse pencere kapatılmıyor, sadece gizleniyor; arka planda çalışmaya devam eder / if tray is active, window is hidden instead of closed; continues running in background
        if self._tray is not None:
            self.hide()
            return True  # True = GTK'ya "kapat isteğini reddet" / True = tell GTK to reject the close request
        # M4K: tepsi yok → kapanırken telemetri timer temizleniyor / no tray → clean up telemetry timer on close
        if self._telemetry_timer_id is not None:
            GLib.source_remove(self._telemetry_timer_id)
            self._telemetry_timer_id = None
        return False


# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------

class GpuSwitcherApp(Adw.Application):
    """GTK4 + libadwaita uygulama nesnesi."""

    def __init__(self):
        # M4K: Gtk.Application yerine Adw.Application kullanıldı; tema otomatik takip edilir / Adw.Application used instead of Gtk.Application; theme follows system automatically
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._window: Optional[GpuSwitcherWindow] = None

    def do_activate(self) -> None:
        if not self._window:
            controller = GpuController()
            self._window = GpuSwitcherWindow(self, controller)
        self._window.present()

    def do_shutdown(self) -> None:
        # M4K: uygulama kapanırken tray ikonu durduruluyor; pystray thread temizleniyor / tray icon stopped on app shutdown; pystray thread cleaned up
        if self._window and self._window._tray is not None:
            try:
                self._window._tray.stop()
            except Exception:
                pass
        if self._window and self._window._telemetry_timer_id is not None:
            GLib.source_remove(self._window._telemetry_timer_id)
            self._window._telemetry_timer_id = None
        super().do_shutdown()


def main() -> None:
    app = GpuSwitcherApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
