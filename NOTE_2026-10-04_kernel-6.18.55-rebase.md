# NOTE 2026-10-04: Rebase needed for kernel 6.18.55

AliveOS repo CI failed: https://github.com/Twilight0/aliveos-repo/actions/runs/37173473397
Job `build-repo`, step `Build Packages & Generate Repository Database`, exit 4.

Failure:
- `linux-cachyos-lts-v2 6.18.55-1` built OK.
- `nouveau-fermi-reclock-cachyos-lts-v2 2.0.1-3` failed in `build()`:
  `nouveau_display.c:767: drm_client_dev_suspend(dev, false) — expected 1 arg, have 2`
  `nouveau_display.c:798: drm_client_dev_resume(dev, false) — expected 1 arg, have 2`
  Header now: `void drm_client_dev_suspend(struct drm_device *dev);` (same for resume).

Last good: `6.18.52-1` (run 36288090162, 2026-09-27). Break introduced by CachyOS bump to `6.18.55-1` (2026-10-03).

Action: rebase `nouveau-source` against current mainline/CachyOS DRM client API, fix `nouveau_display.c:767,798` (and audit for other 6.18.53-55 breakage), then cut new release and update downstream `aliveos-repo` tarball sha256.

No fix applied in `aliveos-repo` yet — intentional, pending rebase here.
