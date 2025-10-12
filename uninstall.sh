#!/usr/bin/env bash

#Author: Mert Akkartal

# uninstall.sh — remove GPU Switcher autostart entries and local traces
# NOTE: By default this will NOT remove any system packages.
# Flags:
#   --gpu-reset     : Also run safe NVIDIA resets (disable persistence, reset locked clocks)
#   --yes           : Do not ask for confirmation (non-interactive)
#   --dry-run       : Show what would be removed, do nothing
#   --verbose       : Print extra details

set -Eeuo pipefail

APP_TAG="[gpu-switcher:uninstall]"
say() { printf "%s %s\n" "$APP_TAG" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

DRY_RUN=0
GPU_RESET=0
YES=0
VERBOSE=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --gpu-reset) GPU_RESET=1 ;;
    --yes)       YES=1 ;;
    --verbose)   VERBOSE=1 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--gpu-reset] [--yes] [--dry-run] [--verbose]

Removes autostart .desktop files created by setup/apply scripts and project-specific entries.
Does NOT remove apt packages.

Options:
  --gpu-reset   Disable NVIDIA persistence mode and reset locked graphics clocks (sudo needed)
  --yes         Do not prompt for confirmation
  --dry-run     Show actions without making changes
  --verbose     Print extra details
EOF
      exit 0
      ;;
    *)
      say "Unknown option: $arg"
      exit 1
      ;;
  esac
done

# Resolve repo dir (the directory containing this script)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_NAME="gpu-switcher"
AUTOSTART_DIR="${HOME}/.config/autostart"

# Candidates created by our setup/apply
CANDIDATES=(
  "${AUTOSTART_DIR}/gpu-switcher-autostart.desktop"
  "${AUTOSTART_DIR}/nvidia-comp-pipeline.desktop"
)

# Also remove any autostart .desktop that executes files inside this repo path (defensive cleanup)
mapfile -t EXTRA <<EOF || true
$(if [[ -d "$AUTOSTART_DIR" ]]; then
    grep -Ilr "^Exec=" "$AUTOSTART_DIR" 2>/dev/null \
    | while read -r file; do
        if grep -q "^Exec=.*${SCRIPT_DIR//\//\\/}" "$file"; then
          printf "%s\n" "$file"
        fi
      done
  fi)
EOF

# Merge & uniq list
declare -A seen
TO_REMOVE=()
for f in "${CANDIDATES[@]}"; do seen["$f"]=1; done
for f in "${EXTRA[@]:-}"; do seen["$f"]=1; done
for f in "${!seen[@]}"; do TO_REMOVE+=("$f"); done

if (( VERBOSE )); then
  say "Repo directory  : $SCRIPT_DIR"
  say "Autostart folder: $AUTOSTART_DIR"
  say "Files to inspect: ${#TO_REMOVE[@]}"
fi

confirm() {
  (( YES )) && return 0
  read -r -p "Proceed with uninstall (remove autostart entries)? [y/N] " ans
  [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]
}

do_rm() {
  local path="$1"
  if [[ -e "$path" ]]; then
    if (( DRY_RUN )); then
      say "(dry-run) rm -f -- $path"
    else
      rm -f -- "$path"
      say "Removed: $path"
    fi
  elif (( VERBOSE )); then
    say "Skip (not found): $path"
  fi
}

gpu_reset() {
  # Optional safe GPU cleanup: disable persistence and reset locked graphics clocks
  if ! have nvidia-smi; then
    say "nvidia-smi not found; skipping GPU reset."
    return 0
  fi
  say "About to reset NVIDIA persistence and locked clocks (sudo may prompt)."
  if (( DRY_RUN )); then
    say "(dry-run) sudo nvidia-smi -pm 0"
    say "(dry-run) sudo nvidia-smi -rgc"
    return 0
  fi
  sudo nvidia-smi -pm 0 || say "Warning: failed to disable persistence (non-fatal)."
  # Reset Graphics Clocks (clears -lgc constraints)
  sudo nvidia-smi -rgc || say "Warning: failed to reset locked clocks (non-fatal)."
  say "GPU reset steps attempted."
}

# --- Main ---
if ! confirm; then
  say "Cancelled by user."
  exit 0
fi

# Remove autostart entries
if [[ ! -d "$AUTOSTART_DIR" ]]; then
  (( VERBOSE )) && say "Autostart dir not present; nothing to remove."
else
  for f in "${TO_REMOVE[@]}"; do
    do_rm "$f"
  done
fi

# Optional GPU reset
if (( GPU_RESET )); then
  gpu_reset
fi

say "Uninstall completed."
if (( DRY_RUN )); then
  say "(dry-run) No changes were actually made."
fi
