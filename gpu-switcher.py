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

Mimari:
  gpu-switcher.py  → giriş noktası (bu dosya)
  gpu_gui.py       → GTK arayüz katmanı
  gpu_core.py      → business logic katmanı
  gpu_config.py    → config yükleyici
  config.yaml      → kullanıcı yapılandırması
"""

# M4K: gpu-switcher.py giriş noktasına indirgendi; tüm logic gpu_gui ve gpu_core'a taşındı
from gpu_gui import main

if __name__ == "__main__":
    main()
