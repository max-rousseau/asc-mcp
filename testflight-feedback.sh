#!/usr/bin/env bash
# Fetch TestFlight beta feedback from the App Store Connect API.
#
# App-agnostic: everything is parameterized by the repo-root .env. Drop this
# file into any iOS project's scripts/ directory (or run it from anywhere with
# ENV_FILE pointing at the right .env).
#
# Usage:
#   testflight-feedback.sh screenshots [N]   latest N screenshot feedback submissions (JSON)
#   testflight-feedback.sh crashes     [N]   latest N crash submissions (JSON)
#   testflight-feedback.sh crashlog    <id>  crash log for one submission (logText inline)
#
# Config comes from the repo-root .env:
#   ASC_KEY_ID           App Store Connect API key id
#   ASC_ISSUER_ID        API issuer id (Users and Access -> Integrations)
#   ASC_PRIVATE_KEY_B64  base64 of the AuthKey_XXXX.p8 (base64 -i key.p8 | tr -d '\n')
#   ASC_APP_ID           the app's numeric Apple ID (App Information -> General)
#
# Output is raw API JSON on stdout — pipe to jq. Errors go to stderr, non-zero exit.
# Must stay compatible with stock macOS bash 3.2 (no assoc arrays, careful set -u).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
API_BASE="https://api.appstoreconnect.apple.com"
DEFAULT_LIMIT=50

usage() {
  cat <<'EOF'
Usage: testflight-feedback.sh <command>

Commands:
  screenshots [N]   list latest N screenshot feedback submissions as JSON (default 50)
  crashes     [N]   list latest N crash submissions as JSON (default 50)
  crashlog    <id>  print crash log JSON for one crash submission (.data.attributes.logText)
  --help            show this help

Config: .env (repo root, or $ENV_FILE) must define ASC_KEY_ID, ASC_ISSUER_ID,
ASC_PRIVATE_KEY_B64, ASC_APP_ID. Output is raw App Store Connect API JSON — pipe to jq.
EOF
}

fatal() { echo "ERROR: $*" >&2; exit 1; }

check_deps() {
  local dep
  for dep in openssl curl jq base64; do
    command -v "$dep" >/dev/null 2>&1 || fatal "required dependency '$dep' not found in PATH"
  done
}

env_get() {
  # KEY=value lines only; comments/other lines ignored; last assignment wins.
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

load_config() {
  [ -f "$ENV_FILE" ] || fatal "$ENV_FILE not found. Copy .env.example to .env and fill in required values"
  local var val
  for var in ASC_KEY_ID ASC_ISSUER_ID ASC_PRIVATE_KEY_B64 ASC_APP_ID; do
    val="$(env_get "$var")"
    [ -n "$val" ] || fatal "$var is not set in $ENV_FILE. Copy .env.example to .env and fill in required values"
    eval "$var=\$val"
  done
  ASC_PRIVATE_KEY="$(printf '%s' "$ASC_PRIVATE_KEY_B64" | openssl base64 -d -A 2>/dev/null)" || \
    fatal "ASC_PRIVATE_KEY_B64 is not valid base64. Copy .env.example to .env and fill in required values"
  case "$ASC_PRIVATE_KEY" in
    *"-----BEGIN"*) ;;
    *) fatal "ASC_PRIVATE_KEY_B64 does not decode to a PEM private key. Copy .env.example to .env and fill in required values" ;;
  esac
}

b64url() { base64 | tr -d '\n=' | tr '+/' '-_'; }

hex_to_bin() {
  local hex="$1" i=0
  while [ "$i" -lt "${#hex}" ]; do
    printf "\\x${hex:$i:2}"
    i=$((i + 2))
  done
}

pad_to_32_bytes() {
  # DER integers carry a 0x00 sign byte when the high bit is set, and may be
  # shorter than 32 bytes; normalize to exactly 64 hex chars.
  local h="$1"
  while [ "${#h}" -gt 64 ] && [ "${h#00}" != "$h" ]; do h="${h#00}"; done
  [ "${#h}" -le 64 ] || fatal "ECDSA signature integer wider than 32 bytes"
  while [ "${#h}" -lt 64 ]; do h="00$h"; done
  printf '%s' "$h"
}

mint_jwt() {
  local now exp header payload signing_input ints r_hex s_hex sig
  now="$(date +%s)"
  exp=$((now + 1200)) # ASC max token lifetime is 20 minutes
  header="$(jq -nc --arg kid "$ASC_KEY_ID" '{alg:"ES256",kid:$kid,typ:"JWT"}')"
  payload="$(jq -nc --arg iss "$ASC_ISSUER_ID" --argjson iat "$now" --argjson exp "$exp" \
    '{iss:$iss,iat:$iat,exp:$exp,aud:"appstoreconnect-v1"}')"
  signing_input="$(printf '%s' "$header" | b64url).$(printf '%s' "$payload" | b64url)"
  # openssl emits a DER-encoded ECDSA signature, but JOSE ES256 wants raw
  # r||s (2x32 bytes): pull the two INTEGERs out of the DER and repack.
  ints="$(printf '%s' "$signing_input" \
    | openssl dgst -sha256 -sign <(printf '%s' "$ASC_PRIVATE_KEY") -binary \
    | openssl asn1parse -inform DER \
    | awk -F: '/INTEGER/{print $NF}')"
  r_hex="$(printf '%s\n' "$ints" | sed -n 1p)"
  s_hex="$(printf '%s\n' "$ints" | sed -n 2p)"
  [ -n "$r_hex" ] && [ -n "$s_hex" ] || \
    fatal "failed to sign JWT (is ASC_PRIVATE_KEY_B64 a valid App Store Connect .p8 key?)"
  sig="$(hex_to_bin "$(pad_to_32_bytes "$r_hex")$(pad_to_32_bytes "$s_hex")" | b64url)"
  printf '%s.%s' "$signing_input" "$sig"
}

api_get() {
  local url="$1" body rc
  # -g: fields[...] brackets must not trigger curl's URL glob parser
  if body="$(curl -sS -g --fail-with-body -H "Authorization: Bearer $JWT" "$url")"; then
    printf '%s\n' "$body"
  else
    rc=$?
    echo "ERROR: request failed: $url" >&2
    printf '%s\n' "$body" >&2
    exit "$rc"
  fi
}

validate_limit() {
  case "$1" in
    *[!0-9]*|'') fatal "limit must be a positive integer, got '$1'" ;;
  esac
  [ "$1" -ge 1 ] || fatal "limit must be >= 1, got '$1'"
}

main() {
  local cmd="${1:-}" limit id
  case "$cmd" in
    -h|--help|help) usage; exit 0 ;;
    screenshots|crashes|crashlog) ;;
    '') usage >&2; exit 1 ;;
    *) echo "ERROR: unknown command '$cmd'" >&2; usage >&2; exit 1 ;;
  esac

  check_deps
  load_config
  JWT="$(mint_jwt)"

  case "$cmd" in
    screenshots)
      limit="${2:-$DEFAULT_LIMIT}"
      validate_limit "$limit"
      api_get "$API_BASE/v1/apps/$ASC_APP_ID/betaFeedbackScreenshotSubmissions?sort=-createdDate&limit=$limit&include=build&fields[betaFeedbackScreenshotSubmissions]=createdDate,comment,email,deviceModel,osVersion,appUptimeInMilliseconds,batteryPercentage,screenshots,build"
      ;;
    crashes)
      limit="${2:-$DEFAULT_LIMIT}"
      validate_limit "$limit"
      api_get "$API_BASE/v1/apps/$ASC_APP_ID/betaFeedbackCrashSubmissions?sort=-createdDate&limit=$limit&include=build"
      ;;
    crashlog)
      id="${2:-}"
      [ -n "$id" ] || fatal "crashlog requires a submission id"
      case "$id" in
        *[!A-Za-z0-9-]*) fatal "submission id may only contain letters, digits, and dashes" ;;
      esac
      api_get "$API_BASE/v1/betaFeedbackCrashSubmissions/$id/crashLog"
      ;;
  esac
}

# Allow sourcing for tests without executing.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
