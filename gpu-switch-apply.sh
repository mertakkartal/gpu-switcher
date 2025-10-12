#!/usr/bin/env bash

#Author: Mert Akkartal

# GPU Switcher Apply – headless helper (Xorg)
# set -x  # uncomment for verbose trace
set -Eeuo pipefail

APP_TAG="[gpu-switcher]"
AUTOSTART_DIR="${HOME}/.config/autostart"
AUTOSTART_DESKTOP="${AUTOSTART_DIR}/nvidia-comp-pipeline.desktop"

log() { printf "%s %s\n" "$APP_TAG" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Best-effort: ensure DISPLAY is set when running manually outside a desktop session.
if [[ -z "${DISPLAY:-}" ]]; then
  export DISPLAY=":0"
fi

# Warn if there is no active X session
if ! xset q &>/dev/null; then
  log "⚠️ Warning: DISPLAY not active (no X session detected). Some features may fail."
fi

# --- detect active X display output name ----------------------------------
# Returns something like HDMI-0 (NVIDIA Xorg) or HDMI-1-0 (Xorg PRIME) or eDP-1
pick_display() {
  if ! have xrandr; then
    echo "HDMI-0"; return 0
  fi

  mapfile -t CONNECTED < <(xrandr --query | awk '$2=="connected"{print $1}')
  if [[ ${#CONNECTED[@]} -eq 0 ]]; then
    echo "HDMI-0"; return 0
  fi

  local PRIMARY
  PRIMARY="$(xrandr --query | awk '/ connected primary/{print $1; exit}' || true)"

  _is_external() {
    [[ "$1" =~ ^(HDMI|DP|DVI|DisplayPort|USB-?C|HDMI-[0-9]-[0-9]|DP-[0-9]-[0-9]|DVI-.*)$ ]]
  }

  if [[ -n "${PRIMARY}" ]] && _is_external "${PRIMARY}"; then
    echo "${PRIMARY}"; return 0
  fi

  local o
  for o in "${CONNECTED[@]}"; do
    if _is_external "$o"; then
      echo "$o"; return 0
    fi
  done

  if [[ -n "${PRIMARY}" ]]; then
    echo "${PRIMARY}"; return 0
  fi

  echo "${CONNECTED[0]}"
}

apply_nvidia_meta() {
  local output="$1" mode="$2" force="$3" fforce="$4"
  local assign="CurrentMetaMode=${output}: ${mode} +0+0 {ForceCompositionPipeline=${force}, ForceFullCompositionPipeline=${fforce}}"
  log "\$ nvidia-settings --assign \"${assign}\""
  nvidia-settings --assign "${assign}"
}

apply_nvidia_color() {
  # ColorSpace: 0=RGB, 1=YCbCr444 ; ColorRange: 0=Full, 1=Limited
  local colorspace="$1" colorrange="$2"
  log "\$ nvidia-settings --assign ColorSpace=${colorspace} --assign ColorRange=${colorrange}"
  nvidia-settings --assign "ColorSpace=${colorspace}" --assign "ColorRange=${colorrange}"
}

enable_persistence() {
  if have nvidia-smi; then
    log "\$ sudo nvidia-smi -pm 1"
    sudo nvidia-smi -pm 1
  else
    log "nvidia-smi not found, skipping persistence."
  fi
}

lock_gpu_clocks() {
  local min="$1" max="$2"
  if [[ -n "${min}" && -n "${max}" ]]; then
    log "\$ sudo nvidia-smi -lgc ${min},${max}"
    sudo nvidia-smi -lgc "${min},${max}"
  fi
}

write_autostart() {
  local output="$1" mode="$2" force="$3" fforce="$4"
  mkdir -p "${AUTOSTART_DIR}"

  # Create skeleton .desktop
  cat > "${AUTOSTART_DESKTOP}" <<'EOF'
[Desktop Entry]
Type=Application
# Exec line will be overwritten below
Exec=true
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=ForceCompositionPipeline
EOF

  # Compose exact Exec line and patch it in
  local exec_cmd="nvidia-settings --assign CurrentMetaMode=\"${output}: ${mode} +0+0 {ForceCompositionPipeline=${force}, ForceFullCompositionPipeline=${fforce}}\""
  # escape & and / for sed
  local esc_cmd
  esc_cmd=$(printf '%s\n' "$exec_cmd" | sed 's/[&/]/\\&/g')
  sed -i "s/^Exec=.*/Exec=${esc_cmd}/" "${AUTOSTART_DESKTOP}"

  log "Autostart written -> ${AUTOSTART_DESKTOP}"
}

usage() {
  cat <<USAGE
Usage: $0 [--apply] [--persist] [--autostart on|off] [--output NAME] [--mode 3840x2160_60] [--clk-min N] [--clk-max N] [--force On|Off] [--fforce On|Off] [--colorspace 0|1] [--colorrange 0|1]
Defaults: output auto-detect, mode=3840x2160_60, Force=On, FullForce=On, Color: RGB Full
USAGE
}

main() {
  local do_apply=0 do_persist=0 autostart="off"
  local output="" mode="3840x2160_60" clk_min="" clk_max=""
  local force="On" fforce="On" colorspace=0 colorrange=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --apply)       do_apply=1 ;;
      --persist)     do_persist=1 ;;
      --autostart)   autostart="${2:-off}"; shift ;;
      --output)      output="${2:-}"; shift ;;
      --mode)        mode="${2:-3840x2160_60}"; shift ;;
      --clk-min)     clk_min="${2:-}"; shift ;;
      --clk-max)     clk_max="${2:-}"; shift ;;
      --force)       force="${2:-On}"; shift ;;
      --fforce)      fforce="${2:-On}"; shift ;;
      --colorspace)  colorspace="${2:-0}"; shift ;;
      --colorrange)  colorrange="${2:-0}"; shift ;;
      -h|--help)     usage; exit 0 ;;
      *) log "Unknown arg: $1"; usage; exit 1 ;;
    esac
    shift
  done

  if [[ -z "$output" ]]; then
    output="$(pick_display)"
  fi
  log "Selected output: ${output}"

  if (( do_apply )); then
    apply_nvidia_meta "$output" "$mode" "$force" "$fforce"
    apply_nvidia_color "$colorspace" "$colorrange"
  fi

  if (( do_persist )); then
    enable_persistence
    if [[ -n "$clk_min" || -n "$clk_max" ]]; then
      lock_gpu_clocks "$clk_min" "$clk_max"
    fi
  fi

  case "$autostart" in
    on)  write_autostart "$output" "$mode" "$force" "$fforce" ;;
    off) rm -f "${AUTOSTART_DESKTOP}" || true; log "Autostart removed (if existed)." ;;
    *)   log "Unknown --autostart value: $autostart"; usage; exit 1 ;;
  esac
}

main "$@"
