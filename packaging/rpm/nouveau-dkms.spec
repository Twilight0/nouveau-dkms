Name:           nouveau-dkms
Version:        2.3.3
Release:        1%{?dist}
Summary:        Nouveau out-of-tree module with dynamic Fermi reclocking (DKMS)
License:        GPL-2.0-only
URL:            https://github.com/Twilight0/nouveau-dkms
Source0:        nouveau-source.tar.gz
Source1:        nouveau.patch
Source2:        dkms.conf
Source3:        nouveau.conf
Source4:        nouveau-load.conf

BuildArch:      noarch
Requires:       dkms >= 2.1.0.0
Requires:       kernel-devel
Recommends:     nouveau-utils
Conflicts:      nouveau-fermi-reclock-dkms

%description
Unified out-of-tree Nouveau DRM driver featuring dynamic core, shader, and
bidirectional DDR3/GDDR5 memory reclocking for NVIDIA Fermi architecture
(GF100, GF104, GF106, GF108, GF119). Includes zero-stutter VBlank onset
sync, 120Hz display floor protection, and unprivileged telemetry accounting.

%prep
%setup -q -c -T
tar -xzf %{SOURCE0}
patch -Np1 -d nouveau-source < %{SOURCE1}
sed 's/@PKGVER@/%{version}/g' %{SOURCE2} > dkms.conf

%build
# DKMS module compiles on the target system kernel during %%post

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}%{_usrsrc}/%{name}-%{version}
cp -r nouveau-source/* %{buildroot}%{_usrsrc}/%{name}-%{version}/
install -Dm644 dkms.conf %{buildroot}%{_usrsrc}/%{name}-%{version}/dkms.conf

# Configuration files
install -Dm644 %{SOURCE3} %{buildroot}%{_sysconfdir}/modprobe.d/nouveau.conf
install -Dm644 %{SOURCE4} %{buildroot}%{_prefix}/lib/modules-load.d/nouveau.conf

%post
if [ $1 -eq 1 ]; then
    dkms add -m %{name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || true
    dkms build -m %{name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || true
    dkms install -m %{name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || true
fi

%preun
if [ $1 -eq 0 ]; then
    dkms remove -m %{name} -v %{version} --all --rpm_safe_upgrade >/dev/null 2>&1 || true
fi

%files
%{_usrsrc}/%{name}-%{version}
%config(noreplace) %{_sysconfdir}/modprobe.d/nouveau.conf
%{_prefix}/lib/modules-load.d/nouveau.conf

%changelog
* Wed Nov 04 2026 Twilight0 <twilight0@vivaldi.net> - 2.3.3-1
- Release v2.3.3: Early module loading configuration for Plymouth and KMS.
- Install nouveau.conf to /usr/lib/modules-load.d/ for early KMS and Plymouth initialization.

* Tue Nov 03 2026 Twilight0 <twilight0@vivaldi.net> - 2.3.2-1
- Release v2.3.2: Fix Linux 7.2+ workqueue affinity and Plymouth boot hangs.
- Guard experimental Fermi PMU diagnostic self-tests behind NvFermiDiag option.
- Eliminate 8.5s PMU timeout preventing Plymouth quit handover to display manager.
- Specify WQ_PERCPU on Linux 7.2+ workqueue allocations to eliminate kernel WARN_ON.

* Tue Nov 03 2026 Twilight0 <twilight0@vivaldi.net> - 2.3.1-1
- Release v2.3.1: Fix DRIVER_GEM_GPUVA compatibility shim for Linux kernels >= 7.3.
- Prevent DRIVER_GEM_GPUVA definition omission on kernels < 7.3 to avoid boot crash.
- Synchronize packaging and prebuilt modules across AUR and AliveOS repository.

* Mon Nov 02 2026 Twilight0 <twilight0@vivaldi.net> - 2.3.0-1
- Release v2.3.0: Multi-kernel support (Linux 6.18 through 7.3) & modular patch queue.
- Centralized multi-kernel compatibility layer (nouveau_compat.h).
- Out-of-tree DKMS support across Linux 6.18 LTS, 7.2 Arch, and 7.3 CachyOS (Clang LLVM=1).
- Modularize patch queue into numbered universal and generation series (patches/series).
- Automated GitHub Actions multi-kernel CI matrix with install-ready cross-distro packages.

* Tue Oct 27 2026 Twilight0 <twilight0@vivaldi.net> - 2.2.3-1
- Release v2.2.3: Zero-tear VBlank sync leading edge guarantee.
- Disallow mid-VBlank reclocking starts to prevent raster scan overrun into active picture.
- Always synchronize reclocking to the true leading edge, ensuring complete execution inside blanking.

* Mon Oct 26 2026 Twilight0 <twilight0@vivaldi.net> - 2.2.2-1
- Release v2.2.2: 256-byte render target base alignment & stable recovery.
- Enforce 256-byte hardware alignment in nouveau_bo.c and nouveau_gem.c for Fermi+ color targets.
- Eliminate PGRAPH DATA_ERROR 00000004 [INVALID_VALUE] on method 0x0804.
- Restore solid upstream engine reset for graceful client recovery.

* Mon Oct 26 2026 Twilight0 <twilight0@vivaldi.net> - 2.2.1-1
- Release v2.2.1: Packaging and code separation.
- Pure DKMS kernel driver package cleanly decoupled from nouveau-utils.

* Mon Oct 26 2026 Twilight0 <twilight0@vivaldi.net> - 2.2.0-1
- Decouple nouveau-utils into standalone userspace package.
- Pure DKMS kernel module and modprobe directives.
