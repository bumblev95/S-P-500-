#!/usr/bin/env bash
# Run from the repository root. Used by publication and read-only PR validation.
# Crypto/shared checks are mandatory; stock snapshot checks belong to stock CI.
set -euo pipefail
node --check assets/crypto.js
node --check assets/spot-forecast.js
node --check assets/perp-engine.js
node --check assets/perp-page.js
node --check assets/decision-support.js
node scripts/test_crypto_page.cjs
node scripts/test_perp.cjs
node scripts/test_decision_support.cjs
