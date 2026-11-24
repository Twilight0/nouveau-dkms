#!/usr/bin/env bash
set -euo pipefail

for vt in /sys/class/vtconsole/vtcon*; do
  echo 0 | sudo tee "$vt/bind" >/dev/null
done

sudo modprobe -r nouveau
sudo modprobe nouveau

for vt in /sys/class/vtconsole/vtcon*; do
  echo 1 | sudo tee "$vt/bind" >/dev/null
done

echo "nouveau reloaded."
