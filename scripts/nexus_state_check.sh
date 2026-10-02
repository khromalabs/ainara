#!/usr/bin/env bash
# =============================================================================
# nexus_state_check.sh — single source of truth for Nexus-task state (Stage 3)
#
# Consolidates every harness/verification used during the submodule + build
# session. Read-only against both repos; edits only a TEMP config copy.
# Pins ./venv/bin/python (gotcha §4-11: bare python fakes import failures).
# Side effects by design (§4-12): check A instantiates the 8 ataria skills
# (keyring reads, API-key loads, cache sweeps). No writes to either repo.
#
# Usage: ./scripts/nexus_state_check.sh   (from anywhere)
# Update EXPECT_*/ATARIA_DEV below when the ledger advances.
# =============================================================================
set -u
export PYTHONDONTWRITEBYTECODE=1

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/venv/bin/python"
[ -x "$PY" ] || { echo "FATAL: venv python not found at $PY"; exit 2; }

EXPECT_AINARA_BRANCH=dev012
EXPECT_AINARA_HEAD=0ef54636
EXPECT_ATARIA_HEAD=ca84c74
EXPECT_GITLINK=d6569c5
# Single-copy layout: the dev checkout was deleted; the submodule mount is
# now BOTH the pinned reference and the dev_apps target (probed 8/8, first-wins).
ATARIA_DEV="$REPO/ainara/nexus/khromalabs/ataria"   # = submodule mount = nexus.dev_apps value

BASELINE_IDS=(
  khromalabs_ataria_charts_candles
  khromalabs_ataria_crypto_analysis
  khromalabs_ataria_crypto_screener
  khromalabs_ataria_crypto_solanasecurity
  khromalabs_ataria_crypto_tradingaccount
  khromalabs_ataria_crypto_tradingorders
  khromalabs_ataria_crypto_tradingworkbook
  khromalabs_ataria_dashboards_controlpanel
)
BASELINE_CSV="$(printf '%s,' "${BASELINE_IDS[@]}")"; BASELINE_CSV="${BASELINE_CSV%,}"

PASS=0; FAIL=0; WARN=0
ok()   { PASS=$((PASS+1)); echo "PASS  $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL  $*"; }
warn() { WARN=$((WARN+1)); echo "WARN  $*"; }

echo "=== S1: repos & submodule ==================================="
[ -f .gitmodules ] && ok ".gitmodules present" || bad ".gitmodules missing"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"; HEAD="$(git rev-parse --short HEAD)"
[ "$BRANCH" = "$EXPECT_AINARA_BRANCH" ] && ok "ainara branch $BRANCH" \
  || bad "ainara branch '$BRANCH' (expected $EXPECT_AINARA_BRANCH)"
if git merge-base --is-ancestor "$EXPECT_AINARA_HEAD" HEAD 2>/dev/null; then
  ok "ainara HEAD $HEAD contains ledger anchor $EXPECT_AINARA_HEAD"
else
  bad "ainara HEAD $HEAD does NOT contain anchor $EXPECT_AINARA_HEAD (rebase/reset?)"
fi

if [ -e "$ATARIA_DEV/.git" ]; then   # gitfile, not dir (absorbed gitdir)
  AH="$(git -C "$ATARIA_DEV" rev-parse HEAD)"
  if git -C "$ATARIA_DEV" merge-base --is-ancestor "$EXPECT_ATARIA_HEAD" "$AH" 2>/dev/null; then
    ok "ataria HEAD ${AH:0:8} contains ledger anchor $EXPECT_ATARIA_HEAD"
  else
    bad "ataria HEAD ${AH:0:8} does NOT contain anchor $EXPECT_ATARIA_HEAD"
  fi
  AS="$(git -C "$ATARIA_DEV" status --short)"
  [ -z "$AS" ] && ok "ataria working tree clean" || warn "ataria dirty: $AS"
else
  warn "ataria dev checkout not at $ATARIA_DEV (update ATARIA_DEV)"
fi

SUB="$(git submodule status ainara/nexus/khromalabs/ataria 2>/dev/null || true)"
case "$SUB" in
  " $EXPECT_GITLINK"*) ok "submodule in-sync @ $(echo "$SUB" | cut -c2-9)" ;;
  "+"*) warn "submodule HEAD differs from pin: $SUB (git add the gitlink)" ;;
  "-"*) bad "submodule not initialized (git submodule update --init)" ;;
  *)    bad "submodule status unexpected: '$SUB'" ;;
esac
GL="$(git ls-files -s ainara/nexus/khromalabs/ataria | awk '{print $2}')"
case "$GL" in
  "$EXPECT_GITLINK"*) ok "gitlink pinned ${GL:0:8}" ;;
  "")                 bad "gitlink missing from index (path not tracked?)" ;;
  *)                  bad "gitlink ${GL:0:8} (expected prefix $EXPECT_GITLINK)" ;;
esac
{ [ -f ainara/nexus/khromalabs/ataria/.git ] && \
  [ -d .git/modules/ainara/nexus/khromalabs/ataria ]; } \
  && ok "gitdir absorbed" || warn "gitdir not absorbed (git submodule absorbgitdirs)"
git check-ignore -q --no-index ainara/nexus/khromalabs/ataria \
  && ok "gitignore rule active (--no-index probe)" \
  || bad ".gitignore ainara/nexus/* rule missing (gotcha §4-4/13)"

echo "=== S2: interpreter & tools ================================="
echo "      venv: $("$PY" --version 2>&1)"
"$PY" -c "import aiohttp" 2>/dev/null && ok "bundle deps importable (aiohttp)" \
  || bad "aiohttp missing in venv — discovery A will fail"
if command -v minisign >/dev/null 2>&1 && minisign -h 2>&1 | head -1 | grep -q "^Usage:"; then
  ok "minisign real binary"
else
  warn "minisign unusable (D-B regression?)"
fi

echo "=== S3: discovery A/B (A: keyring/API-key side effects) ====="
REAL_CFG="$("$PY" -c "from ainara.framework.config import config; print(config.get_default_config_paths()[0])")"
TMP_CFG="$(mktemp /tmp/nexus_check_cfg_XXXX)"
TMP_ERR="$(mktemp /tmp/nexus_check_err_XXXX)"
cp "$REAL_CFG" "$TMP_CFG"
printf '\nnexus:\n  dev_apps:\n    ataria: %s\n' "$ATARIA_DEV" >> "$TMP_CFG"
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
if [ "${IDS_A#IDS:}" = "$BASELINE_CSV" ]; then
  ok "A (dev_apps set): 8/8 exact baseline"
else
  bad "A mismatch — got '${IDS_A#IDS:}' — stderr tail:"
  tail -n 6 "$TMP_ERR" | sed 's/^/        /'
fi
B_IDS="$(discover_ids "$REAL_CFG" 2>"$TMP_ERR")"   # two-step: nested ${()#} is illegal bash
B_IDS="${B_IDS#IDS:}"
[ -z "$B_IDS" ] && ok "B (real config): 0 skills — footgun state as documented" \
  || warn "B returned '$B_IDS' (real config has dev_apps/other roots now)"

echo "=== S4: framework payload resolution ========================"
# Root-driven probe of the Stage 3a contract: the resolver must yield the
# payload, never the repo root. (Replaces the retired _obfuscate probe —
# resolution is a framework feature; obfuscation now lives in pack.py.)
PROBE_OUT="$(PROBE_ROOT="$ATARIA_DEV" "$PY" - 2>"$TMP_ERR" <<'PYEOF'
import os, sys, traceback
try:
    from ainara.framework.nexus_apps import resolve_app_payload
    app = resolve_app_payload(os.environ["PROBE_ROOT"])
except BaseException:
    traceback.print_exc()
    sys.exit(3)
payload = str(app[2]) if app else ""
print(payload or "NONE")
arts = ["nexus.json", "providers_registry.json", "skills_metadata.json", "site"]
print("MISS:" + ",".join(
    n for n in arts if not payload or not os.path.exists(os.path.join(payload, n))))
PYEOF
)"
RA_RES="$(sed -n 1p <<<"$PROBE_OUT")"
MA="$(sed -n 's/^MISS://p' <<<"$PROBE_OUT")"
case "$RA_RES" in
  ""|NONE)
    bad "resolve: probe failed or returned NONE — payload not resolved; stderr tail:"
    tail -n 8 "$TMP_ERR" | sed 's/^/        /' ;;
  *)
    if [ -d "$RA_RES/charts" ] && [ -d "$RA_RES/plans" ] && [ -f "$RA_RES/nexus.json" ]; then
      ok "resolve(dev_apps root) = payload, never repo root"
    else
      bad "resolve: '$RA_RES' fails payload markers (charts+plans+nexus.json present)"
    fi
    if [ -z "$MA" ]; then
      ok "dev payload artifacts complete"
    else
      warn "dev payload missing artifacts: $MA (regen before pack)"
    fi ;;
esac

echo "=== S5: bundle dist artifact (informational) ================"
ZIP="$(ls "$ATARIA_DEV"/dist/ataria-*.zip 2>/dev/null | head -1)"
if [ -n "$ZIP" ] && [ -f "$ZIP.minisig" ] && [ -f "$ZIP.sha256" ]; then
  ok "dist artifact present: $(basename "$ZIP") (+ sig + sha256)"
  warn "artifact predates the pack obfuscation stage — verify before shipping"
elif [ -n "$ZIP" ]; then
  warn "dist artifact present but signature files missing: $(basename "$ZIP")"
else
  warn "no dist artifact (run the pack pipeline to produce one)"
fi

echo "=== S6: Stage 3 pack prerequisites =========================="
CID="$("$PY" - "$ATARIA_DEV/payload/nexus.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))          # tolerate manifest nested or flat
print((d.get("manifest") or d).get("creatorId", ""))
PYEOF
)"
[ -n "$CID" ] && [ "$CID" != "YOUR_SOLANA_PUBLIC_KEY_HERE" ] \
  && ok "creatorId set" || warn "creatorId placeholder — pack lint will hard-fail (§6)"
PLANS="$(ls "$ATARIA_DEV"/payload/plans/*.yaml 2>/dev/null | wc -l)"
[ "$PLANS" = "2" ] && ok "payload/plans/*.yaml = 2 (store/ at repo root, excluded structurally)" \
  || warn "payload/plans top-level count = $PLANS (expected 2)"

echo
echo "RESULT: $PASS pass / $FAIL fail / $WARN warn"
if [ "$FAIL" = "0" ]; then echo "STATE: GREEN — resume at note_stage3.md §8"
else echo "STATE: RED — fix FAILs before resuming"; fi
