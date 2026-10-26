#!/usr/bin/env bash
set -euo pipefail

VERSION="2.2.0"
PKGNAME="nouveau-dkms"
ARCH="all"
DEB_NAME="${PKGNAME}_${VERSION}-1_${ARCH}.deb"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d /tmp/deb_build.XXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "[*] Building Debian package: ${DEB_NAME}"

# 1. Prepare data directory
DATA_DIR="${WORK_DIR}/data"
mkdir -p "${DATA_DIR}"

make -C "${REPO_ROOT}" install DESTDIR="${DATA_DIR}" PREFIX=/usr

# 2. Prepare control directory
CONTROL_DIR="${WORK_DIR}/control"
mkdir -p "${CONTROL_DIR}"

# Calculate installed size in KB
INSTALLED_SIZE=$(du -sk "${DATA_DIR}" | awk '{print $1}')

cat > "${CONTROL_DIR}/control" <<EOF
Package: ${PKGNAME}
Version: ${VERSION}-1
Architecture: ${ARCH}
Maintainer: Twilight0 <twilight0@vivaldi.net>
Installed-Size: ${INSTALLED_SIZE}
Depends: dkms (>= 2.1.0.0)
Recommends: nouveau-utils, linux-headers-generic | linux-headers-amd64 | linux-headers
Section: kernel
Priority: optional
Homepage: https://github.com/Twilight0/nouveau-dkms
Description: Nouveau out-of-tree DRM module with dynamic Fermi reclocking (DKMS)
 Unified out-of-tree Nouveau DRM driver featuring dynamic core, shader, and
 bidirectional DDR3/GDDR5 memory reclocking for NVIDIA Fermi architecture
 (GF100, GF104, GF106, GF108, GF119). Includes zero-stutter VBlank onset
 sync, 120Hz display floor protection, unprivileged telemetry snapshots,
 and the nouveau-dynclockd background governor.
EOF

cp "${REPO_ROOT}/packaging/debian/nouveau-dkms.postinst" "${CONTROL_DIR}/postinst"
cp "${REPO_ROOT}/packaging/debian/nouveau-dkms.prerm" "${CONTROL_DIR}/prerm"
chmod 755 "${CONTROL_DIR}/postinst" "${CONTROL_DIR}/prerm"

# 3. Create debian-binary
echo "2.0" > "${WORK_DIR}/debian-binary"

# 4. Create control.tar.gz and data.tar.xz
tar --owner=0 --group=0 -czf "${WORK_DIR}/control.tar.gz" -C "${CONTROL_DIR}" .
tar --owner=0 --group=0 -cJf "${WORK_DIR}/data.tar.xz" -C "${DATA_DIR}" .

# 5. Pack deb
ar -rc "${REPO_ROOT}/${DEB_NAME}" "${WORK_DIR}/debian-binary" "${WORK_DIR}/control.tar.gz" "${WORK_DIR}/data.tar.xz"

echo "[✓] Built Debian package: ${REPO_ROOT}/${DEB_NAME}"
