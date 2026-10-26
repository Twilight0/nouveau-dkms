VERSION ?= 2.2.0
PKGNAME ?= nouveau-dkms
DESTDIR ?=
PREFIX ?= /usr

all:
	@echo "Nouveau Fermi Reclocking DKMS (v$(VERSION))"
	@echo "Available targets:"
	@echo "  make src-prep     - Extract and patch nouveau-source into build/nouveau-source"
	@echo "  make install      - Install module sources, binaries, and configs to DESTDIR"
	@echo "  make clean        - Clean build artifacts"

src-prep:
	rm -rf build/nouveau-source build/$(PKGNAME)-$(VERSION)
	mkdir -p build
	tar -xzf nouveau-source.tar.gz -C build/
	patch -Np1 -d build/nouveau-source < nouveau.patch
	mkdir -p build/$(PKGNAME)-$(VERSION)
	cp -r build/nouveau-source/* build/$(PKGNAME)-$(VERSION)/
	sed 's/@PKGVER@/$(VERSION)/g' dkms.conf > build/$(PKGNAME)-$(VERSION)/dkms.conf

install: src-prep
	# DKMS source
	install -d $(DESTDIR)$(PREFIX)/src/$(PKGNAME)-$(VERSION)
	cp -r build/$(PKGNAME)-$(VERSION)/* $(DESTDIR)$(PREFIX)/src/$(PKGNAME)-$(VERSION)/
	
	# Modprobe configuration
	install -Dm644 nouveau.conf $(DESTDIR)/etc/modprobe.d/nouveau.conf

clean:
	rm -rf build/ *.pkg.tar.zst *.deb *.rpm

.PHONY: all src-prep install clean
