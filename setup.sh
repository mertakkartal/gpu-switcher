#!/usr/bin/env bash

#Author: Mert Akkartal

# GPU Switcher – setup helper (Ubuntu 24.04, Xorg)
set -Eeuo pipefail

APP_TAG="[gpu-switcher:setup]"
log() { printf "%s %s\n" "$APP_TAG" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Resolve repo dir (works even if called via symlink)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"

# Paths inside repo
APPLY_SH="$REPO_DIR/gpu-switcher-apply.sh"
GUI_PY="$REPO_DIR/gpu-switcher.py"

# Autostart target
AUTOSTART_DIR="${HOME}/.config/autostart"
AUTOSTART_DESKTOP="${AUTOSTART_DIR}/gpu-switcher-autostart.desktop"

# ---------------------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------------------
if ! have sudo; then
  log "ERROR: 'sudo' not found. Please install or run as a user with sudo privileges."
  exit 1
fi

if [[ ! -f "$APPLY_SH" ]]; then
  log "ERROR: gpu-switcher-apply.sh not found at: $APPLY_SH"
  exit 1
fi

if [[ ! -f "$GUI_PY" ]]; then
  log "WARN: gpu-switcher.py not found at: $GUI_PY (GUI won’t run until you add it)"
fi

# Make sure scripts are executable
chmod +x "$APPLY_SH" || true
[[ -f "$GUI_PY" ]] && chmod +x "$GUI_PY" || true

# ---------------------------------------------------------------------------------------
# OS / session info
# ---------------------------------------------------------------------------------------
XDG_TYPE="${XDG_SESSION_TYPE:-}"
if [[ "$XDG_TYPE" != "x11" ]]; then
  log "NOTE: Current session is not Xorg (X11). Detected: '${XDG_TYPE:-unknown}'."
  log "      This tool targets Xorg. You can still install dependencies."
fi

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  log "Detected OS: ${NAME:-Unknown} ${VERSION:-}"
fi

# ---------------------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------------------
PKGS_COMMON=(
  # NVIDIA tools (version can differ; 550 is common on 24.04)
  nvidia-settings
  nvidia-utils-550

  # Xorg helpers
  x11-xserver-utils
  edid-decode

  # Python GTK GUI
  python3-gi
  gir1.2-gtk-3.0
  gir1.2-glib-2.0
  gir1.2-notify-0.7
  python3-psutil

  # (optional) tray support on some desktops
  gir1.2-appindicator3-0.1
)

log "Updating apt package lists (sudo)…"
sudo apt update -y

log "Installing required packages (sudo)…"
# Install in one shot; continue if some are already satisfied
sudo apt install -y "${PKGS_COMMON[@]}" || {
  log "WARN: Some packages failed to install. You can re-run later."
}

# ---------------------------------------------------------------------------------------
# Optional: create Autostart entry
# ---------------------------------------------------------------------------------------
log "Create an Autostart entry to apply NVIDIA composition pipeline on login? (y/N)"
read -r ans
ans="${ans,,}"
if [[ "$ans" == "y" || "$ans" == "yes" ]]; then
  mkdir -p "$AUTOSTART_DIR"

  # Recommended defaults for stutter-free 4K60 + RGB Full
  # NOTE: gpu-switcher-apply.sh will auto-detect output (HDMI/DP/…) at runtime.
  APPLY_CMD="$APPLY_SH --apply --persist --autostart on --mode 3840x2160_60 --colorspace 0 --colorrange 0"

  # Escape for .desktop Exec=
  ESC_APPLY_CMD="$(printf '%q ' $APPLY_SH --apply --persist --autostart on --mode 3840x2160_60 --colorspace 0 --colorrange 0 | sed 's/[ ]$//')"

  cat > "$AUTOSTART_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=GPU Switcher Apply (Xorg)
Comment=Apply NVIDIA composition pipeline and display tuning at login
Exec=${ESC_APPLY_CMD}
X-GNOME-Autostart-enabled=true
# Do not restrict to a single DE; comment OnlyShowIn to allow KDE/XFCE/etc.
# OnlyShowIn=GNOME;Unity;X-Cinnamon;MATE;XFCE;
EOF

  log "Autostart entry created:"
  log "  $AUTOSTART_DESKTOP"
  log "Exec line:"
  log "  $APPLY_CMD"
else
  log "Autostart creation skipped."
fi

# ---------------------------------------------------------------------------------------
# Final notes
# ---------------------------------------------------------------------------------------
log "Setup complete."
log "You can run the GUI (if present) with:"
log "  python3 \"$GUI_PY\""
log "Or apply headless right now:"
log "  \"$APPLY_SH\" --apply --persist --autostart on --mode 3840x2160_60 --colorspace 0 --colorrange 0"

