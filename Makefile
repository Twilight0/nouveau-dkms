VERSION ?= 2.3.3
PKGNAME ?= nouveau-dkms
DESTDIR ?=
PREFIX ?= /usr

all:
	@echo "Nouveau Out-of-Tree DKMS Driver (v$(VERSION))"
	@echo "Available targets:"
	@echo "  make src-prep     - Extract and patch nouveau-source into build/nouveau-source"
	@echo "  make regen-patch  - Regenerate monolithic nouveau.patch from patches/series"
	@echo "  make check        - Verify patch queue (--fuzz=0) and upstream v6.18..v7.3 portability"
	@echo "  make test-compile - Compile nouveau.ko against installed kernel headers"
	@echo "  make install      - Install module sources, binaries, and configs to DESTDIR"
	@echo "  make clean        - Clean build artifacts"

src-prep:
	rm -rf build/nouveau-source build/$(PKGNAME)-$(VERSION)
	mkdir -p build
	tar -xzf nouveau-source.tar.gz -C build/
	@if [ -f patches/series ]; then \
		while IFS= read -r p || [ -n "$$p" ]; do \
			p="$${p%%#*}"; p="$$(echo "$$p" | xargs)"; \
			[ -z "$$p" ] && continue; \
			echo "Applying patches/$$p..."; \
			patch -Np1 -d build/nouveau-source < "patches/$$p"; \
		done < patches/series; \
	else \
		patch -Np1 -d build/nouveau-source < nouveau.patch; \
	fi
	mkdir -p build/$(PKGNAME)-$(VERSION)
	cp -r build/nouveau-source/* build/$(PKGNAME)-$(VERSION)/
	sed 's/@PKGVER@/$(VERSION)/g' dkms.conf > build/$(PKGNAME)-$(VERSION)/dkms.conf

regen-patch:
	@rm -f nouveau.patch
	@while IFS= read -r p || [ -n "$$p" ]; do \
		p="$${p%%#*}"; p="$$(echo "$$p" | xargs)"; \
		[ -z "$$p" ] && continue; \
		grep -v '^# ' "patches/$$p" >> nouveau.patch; \
	done < patches/series
	@echo "Regenerated nouveau.patch from patches/series."

check:
	bash testing/test-kernel-matrix.sh --check-series --upstream-matrix

test-compile:
	bash testing/test-kernel-matrix.sh --compile-installed

install: src-prep
	# DKMS source
	install -d $(DESTDIR)$(PREFIX)/src/$(PKGNAME)-$(VERSION)
	cp -r build/$(PKGNAME)-$(VERSION)/* $(DESTDIR)$(PREFIX)/src/$(PKGNAME)-$(VERSION)/
	
	# Modprobe and early module load configuration
	install -Dm644 nouveau.conf $(DESTDIR)/etc/modprobe.d/nouveau.conf
	install -Dm644 nouveau-load.conf $(DESTDIR)/usr/lib/modules-load.d/nouveau.conf

clean:
	rm -rf build/ *.pkg.tar.zst *.deb *.rpm

.PHONY: all src-prep regen-patch check test-compile install clean
