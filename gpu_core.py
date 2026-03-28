#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_core.py — Business logic katmanı
GPU Switcher uygulamasının tüm sistem çağrıları, algılama ve uygulama
mantığı burada toplanır. GTK veya UI bağımlılığı yoktur.
"""

# M4K: business logic gpu-switcher.py'den ayrı bir modüle taşındı; UI bağımlılığı sıfır
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from gpu_config import load_config

# M4K: config yüklenerek hardcoded sabitler dışa taşındı
_cfg = load_config()

APP_TAG: str = _cfg.get("app_tag", "[gpu-switcher]")

# M4K: autostart sabitleri config'den okunuyor; yoksa varsayılan kullanılır
AUTOSTART_DIR: str = os.path.expanduser(
    _cfg.get("autostart_dir", "~/.config/autostart")
)
AUTOSTART_DESKTOP: str = os.path.join(AUTOSTART_DIR, "nvidia-comp-pipeline.desktop")

# M4K: autostart komutu config'den okunuyor; %s placeholder kullanıldı — {} nvidia syntax ile çakışmaması için
AUTOSTART_CMD: str = _cfg.get(
    "autostart_cmd",
    'nvidia-settings --assign CurrentMetaMode="%s: 3840x2160_60 +0+0 '
    '{ForceCompositionPipeline=On, ForceFullCompositionPipeline=On}"',
)

# M4K: komut timeout'ları config'den okunuyor
_DEFAULT_TIMEOUT: int = _cfg.get("default_cmd_timeout", 10)
_TELEMETRY_TIMEOUT: int = _cfg.get("telemetry_cmd_timeout", 3)


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------

def which(cmd: str) -> Optional[str]:
    """Komutun PATH içindeki tam yolunu döndürür, bulunamazsa None."""
    # M4K: gpu-switcher.py'deki which() aynen taşındı
    for p in os.environ.get("PATH", "").split(os.pathsep):
        fp = os.path.join(p, cmd)
        if os.path.isfile(fp) and os.access(fp, os.X_OK):
            return fp
    return None


def run_cmd(cmd: str, timeout: int = _DEFAULT_TIMEOUT) -> Tuple[int, str, str]:
    """Shell komutunu güvenli biçimde çalıştırır; (rc, stdout, stderr) döner."""
    # M4K: gpu-switcher.py'deki run_cmd() aynen taşındı
    try:
        proc = subprocess.run(
            shlex.split(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            check=False,
            env=os.environ.copy(),
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def have(cmd: str) -> bool:
    """Komutun PATH'te var olup olmadığını kontrol eder."""
    # M4K: gpu-switcher.py'deki have() aynen taşındı
    return which(cmd) is not None


def ensure_dir(path: str) -> None:
    # M4K: gpu-switcher.py'deki ensure_dir() aynen taşındı
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Algılama
# ---------------------------------------------------------------------------

def detect_display_output() -> str:
    """
    Bağlı ekran çıkışını algılar; önce HDMI/DP tercih edilir,
    bulunamazsa 'HDMI-0' döner.
    """
    # M4K: gpu-switcher.py'deki detect_display_output() aynen taşındı
    if not have("xrandr"):
        return "HDMI-0"
    rc, out, _ = run_cmd("xrandr --verbose")
    if rc != 0 or not out:
        return "HDMI-0"
    lines = out.splitlines()
    connected = []
    for ln in lines:
        if " connected" in ln:
            name = ln.split()[0]
            if "disconnected" not in ln:
                connected.append(name)
    for n in connected:
        if n.startswith(("HDMI", "DP", "DVI", "DisplayPort")):
            return n
    if connected:
        return connected[0]
    return "HDMI-0"


def detect_prime_mode() -> str:
    """prime-select mevcut modunu döndürür; yoksa 'unknown'."""
    # M4K: gpu-switcher.py'deki detect_prime_mode() aynen taşındı
    if not have("prime-select"):
        return "unknown"
    rc, out, _ = run_cmd("prime-select query")
    if rc == 0 and out:
        return out.strip()
    return "unknown"


# ---------------------------------------------------------------------------
# NVIDIA telemetri
# ---------------------------------------------------------------------------

@dataclass
class Telemetry:
    # M4K: Telemetry dataclass'ı gpu-switcher.py'den aynen taşındı
    tempC: Optional[float] = None
    clkMHz: Optional[float] = None
    fanPct: Optional[float] = None
    pwrW: Optional[float] = None
    pwrCap: Optional[float] = None
    fanRaw: Optional[str] = None


def parse_float_safe(s: str) -> Optional[float]:
    # M4K: gpu-switcher.py'deki parse_float_safe() aynen taşındı
    try:
        return float(s)
    except Exception:
        return None


def fetch_nvidia_telemetry() -> Telemetry:
    """nvidia-smi üzerinden GPU telemetrisini çeker."""
    # M4K: gpu-switcher.py'deki fetch_nvidia_telemetry() aynen taşındı
    tele = Telemetry()
    if not have("nvidia-smi"):
        return tele
    q = (
        "nvidia-smi --query-gpu=temperature.gpu,clocks.gr,fan.speed,"
        "power.draw,power.limit --format=csv,noheader,nounits"
    )
    rc, out, _ = run_cmd(q, timeout=_TELEMETRY_TIMEOUT)
    if rc != 0 or not out:
        return tele
    line = out.splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 5:
        tele.tempC = parse_float_safe(parts[0])
        tele.clkMHz = parse_float_safe(parts[1])
        tele.fanRaw = parts[2]
        tele.fanPct = parse_float_safe(parts[2])
        tele.pwrW = parse_float_safe(parts[3])
        tele.pwrCap = parse_float_safe(parts[4])
    return tele


# ---------------------------------------------------------------------------
# Uygulama operasyonları
# ---------------------------------------------------------------------------

Logger = Callable[[str], None]


def apply_force_comp_pipeline(output_name: str, logger: Logger) -> bool:
    """ForceCompositionPipeline + FullCompositionPipeline ayarlar."""
    # M4K: gpu-switcher.py'deki apply_force_comp_pipeline() aynen taşındı
    if not have("nvidia-settings"):
        logger("nvidia-settings not found; cannot apply composition pipeline.")
        return False
    cmd = (
        f'nvidia-settings --assign CurrentMetaMode="'
        f'{output_name}: {{ForceCompositionPipeline=On, ForceFullCompositionPipeline=On}}"'
    )
    rc, _, err = run_cmd(cmd)
    if rc != 0:
        # M4K: fallback çözünürlük config'den okunuyor
        res = _cfg.get("fallback_resolution", "3840x2160_60")
        cmd2 = (
            f'nvidia-settings --assign CurrentMetaMode="'
            f'{output_name}: {res} +0+0 '
            f'{{ForceCompositionPipeline=On, ForceFullCompositionPipeline=On}}"'
        )
        rc2, _, err2 = run_cmd(cmd2)
        if rc2 != 0:
            logger(f"Failed to set ForceCompositionPipeline: {err2 or err}")
            return False
        logger("ForceCompositionPipeline applied (fallback meta).")
        return True
    logger("ForceCompositionPipeline applied.")
    return True


def apply_full_rgb(logger: Logger) -> bool:
    """ColorSpace=RGB ve ColorRange=Full ayarlar."""
    # M4K: gpu-switcher.py'deki apply_full_rgb() aynen taşındı
    if not have("nvidia-settings"):
        logger("nvidia-settings not found; cannot apply color space/range.")
        return False
    ok = True
    rc, _, _ = run_cmd("nvidia-settings --assign ColorSpace=0")
    if rc != 0:
        ok = False
    rc, _, _ = run_cmd("nvidia-settings --assign ColorRange=0")
    if rc != 0:
        ok = False
    if ok:
        logger("Color space set to RGB, full range enabled.")
    else:
        logger("Failed to set ColorSpace/ColorRange (may be harmless on some setups).")
    return ok


def set_persistence_mode(enable: bool, logger: Logger) -> bool:
    """NVIDIA persistence modunu etkinleştirir/devre dışı bırakır."""
    # M4K: gpu-switcher.py'deki set_persistence_mode() aynen taşındı
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


def set_locked_clocks(
    min_mhz: Optional[int], max_mhz: Optional[int], logger: Logger
) -> bool:
    """GPU saat hızlarını kilitler."""
    # M4K: gpu-switcher.py'deki set_locked_clocks() aynen taşındı
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


def apply_prime(mode: str, logger: Logger) -> bool:
    """prime-select ile GPU modunu değiştirir."""
    # M4K: gpu-switcher.py'deki apply_prime() aynen taşındı
    if not have("prime-select"):
        logger("prime-select not found; skipping PRIME mode switching.")
        return False
    if mode not in {"intel", "on-demand", "nvidia"}:
        logger(f"Invalid PRIME mode: {mode}")
        return False
    rc, out, err = run_cmd(f"pkexec prime-select {mode}", timeout=30)
    if rc != 0:
        rc2, out2, err2 = run_cmd(f"sudo prime-select {mode}", timeout=30)
        if rc2 != 0:
            logger(f"Failed to switch prime-select: {err2 or err or out2 or out}")
            return False
    logger(f"prime-select set to '{mode}'. A reboot or logout/login may be required.")
    return True


# ---------------------------------------------------------------------------
# Autostart
# ---------------------------------------------------------------------------

def install_autostart(output_name: str, logger: Logger) -> bool:
    """Composition pipeline autostart .desktop dosyasını yazar."""
    # M4K: gpu-switcher.py'deki install_autostart() aynen taşındı; AUTOSTART_CMD config'den geliyor
    ensure_dir(AUTOSTART_DIR)
    # M4K: .format() yerine % kullanıldı; nvidia-settings sözdizimindeki {} ile çakışmıyor
    cmdline = AUTOSTART_CMD % output_name
    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Exec={cmdline}\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Name=ForceCompositionPipeline\n"
    )
    try:
        with open(AUTOSTART_DESKTOP, "w") as f:
            f.write(desktop)
        logger(f"Autostart entry written: {AUTOSTART_DESKTOP}")
        return True
    except Exception as e:
        logger(f"Failed to write autostart entry: {e}")
        return False


def remove_autostart(logger: Logger) -> bool:
    """Autostart .desktop dosyasını siler."""
    # M4K: gpu-switcher.py'deki remove_autostart() aynen taşındı
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
    """Autostart dosyasının var olup olmadığını kontrol eder."""
    # M4K: gpu-switcher.py'deki autostart_exists() aynen taşındı
    return os.path.exists(AUTOSTART_DESKTOP)
