# Maintainer: Twilight0 <https://github.com/Twilight0>
pkgname=nouveau-fermi-reclock-dkms
_pkgname=nouveau-fermi-reclock
pkgver=2.1.0
pkgrel=1
pkgdesc="Unified Nouveau out-of-tree module with Fermi core, shader, and DDR3 memory reclocking (DKMS)"
arch=('x86_64')
url="https://github.com/Twilight0/nouveau-fermi-reclock-dkms"
license=('GPL-2.0-only')
depends=('dkms' 'python')
backup=('etc/nouveau-dynclockd.conf')
source=(
  "https://github.com/Twilight0/nouveau-fermi-reclock-dkms/releases/download/v${pkgver}/nouveau-source.tar.gz"
  "nouveau-fermi-reclock.patch"
  "dkms.conf"
  "nouveau-fermi-reclock.conf"
  "nouveau-dynclockd.conf"
  "nouveau-dynclockd.py"
  "nouveau-dynclockd.service"
  "nouveau-ctrl"
  "nouveau-tui"
)
sha256sums=('1426cea7f5c4959cfcaec78b4974cde3071f51eb9fdf9beedf38efae0bc6b9ad'
            '72c6e0a313bb994d48fef2053636f2819787b85d61710436e4b2368c8b400759'
            'f2876f7cc04ca907063832488f5f8488bd61d49e18886001bd87e545e53381a0'
            '80fd6268f03730c053c56ac67d9dfea450ac88e93b83aa60914d47dc218e4b97'
            'a28abe29db225765c93c03b02aec60ac6db4ad59826689fcad92e59d5ec8d69b'
            'e11287593184e6f0677ae14120b0392f23b3a70aaa20d737ef1bea4b6d6b5641'
            '87f698b1de37689cb3889bfae916ceaba1caca634ab6a653b1602bda613b20e4'
            'fb3708ba720b69f4bca302c1262b1bf14d0e310827c8fed078f37b771efa37de'
            '70822e3d4b126e731861584149819bf3adfbe44ea29eb109ca68b0b8911270e2')

prepare() {
  msg2 "Applying Fermi reclocking and 120Hz display patches..."
  patch -Np1 -d "${srcdir}/nouveau-source" < "${srcdir}/nouveau-fermi-reclock.patch"

  # Replace @PKGVER@ in dkms.conf
  sed "s/@PKGVER@/${pkgver}/g" -i "${srcdir}/dkms.conf"
}

package() {
  local destdir="${pkgdir}/usr/src/${_pkgname}-${pkgver}"
  install -d "${destdir}"
  
  # Copy pre-patched sources directly to the DKMS build directory
  cp -r "${srcdir}/nouveau-source/"* "${destdir}/"
  
  # Install dkms.conf
  install -Dm644 "${srcdir}/dkms.conf" "${destdir}/dkms.conf"

  # Install default modprobe configuration
  install -Dm644 "${srcdir}/nouveau-fermi-reclock.conf" "${pkgdir}/usr/lib/modprobe.d/nouveau-fermi-reclock.conf"

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
