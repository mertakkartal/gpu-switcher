#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_config.py — Config yükleyici
config.yaml varsa yükler, yoksa boş dict dönerek varsayılanlara düşer.
"""

# M4K: config yükleme mantığı ayrı bir modüle çıkarıldı; gpu_core ve gpu_gui buradan okur / config loading logic extracted to its own module; gpu_core and gpu_gui read from here
import os
from typing import Any, Dict

# M4K: config dosyasının yolu bu modüle göre belirlendi / config file path resolved relative to this module
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config() -> Dict[str, Any]:
    """
    config.yaml dosyasını yükler.
    Dosya yoksa veya PyYAML kurulu değilse boş dict döner (graceful fallback).
    """
    # M4K: config yoksa uygulama çökmemeli; varsayılan değerlerle çalışmaya devam eder / if config is missing the app must not crash; continues with default values
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        import yaml  # M4K: PyYAML isteğe bağlı; kurulu değilse fallback devreye girer / PyYAML is optional; fallback activates if not installed
        with open(_CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
