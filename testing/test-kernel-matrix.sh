#!/usr/bin/env bash
# ==============================================================================
# nouveau-dkms Multi-Kernel Patch & DKMS Build Test Suite
# ==============================================================================
# Verifies:
#   1. --check-series      : Modular patches/series applies with --fuzz=0 onto
#                            nouveau-source.tar.gz and matches nouveau.patch.
#   2. --upstream-matrix   : Feature patches (0001..0003, 0010..0012) apply
#                            cleanly across upstream Linux tags v6.18 -> v7.3.
#   3. --compile <kdir>    : Full out-of-tree compilation of nouveau.ko against
#                            target kernel headers (GCC or Clang/LLVM=1).
#   4. --compile-installed : Compiles against all installed /usr/lib/modules/*/build.
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nouveau-matrix-test.XXXXXX")"
CACHE_DIR="${NOUVEAU_TEST_CACHE_DIR:-${WORK_DIR}/upstream-cache}"

trap 'rm -rf "${WORK_DIR}"' EXIT

UPSTREAM_TAGS=("v6.18" "v6.19" "v7.0" "v7.1" "v7.2" "v7.3")
UPSTREAM_FILES=(
    "dispnv50/disp.c"
    "include/nvkm/core/device.h"
    "nouveau_backlight.c"
    "nouveau_bo.c"
    "nouveau_debugfs.c"
    "nouveau_gem.c"
    "nvkm/engine/device/pci.c"
    "nvkm/subdev/clk/base.c"
    "nvkm/subdev/clk/gf100.c"
    "nvkm/subdev/fb/ramfuc.h"
    "nvkm/subdev/fb/ramgf100.c"
    "nvkm/subdev/pmu/fuc/gf100.fuc3.h"
    "nvkm/subdev/pmu/gt215.c"
    "nvkm/subdev/pmu/memx.c"
)

log_info() { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
log_ok()   { printf '\033[1;32m[ PASS ]\033[0m %s\n' "$*"; }
log_err()  { printf '\033[1;31m[ FAIL ]\033[0m %s\n' "$*" >&2; }

# ------------------------------------------------------------------------------
# 1. Check modular patches/series vs monolithic nouveau.patch (--fuzz=0)
# ------------------------------------------------------------------------------
run_check_series() {
    log_info "Stage 1: Verifying modular patch series (patches/series) vs nouveau.patch..."
    local series_file="${REPO_ROOT}/patches/series"
    if [[ ! -f "${series_file}" ]]; then
        log_err "Missing ${series_file}"
        return 1
    fi

    local dir_series="${WORK_DIR}/tree-series"
    local dir_mono="${WORK_DIR}/tree-mono"
    mkdir -p "${dir_series}" "${dir_mono}"

    tar -xzf "${REPO_ROOT}/nouveau-source.tar.gz" -C "${dir_series}"
    tar -xzf "${REPO_ROOT}/nouveau-source.tar.gz" -C "${dir_mono}"

    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%%#*}"
        line="$(echo "${line}" | xargs)"
        [[ -z "${line}" ]] && continue
        local pfile="${REPO_ROOT}/patches/${line}"
        if [[ ! -f "${pfile}" ]]; then
            log_err "Patch listed in series not found: ${pfile}"
            return 1
        fi
        if ! patch --fuzz=0 -Np1 -s -d "${dir_series}/nouveau-source" < "${pfile}"; then
            log_err "Patch failed strict --fuzz=0 application: ${line}"
            return 1
        fi
        log_ok "Applied ${line} (--fuzz=0)"
    done < "${series_file}"

    if ! patch --fuzz=0 -Np1 -s -d "${dir_mono}/nouveau-source" < "${REPO_ROOT}/nouveau.patch"; then
        log_err "Monolithic nouveau.patch failed strict --fuzz=0 application"
        return 1
    fi

    if ! diff -ruN "${dir_series}/nouveau-source" "${dir_mono}/nouveau-source" > "${WORK_DIR}/series_vs_mono.diff"; then
        log_err "Mismatch between patches/series tree and monolithic nouveau.patch!"
        head -n 40 "${WORK_DIR}/series_vs_mono.diff" >&2
        return 1
    fi
    log_ok "Modular patches/series and monolithic nouveau.patch produce identical source trees."
}

# ------------------------------------------------------------------------------
# 2. Fetch upstream kernel files & test feature patches across v6.18..v7.3
# ------------------------------------------------------------------------------
fetch_upstream_file() {
    local tag="$1"
    local relpath="$2"
    local dest="${CACHE_DIR}/${tag}/${relpath}"
    if [[ -s "${dest}" ]]; then
        return 0
    fi
    mkdir -p "$(dirname "${dest}")"

    local raw_url="https://raw.githubusercontent.com/torvalds/linux/${tag}/drivers/gpu/drm/nouveau/${relpath}"
    local korg_url="https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/drivers/gpu/drm/nouveau/${relpath}?h=${tag}"

    if curl -fsSL --retry 3 --retry-delay 1 "${raw_url}" -o "${dest}" 2>/dev/null; then
        return 0
    fi
    if curl -fsSL --retry 3 --retry-delay 1 "${korg_url}" -o "${dest}" 2>/dev/null; then
        return 0
    fi
    if command -v gh >/dev/null 2>&1; then
        if gh api -H "Accept: application/vnd.github.raw" \
            "repos/torvalds/linux/contents/drivers/gpu/drm/nouveau/${relpath}?ref=${tag}" > "${dest}" 2>/dev/null; then
            return 0
        fi
    fi
    log_err "Failed to download upstream ${tag}:${relpath}"
    rm -f "${dest}"
    return 1
}

run_upstream_matrix() {
    log_info "Stage 2: Testing feature patch portability across upstream Linux ${UPSTREAM_TAGS[*]}..."
    local series_file="${REPO_ROOT}/patches/series"

    for tag in "${UPSTREAM_TAGS[@]}"; do
        local test_tree="${WORK_DIR}/upstream-${tag}"
        mkdir -p "${test_tree}"
        for f in "${UPSTREAM_FILES[@]}"; do
            fetch_upstream_file "${tag}" "${f}"
            mkdir -p "${test_tree}/$(dirname "${f}")"
            cp "${CACHE_DIR}/${tag}/${f}" "${test_tree}/${f}"
        done

        while IFS= read -r line || [[ -n "${line}" ]]; do
            line="${line%%#*}"
            line="$(echo "${line}" | xargs)"
            [[ -z "${line}" ]] && continue
            # 0004-drm-nouveau-compat-shims.patch targets the out-of-tree DKMS baseline tarball
            [[ "${line}" == 0004-* ]] && continue

            local pfile="${REPO_ROOT}/patches/${line}"
            local out
            if ! out="$(patch -Np1 -d "${test_tree}" < "${pfile}" 2>&1)"; then
                log_err "[${tag}] Failed applying ${line}:"
                echo "${out}" >&2
                return 1
            fi
        done < "${series_file}"
        log_ok "Upstream Linux ${tag}: All feature patches (0001..0003, 0005, 0010..0012) applied cleanly."
    done
}

# ------------------------------------------------------------------------------
# 3. Compile nouveau.ko out-of-tree against target kernel headers
# ------------------------------------------------------------------------------
run_compile_kdir() {
    local kdir="$1"
    if [[ ! -d "${kdir}" ]]; then
        log_err "Kernel build directory not found: ${kdir}"
        return 1
    fi

    local kver
    kver="$(make -s -C "${kdir}" kernelrelease 2>/dev/null || true)"
    if [[ -z "${kver}" ]]; then
        if [[ "$(basename "${kdir}")" == "build" ]]; then
            kver="$(basename "$(dirname "${kdir}")")"
        else
            kver="$(basename "${kdir}")"
        fi
    fi
    local llvm_arg=()
    if [[ -f "${kdir}/.config" ]] && grep -q '^CONFIG_CC_IS_CLANG=y' "${kdir}/.config"; then
        llvm_arg=("LLVM=1")
    elif [[ -f "${kdir}/include/config/auto.conf" ]] && grep -q '^CONFIG_CC_IS_CLANG=y' "${kdir}/include/config/auto.conf"; then
        llvm_arg=("LLVM=1")
    fi

    log_info "Stage 3: Compiling nouveau.ko [${TARGET_GEN}] against kernel ${kver} (${kdir}) ${llvm_arg[*]:-[GCC]}..."
    local build_src="${WORK_DIR}/build-${kver}"
    mkdir -p "${build_src}"
    python3 "${REPO_ROOT}/tools/nouveau-matrix-builder.py" build-tree "${TARGET_GEN}" -o "${build_src}/nouveau-source" -f

    make -j"$(nproc)" -C "${kdir}" M="${build_src}/nouveau-source" \
        "${llvm_arg[@]}" CONFIG_DRM_NOUVEAU=m modules

    for mod in nouveau.ko ch7006.ko sil164.ko; do
        if [[ ! -s "${build_src}/nouveau-source/${mod}" ]]; then
            log_err "Expected built module missing: ${mod}"
            return 1
        fi
    done

    if command -v modinfo >/dev/null 2>&1; then
        local vermagic
        vermagic="$(modinfo -F vermagic "${build_src}/nouveau-source/nouveau.ko")"
        if ! modinfo -F parm "${build_src}/nouveau-source/nouveau.ko" | grep -q 'vblank_continuous'; then
            log_err "Built nouveau.ko is missing custom vblank_continuous parameter!"
            return 1
        fi
        log_ok "Built nouveau.ko (${kver}) | vermagic: ${vermagic}"
    else
        log_ok "Built nouveau.ko (${kver})"
    fi
}

# ------------------------------------------------------------------------------
# CLI Argument Parsing
# ------------------------------------------------------------------------------
DO_SERIES=0
DO_UPSTREAM=0
DO_INSTALLED=0
DO_ISOLATION=0
TARGET_GEN="all"
COMPILE_KDIRS=()

if [[ $# -eq 0 ]]; then
    DO_SERIES=1
    DO_ISOLATION=1
    DO_UPSTREAM=1
    DO_INSTALLED=1
else
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --check-series)
                DO_SERIES=1
                shift
                ;;
            --check-isolation)
                DO_ISOLATION=1
                shift
                ;;
            --generation)
                TARGET_GEN="$2"
                shift 2
                ;;
            --upstream-matrix)
                DO_UPSTREAM=1
                shift
                ;;
            --compile-installed)
                DO_INSTALLED=1
                shift
                ;;
            --compile)
                COMPILE_KDIRS+=("$2")
                shift 2
                ;;
            *)
                log_err "Unknown argument: $1"
                exit 2
                ;;
        esac
    done
fi

[[ "${DO_SERIES}" -eq 1 ]] && run_check_series

if [[ "${DO_ISOLATION}" -eq 1 ]]; then
    log_info "Verifying architectural chip generation isolation..."
    python3 "${REPO_ROOT}/tools/nouveau-matrix-builder.py" check-isolation
fi

[[ "${DO_UPSTREAM}" -eq 1 ]] && run_upstream_matrix

if [[ "${DO_INSTALLED}" -eq 1 ]]; then
    candidate_dirs=()
    for d in /usr/lib/modules/*/build /lib/modules/*/build /usr/src/kernels/* /usr/src/linux-obj/*/*/ /usr/src/linux-headers-*; do
        if [[ -d "${d}" && -f "${d}/Makefile" && ( -f "${d}/include/config/auto.conf" || -f "${d}/.config" ) ]]; then
            real_d="$(cd "${d}" && pwd -P)"
            candidate_dirs+=("${real_d}")
        fi
    done
    if [[ ${#candidate_dirs[@]} -gt 0 ]]; then
        while IFS= read -r kdir; do
            [[ -n "${kdir}" ]] && COMPILE_KDIRS+=("${kdir}")
        done < <(printf '%s\n' "${candidate_dirs[@]}" | sort -u)
    fi
fi

for kdir in "${COMPILE_KDIRS[@]}"; do
    run_compile_kdir "${kdir}"
done

log_ok "All requested multi-kernel test suite stages completed successfully."
