#!/usr/bin/env bash
# Extend root LVM to use all free space on the physical disk (one-time, requires sudo).
#
#   sudo ./scripts/openfdd_bench_extend_disk.sh
#
# Before: ~100G on / (rest of ~233G disk unused)
# After:  root uses full ubuntu-vg free extents
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: run with sudo: sudo $0" >&2
  exit 1
fi

LV_PATH="/dev/ubuntu-vg/ubuntu-lv"
[[ -b "$LV_PATH" ]] || LV_PATH="/dev/mapper/ubuntu--vg-ubuntu--lv"

echo "==> Before"
df -h /
vgs
lvs

echo "==> Grow partition (if needed) and PV"
if command -v growpart >/dev/null 2>&1; then
  growpart /dev/sda 3 || true
fi
pvresize /dev/sda3

echo "==> Extend logical volume to 100% of VG free space"
lvextend -l +100%FREE "$LV_PATH"

echo "==> Resize filesystem"
if xfs_info / >/dev/null 2>&1; then
  xfs_growfs /
else
  resize2fs "$LV_PATH"
fi

echo "==> After"
df -h /
vgs
lvs
echo "Done. Root should now use the full disk."
