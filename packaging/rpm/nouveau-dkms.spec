Name:           nouveau-dkms
Version:        2.2.0
Release:        1%{?dist}
Summary:        Nouveau out-of-tree module with dynamic Fermi reclocking (DKMS)
License:        GPL-2.0-only
URL:            https://github.com/Twilight0/nouveau-dkms
Source0:        nouveau-source.tar.gz
Source1:        nouveau.patch
Source2:        dkms.conf
Source3:        nouveau.conf

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

# Configuration file
install -Dm644 %{SOURCE3} %{buildroot}%{_sysconfdir}/modprobe.d/nouveau.conf

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

%changelog
* Mon Oct 26 2026 Twilight0 <twilight0@vivaldi.net> - 2.2.0-1
- Decouple nouveau-utils into standalone userspace package.
- Pure DKMS kernel module and modprobe directives.
