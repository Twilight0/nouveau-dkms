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
Source4:        nouveau-dynclockd.conf
Source5:        nouveau-dynclockd.py
Source6:        nouveau-dynclockd.service
Source7:        nouveau-ctrl
Source8:        nouveau-tui
Source9:        apps.conf.sample

BuildArch:      noarch
Requires:       dkms >= 2.1.0.0
Requires:       kernel-devel
Requires:       python3
Requires:       libdrm
Conflicts:      nouveau-fermi-reclock-dkms

%description
Unified out-of-tree Nouveau DRM driver featuring dynamic core, shader, and
bidirectional DDR3/GDDR5 memory reclocking for NVIDIA Fermi architecture
(GF100, GF104, GF106, GF108, GF119). Includes zero-stutter VBlank onset
sync, 120Hz display floor protection, unprivileged telemetry snapshots,
and the nouveau-dynclockd background governor.

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

# Utilities
install -Dm755 %{SOURCE7} %{buildroot}%{_bindir}/nouveau-ctrl
install -Dm755 %{SOURCE8} %{buildroot}%{_bindir}/nouveau-tui
install -Dm755 %{SOURCE5} %{buildroot}%{_bindir}/nouveau-dynclockd.py
ln -sf nouveau-dynclockd.py %{buildroot}%{_bindir}/nouveau-dynclockd

# Configuration files
install -Dm644 %{SOURCE3} %{buildroot}%{_sysconfdir}/modprobe.d/nouveau.conf
install -Dm644 %{SOURCE4} %{buildroot}%{_sysconfdir}/nouveau-dynclockd.conf
mkdir -p %{buildroot}%{_sysconfdir}/nouveau-dynclockd.d
install -Dm644 %{SOURCE9} %{buildroot}%{_sysconfdir}/nouveau-dynclockd.d/apps.conf.sample

# Systemd service
install -Dm644 %{SOURCE6} %{buildroot}%{_unitdir}/nouveau-dynclockd.service

%post
if [ $1 -eq 1 ]; then
    dkms add -m %{name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || true
    dkms build -m %{name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || true
    dkms install -m %{name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || true
fi
%systemd_post nouveau-dynclockd.service

%preun
if [ $1 -eq 0 ]; then
    %systemd_preun nouveau-dynclockd.service
    dkms remove -m %{name} -v %{version} --all --rpm_safe_upgrade >/dev/null 2>&1 || true
fi

%postun
%systemd_postun_with_restart nouveau-dynclockd.service

%files
%{_usrsrc}/%{name}-%{version}
%{_bindir}/nouveau-ctrl
%{_bindir}/nouveau-tui
%{_bindir}/nouveau-dynclockd.py
%{_bindir}/nouveau-dynclockd
%{_unitdir}/nouveau-dynclockd.service
%config(noreplace) %{_sysconfdir}/modprobe.d/nouveau.conf
%config(noreplace) %{_sysconfdir}/nouveau-dynclockd.conf
%dir %{_sysconfdir}/nouveau-dynclockd.d
%{_sysconfdir}/nouveau-dynclockd.d/apps.conf.sample

%changelog
* Sun Oct 25 2026 Twilight0 <twilight0@vivaldi.net> - 2.2.0-1
- Release v2.2.0: Zero-stutter VBlank-onset memory reclocking.
- Governor modernization & zero-sudo telemetry (nouveau-dynclockd 2.0).
- 120Hz display floor guard & per-application profiles.
