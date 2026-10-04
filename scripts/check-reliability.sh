#!/usr/bin/env bash
# Offline checks: no corpus downloads, model calls, credentials, or vendor trees.
# Install requests==2.32.5 indexed-gzip==1.10.3 topk-sdk==0.15.0 for Python;
# expose playwright@1.63.0 on NODE_PATH and install Chromium for browser checks.
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-python}"
python_bin="${PYTHON:-python3}"
report_dir="${ATLAS_RELIABILITY_REPORT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/atlas-reliability.XXXXXX")}"
mkdir -p "$report_dir"
printf 'Reliability logs: %s\n' "$report_dir"
run_check() {
  local label="$1"
  shift
  "$@" 2>&1 | tee "$report_dir/$label.log"
}
case "$mode" in
  python)
    "$python_bin" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"; import requests, indexed_gzip, topk_sdk'
    for suite in tests tests_harvest tests_search tests_benchmark; do
      if [[ -d "$suite" ]]; then
        run_check "$suite" "$python_bin" -m unittest discover -s "$suite" -v
      fi
    done
    run_check fixture-validation "$python_bin" -m atlas validate data/fixtures/atlas-demo.json
    if [[ -f scripts/build_cloudflare.py ]]; then
      run_check cloud-build "$python_bin" scripts/build_cloudflare.py
      run_check cloud-build-verification "$python_bin" scripts/verify_cloudflare_build.py
    fi
    # The optional av decoder test may skip; installing a speech model is not required.
    ;;
  browser)
    node -e "require('playwright')"
    run_check frontend-webgl node scripts/check_frontend_reliability.cjs
    run_check frontend-canvas env ATLAS_DISABLE_WEBGL=1 node scripts/check_frontend_reliability.cjs
    if [[ -f scripts/check_proposal_browser.cjs ]]; then
      run_check proposal-browser node scripts/check_proposal_browser.cjs
    fi
    if [[ -f scripts/check_cluster_browser.cjs ]]; then
      run_check cloud-browser-build "$python_bin" scripts/build_cloudflare.py
      run_check cluster-browser-csp env ATLAS_CLUSTER_BUILD_DIR="$PWD/deploy/cloudflare/build/public" node scripts/check_cluster_browser.cjs
    fi
    ;;
  *) printf 'Usage: %s [python|browser]\n' "$0" >&2; exit 2 ;;
esac
