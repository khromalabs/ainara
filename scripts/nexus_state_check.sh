#!/usr/bin/env bash
# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.

# Framework-level Nexus state check (app-agnostic).
#
# Verifies the FRAMEWORK side of the Nexus contract: dev_apps resolution,
# payload resolution, discovery plumbing, pybridge route contract, and
# generic per-app manifest sanity for every app declared in
# nexus.dev_apps (ainara.yaml). Nothing here may reference a specific
# Nexus application — each app repo owns its own state check (e.g.
# <app-repo>/scripts/state_check.sh) for skill baselines, dist artifacts
# and app-specific anchors.

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PY=""
for c in "$REPO/venv/bin/python" "$REPO/.venv/bin/python"; do
  [ -x "$c" ] && PY="$c" && break
done
[ -n "$PY" ] || { echo "FATAL: venv python not found"; exit 2; }

EXPECT_AINARA_BRANCH=dev012
EXPECT_AINARA_HEAD=0ef54636

PASS=0; FAIL=0; WARN=0
ok()   { PASS=$((PASS+1)); echo "PASS  $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL  $*"; }
warn() { WARN=$((WARN+1)); echo "WARN  $*"; }

echo "=== S1: framework repo ======================================"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"; HEAD="$(git rev-parse --short HEAD)"
[ "$BRANCH" = "$EXPECT_AINARA_BRANCH" ] && ok "ainara branch $BRANCH" \
  || bad "ainara branch '$BRANCH' (expected $EXPECT_AINARA_BRANCH)"
if git merge-base --is-ancestor "$EXPECT_AINARA_HEAD" HEAD 2>/dev/null; then
  ok "ainara HEAD $HEAD contains ledger anchor $EXPECT_AINARA_HEAD"
else
  bad "ainara HEAD $HEAD does NOT contain anchor $EXPECT_AINARA_HEAD (rebase/reset?)"
fi

echo "=== S2: interpreter & tools ================================="
echo "      venv: $("$PY" --version 2>&1)"
"$PY" -c "import aiohttp" 2>/dev/null && ok "bundle deps importable (aiohttp)" \
  || bad "aiohttp missing in venv — discovery probes will fail"

NEXUS_ROUTES=$(grep -c '@app.route("/nexus' ainara/framework/pybridge.py || true)
if [ "$NEXUS_ROUTES" -ge 6 ]; then
  ok "pybridge /nexus route contract ($NEXUS_ROUTES routes)"
else
  bad "pybridge /nexus routes missing (found $NEXUS_ROUTES, need >=6)"
fi

echo "=== S3: dev_apps config & roots ============================="
# Enumerate dev apps purely from config — the framework never names apps.
DEV_ROOTS="$("$PY" - <<'PYEOF'
from ainara.framework.config import config
roots = config.get_nexus_base_paths()
for r in roots:
    print(r)
PYEOF
)"
DEV_COUNT="$("$PY" - <<'PYEOF'
from ainara.framework.config import config
da = config._get_unscoped("nexus.dev_apps", {}) or {}
print(len(da))
PYEOF
)"
if [ "$DEV_COUNT" -ge 1 ] 2>/dev/null; then
  ok "nexus.dev_apps declares $DEV_COUNT dev app(s)"
else
  warn "nexus.dev_apps empty — no dev apps configured (installed apps only)"
fi

echo "=== S4: payload resolution (per dev app, identity-agnostic) ="
while IFS= read -r ROOT; do
  [ -z "$ROOT" ] && continue
  MANIFEST="$ROOT/payload/nexus.json"
  if [ ! -f "$MANIFEST" ]; then
    # Installed-app layout (nexus.json at top) or primary root: skip the
    # dev-repo probes; resolution itself is covered by the S5 probe.
    continue
  fi
  APP_OUT="$("$PY" - "$MANIFEST" <<'PYEOF'
import json, re, sys
d = json.load(open(sys.argv[1]))
m = d.get("manifest") or d
name = f"{m.get('provider','?')}/{m.get('name','?')}"
ver = str(m.get("version", ""))
cid = (m.get("creatorId") or "").strip()
print("IDENT:" + name)
print("VER_OK:" + str(bool(re.match(r"^\d+\.\d+\.\d+$", ver))))
print("CID_OK:" + str(bool(cid) and cid != "YOUR_SOLANA_PUBLIC_KEY_HERE"))
PYEOF
)"
  IDENT="$(sed -n 's/^IDENT://p' <<<"$APP_OUT")"
  VER_OK="$(sed -n 's/^VER_OK://p' <<<"$APP_OUT")"
  CID_OK="$(sed -n 's/^CID_OK://p' <<<"$APP_OUT")"
  [ "$VER_OK" = "True" ] && ok "$IDENT manifest version is semver" \
    || bad "$IDENT manifest version not X.Y.Z"
  [ "$CID_OK" = "True" ] && ok "$IDENT creatorId set" \
    || warn "$IDENT creatorId placeholder — pack lint will hard-fail"
done <<<"$DEV_ROOTS"

echo "=== S5: discovery & payload resolution probe ================"
REAL_CFG="$("$PY" -c "from ainara.framework.config import config; print(config.get_default_config_paths()[0])")"
TMP_CFG="$(mktemp /tmp/nexus_check_cfg_XXXX)"
TMP_ERR="$(mktemp /tmp/nexus_check_err_XXXX)"
cp "$REAL_CFG" "$TMP_CFG"
# A: minimal config carrying exactly the same dev_apps as the real one —
# proves the dev_apps plumbing independent of any other config state.
"$PY" - "$TMP_CFG" <<'PYEOF'
import sys
from ainara.framework.config import config
da = config._get_unscoped("nexus.dev_apps", {}) or {}
with open(sys.argv[1], "a") as f:
    f.write("\nnexus:\n  dev_apps:\n")
    for k, v in da.items():
        f.write(f"    {k}: {v}\n")
PYEOF
trap 'rm -f "$TMP_CFG" "$TMP_ERR"' EXIT

discover_ids () {
  AINARA_CONFIG="$1" "$PY" - <<'PYEOF'
from ainara.framework.capabilities.nexus import NexusSkillProvider
from ainara.framework.config import config
p = NexusSkillProvider(nexus_path="", config=config, mcp_client_manager=None)
print("IDS:" + ",".join(sorted(p.discover())))
PYEOF
}
IDS_A="$(discover_ids "$TMP_CFG" 2>"$TMP_ERR")"
B_IDS="$(discover_ids "$REAL_CFG" 2>"$TMP_ERR")"   # two-step: nested ${()#} is illegal bash
IDS_A="${IDS_A#IDS:}"; B_IDS="${B_IDS#IDS:}"
if [ -n "$IDS_A" ] && [ "$IDS_A" = "$B_IDS" ]; then
  N=$(awk -F, '{print NF}' <<<"$IDS_A")
  ok "discovery: minimal dev_apps config == real config ($N skill ids)"
elif [ -z "$IDS_A" ] && [ -z "$B_IDS" ]; then
  warn "discovery: no skills found (no dev apps or no gated skills installed)"
else
  bad "discovery mismatch — minimal:'$IDS_A' real:'$B_IDS' — stderr tail:"
  tail -n 6 "$TMP_ERR" | sed 's/^/        /'
fi

# Payload-resolution probe for each dev root (framework contract: the
# resolver must yield the payload, never the repo root).
PAY_FAIL=0
while IFS= read -r ROOT; do
  [ -z "$ROOT" ] || [ ! -f "$ROOT/payload/nexus.json" ] && continue
  PROBE_OUT="$(PROBE_ROOT="$ROOT" "$PY" - 2>"$TMP_ERR" <<'PYEOF'
import os, sys, traceback
try:
    from ainara.framework.nexus_apps import resolve_app_payload
    app = resolve_app_payload(os.environ["PROBE_ROOT"])
except BaseException:
    traceback.print_exc()
    sys.exit(3)
payload = str(app[2]) if app else ""
print(payload or "NONE")
PYEOF
)"
  RA_RES="$(sed -n 1p <<<"$PROBE_OUT")"
  if [ -n "$RA_RES" ] && [ "$RA_RES" != "NONE" ] && [ -f "$RA_RES/nexus.json" ]; then
    ok "resolve($ROOT) = payload, never repo root"
  else
    PAY_FAIL=1
    bad "resolve('$ROOT') failed — payload not resolved; stderr tail:"
    tail -n 8 "$TMP_ERR" | sed 's/^/        /'
  fi
done <<<"$DEV_ROOTS"
[ "$PAY_FAIL" = "0" ] && [ -n "$(head -1 <<<"$DEV_ROOTS")" ] && ok "payload resolution green for all dev apps"

echo
echo "RESULT: $PASS pass / $FAIL fail / $WARN warn"
if [ "$FAIL" = "0" ]; then echo "STATE: GREEN"
else echo "STATE: RED — fix FAILs before resuming"; fi
