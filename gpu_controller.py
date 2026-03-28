#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_controller.py — MVC Controller katmanı
View (gpu_gui.py) ile Model (gpu_core.py) arasındaki köprü.
State yönetimi, async apply ve profil sistemi burada.
"""

# M4K: controller katmanı oluşturuldu; GUI'nin business logic'e doğrudan erişimi kaldırıldı / controller layer created; direct access from GUI to business logic removed
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional

import gpu_core as core
from gpu_config import load_config

_cfg = load_config()

# M4K: profil dosyası yolu config'den okunuyor; varsayılan ~/.config/gpu-switcher/profiles.yaml / profile file path read from config; default is ~/.config/gpu-switcher/profiles.yaml
PROFILES_PATH: str = os.path.expanduser(
    _cfg.get("profiles_path", "~/.config/gpu-switcher/profiles.yaml")
)


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------

@dataclass
class GpuProfile:
    """Kaydedilmiş GPU ayar seti."""
    # M4K: profil dataclass'ı oluşturuldu; YAML ile seri/deseri için asdict() uyumlu / profile dataclass created; compatible with asdict() for YAML serialization/deserialization
    name: str
    prime_mode: str = "on-demand"
    comp_pipeline: bool = False
    full_rgb: bool = False
    autostart: bool = False
    persistence: bool = False
    min_clk: Optional[int] = None
    max_clk: Optional[int] = None


@dataclass
class ApplySettings:
    """Tek seferlik apply işlemi için ayar paketi."""
    # M4K: view'den controller'a aktarılan ayar nesnesi; doğrudan widget state tutulmuyor / settings object passed from view to controller; no direct widget state stored
    prime_mode: str
    comp_pipeline: bool
    full_rgb: bool
    autostart: bool
    persistence: bool
    min_clk: Optional[int]
    max_clk: Optional[int]


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class GpuController:
    """
    GPU Switcher iş akışı kontrolcüsü.
    - Sistem durumunu algılar ve önbelleğe alır
    - Apply işlemlerini arka plan thread'inde çalıştırır
    - Profilleri YAML'a kaydeder/okur
    """

    def __init__(self):
        # M4K: başlangıçta sistem durumu algılanıyor; view init'ten önce hazır / system state detected at startup; ready before view initialization
        self.output_name: str = core.detect_display_output()
        self.prime_mode: str = core.detect_prime_mode()
        self._profiles: List[GpuProfile] = []
        self._load_profiles()

    # -----------------------------------------------------------------------
    # Sistem algılama
    # -----------------------------------------------------------------------

    def detect_display(self) -> str:
        """Ekran çıkışını yeniden algılar ve önbelleği günceller."""
        # M4K: state cache güncelleniyor; view set_subtitle ile yansıtır / state cache updated; view reflects it via set_subtitle
        self.output_name = core.detect_display_output()
        return self.output_name

    def detect_prime(self) -> str:
        """PRIME modunu yeniden algılar ve önbelleği günceller."""
        self.prime_mode = core.detect_prime_mode()
        return self.prime_mode

    def refresh_telemetry(self):
        """Anlık telemetri verisini döndürür."""
        return core.fetch_nvidia_telemetry()

    # -----------------------------------------------------------------------
    # Async apply
    # -----------------------------------------------------------------------

    def apply_async(
        self,
        settings: ApplySettings,
        on_log: Callable[[str, str], None],
        on_done: Callable[[bool], None],
    ) -> None:
        """
        Ayarları arka plan thread'inde uygular.
        on_log(level, msg) ve on_done(success) GLib.idle_add ile GUI thread'inden çağrılmalı.
        """
        # M4K: apply işlemi daemon thread'e taşındı; apply sırasında UI donmuyor / apply operation moved to daemon thread; UI stays responsive during apply
        t = threading.Thread(target=self._run_apply, args=(settings, on_log, on_done), daemon=True)
        t.start()

    def _run_apply(
        self,
        settings: ApplySettings,
        on_log: Callable[[str, str], None],
        on_done: Callable[[bool], None],
    ) -> None:
        # M4K: tüm core çağrıları bu thread içinde; hata yakalanıp on_done(False) ile bildirilir / all core calls run in this thread; errors are caught and reported via on_done(False)
        success = True
        try:
            logger = lambda msg: on_log("INFO", msg)

            if settings.prime_mode != self.prime_mode:
                on_log("INFO", f"Switching PRIME to '{settings.prime_mode}'...")
                core.apply_prime(settings.prime_mode, logger)
                self.prime_mode = core.detect_prime_mode()

            if settings.comp_pipeline:
                on_log("INFO", f"Applying ForceCompositionPipeline on {self.output_name}...")
                core.apply_force_comp_pipeline(self.output_name, logger)

            if settings.full_rgb:
                on_log("INFO", "Applying Full RGB range...")
                core.apply_full_rgb(logger)

            if settings.autostart:
                core.install_autostart(self.output_name, logger)
            else:
                core.remove_autostart(logger)

            core.set_persistence_mode(settings.persistence, logger)

            if settings.min_clk and settings.max_clk:
                core.set_locked_clocks(settings.min_clk, settings.max_clk, logger)

            on_log("INFO", "Apply finished.")

        except Exception as e:
            on_log("ERROR", f"Apply failed: {e}")
            success = False
        finally:
            on_done(success)

    # -----------------------------------------------------------------------
    # Profil yönetimi
    # -----------------------------------------------------------------------

    def get_profiles(self) -> List[GpuProfile]:
        """Mevcut profil listesinin kopyasını döndürür."""
        return list(self._profiles)

    def save_profile(self, profile: GpuProfile) -> bool:
        """Profili kaydeder; aynı isimde varsa üzerine yazar."""
        # M4K: aynı isimli profil varsa replace edilir; sıralama korunur / existing profile with same name is replaced; list order preserved
        self._profiles = [p for p in self._profiles if p.name != profile.name]
        self._profiles.append(profile)
        return self._persist_profiles()

    def delete_profile(self, name: str) -> bool:
        """İsme göre profil siler."""
        self._profiles = [p for p in self._profiles if p.name != name]
        return self._persist_profiles()

    def _load_profiles(self) -> None:
        # M4K: PyYAML yoksa veya dosya bozuksa profiller boş başlar; uygulama çökmez / if PyYAML is missing or file is corrupt, profiles start empty; app does not crash
        try:
            import yaml
            if not os.path.exists(PROFILES_PATH):
                return
            with open(PROFILES_PATH, "r") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "profiles" in data:
                for item in data["profiles"]:
                    if isinstance(item, dict) and "name" in item:
                        self._profiles.append(GpuProfile(**item))
        except Exception:
            pass

    def _persist_profiles(self) -> bool:
        # M4K: dizin yoksa oluşturuluyor; yazma hatası False döndürür, uygulama çökmez / directory created if missing; write errors return False, app does not crash
        try:
            import yaml
            os.makedirs(os.path.dirname(PROFILES_PATH), exist_ok=True)
            data = {"profiles": [asdict(p) for p in self._profiles]}
            with open(PROFILES_PATH, "w") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
            return True
        except Exception:
            return False
