#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_config.py — Config yükleyici
config.yaml varsa yükler, yoksa boş dict dönerek varsayılanlara düşer.
"""

# M4K: config yükleme mantığı ayrı bir modüle çıkarıldı; gpu_core ve gpu_gui buradan okur
import os
from typing import Any, Dict

# M4K: config dosyasının yolu bu modüle göre belirlendi
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config() -> Dict[str, Any]:
    """
    config.yaml dosyasını yükler.
    Dosya yoksa veya PyYAML kurulu değilse boş dict döner (graceful fallback).
    """
    # M4K: config yoksa uygulama çökmemeli; varsayılan değerlerle çalışmaya devam eder
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        import yaml  # M4K: PyYAML isteğe bağlı; kurulu değilse fallback devreye girer
        with open(_CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
