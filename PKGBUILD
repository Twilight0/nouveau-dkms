# Maintainer: Twilight0 <https://github.com/Twilight0>
pkgname=nouveau-dkms
pkgver=2.1.0
pkgrel=1
pkgdesc="Unified Nouveau out-of-tree module with Fermi core, shader, and DDR3 memory reclocking (DKMS)"
arch=('x86_64')
url="https://github.com/Twilight0/nouveau-dkms"
license=('GPL-2.0-only')
depends=('dkms' 'python')
provides=('nouveau-fermi-reclock-dkms')
conflicts=('nouveau-fermi-reclock-dkms' 'nouveau-fermi-reclock-cachyos-lts-v2')
replaces=('nouveau-fermi-reclock-dkms')
backup=('etc/nouveau-dynclockd.conf')
source=(
  "https://github.com/Twilight0/nouveau-dkms/releases/download/v${pkgver}/nouveau-source.tar.gz"
  "nouveau.patch"
  "dkms.conf"
  "nouveau.conf"
  "nouveau-dynclockd.conf"
  "nouveau-dynclockd.py"
  "nouveau-dynclockd.service"
  "nouveau-ctrl"
  "nouveau-tui"
)
sha256sums=('1426cea7f5c4959cfcaec78b4974cde3071f51eb9fdf9beedf38efae0bc6b9ad'
            'efcf76af97471e399b2f048a1bb7545b5d8d5da9027d89f569fedfc73bcce842'
            'a11605844d840a0f701bfd45b0f9e200192b860be7c37e4390b86dd4a7938906'
            '326efac21bf858f7be0e41b21f2c585bfd1ef5b18dad9cce022685a4623bb090'
            'a28abe29db225765c93c03b02aec60ac6db4ad59826689fcad92e59d5ec8d69b'
            '2b8d254d3f0f341890e22898d59f787f79044e5728fae75bc2e9731e18292ff6'
            '87f698b1de37689cb3889bfae916ceaba1caca634ab6a653b1602bda613b20e4'
            'd69c3ff716892b2eb22cf2b8494f15117c1d85efcf0f03d3159b49c69916a294'
            'b868f1e1688c36e67cdff0bcb753cce891ed165c6a4b3811f3dc37d633bc1dc0')

prepare() {
  msg2 "Applying Fermi reclocking and 120Hz display patches..."
  patch -Np1 -d "${srcdir}/nouveau-source" < "${srcdir}/nouveau.patch"

  # Replace @PKGVER@ in dkms.conf
  sed "s/@PKGVER@/${pkgver}/g" -i "${srcdir}/dkms.conf"
}

package() {
  local destdir="${pkgdir}/usr/src/${pkgname}-${pkgver}"
  install -d "${destdir}"
  
  # Copy pre-patched sources directly to the DKMS build directory
  cp -r "${srcdir}/nouveau-source/"* "${destdir}/"
  
  # Install dkms.conf
  install -Dm644 "${srcdir}/dkms.conf" "${destdir}/dkms.conf"

  # Install default modprobe configuration
  install -Dm644 "${srcdir}/nouveau.conf" "${pkgdir}/usr/lib/modprobe.d/nouveau.conf"

  # Install daemon configuration
  install -Dm644 "${srcdir}/nouveau-dynclockd.conf" "${pkgdir}/etc/nouveau-dynclockd.conf"

  # Install the dynamic clock daemon
  install -Dm755 "${srcdir}/nouveau-dynclockd.py" "${pkgdir}/usr/bin/nouveau-dynclockd.py"

  # Install systemd service
  install -Dm644 "${srcdir}/nouveau-dynclockd.service" "${pkgdir}/usr/lib/systemd/system/nouveau-dynclockd.service"

  # Install CLI management utility
  install -Dm755 "${srcdir}/nouveau-ctrl" "${pkgdir}/usr/bin/nouveau-ctrl"

  # Install interactive TUI reclocking & telemetry manager
  install -Dm755 "${srcdir}/nouveau-tui" "${pkgdir}/usr/bin/nouveau-tui"
}
