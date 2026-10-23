#!/usr/bin/env bash
# Run the API and Stripe's event forwarder together, for local payment testing.
#
#   ./dev_payments.sh                    # API + `stripe listen`; one Ctrl+C stops both
#   ./dev_payments.sh --api-only         # the API alone, no forwarding
#   ./dev_payments.sh --check            # report what it would do; prints no secrets
#   ./dev_payments.sh --env-file .env.stripe
#
# Stripe keys are read from backend/.env, then backend/.env.local (local wins).
# A variable already in the environment wins over both, so
# `STRIPE_SECRET_KEY=sk_test_... ./dev_payments.sh` still does what you expect.
# Neither file is committed; see .gitignore.
#
# Why the listener starts first: `stripe listen` prints a fresh signing secret
# (`whsec_...`) when it starts, and the API must verify against *that* secret.
# A Dashboard endpoint's secret belongs to that endpoint and cannot verify
# events the CLI signs. So the secret is read from the listener's own output and
# handed to the API - nothing to copy, nothing to restart.
#
# A live key (sk_live_..., rk_live_...) is refused unless --allow-live is
# passed, because this starts an API that charges real cards.
#
# Flags: --api-only, --check, --env-file PATH, --allow-live, -h/--help.
# Exit:  0 clean stop, 1 the API did not come up, 2 bad usage or a live key
#        without --allow-live, 130 Ctrl+C.
set -euo pipefail

CALLER_PWD="$PWD"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PORT_SHIFTED=0

LOG_DIR="${DEV_PAYMENTS_LOG_DIR:-logs/dev_payments}"
API_LOG="$LOG_DIR/api.log"
STRIPE_LOG="$LOG_DIR/stripe.log"

API_PID=""
STRIPE_PID=""
API_TAIL_PID=""
STRIPE_TAIL_PID=""
STOPPING=0

API_ONLY=0
CHECK_ONLY=0
ALLOW_LIVE=0
ENV_FILE=""
ENV_SOURCE=""

usage() {
  cat <<'USAGE'
Start the API and the Stripe CLI listener together.

Usage: ./dev_payments.sh [--api-only] [--check] [--env-file PATH] [--allow-live]

  --api-only        Do not start `stripe listen`; run only the API.
  --check           Print what this would do and exit. Never starts a process
                    and never prints a secret.
  --env-file PATH   Read keys from PATH instead of backend/.env and
                    backend/.env.local. Relative paths are relative to where
                    you ran the script.
  --allow-live      Permit a live Stripe key (sk_live_... / rk_live_...).
                    Without this a live key is refused, because this starts an
                    API that charges real cards.
  -h, --help        This text.

Environment:
  HOST=127.0.0.1      HOST and PORT are what `run.sh` binds. If PORT is already
  PORT=8000           taken, the next free port is used (and the listener is
                      pointed at it) instead of failing.
  STRIPE_SECRET_KEY=sk_test_...        absent means checkout answers 503.
  STRIPE_WEBHOOK_SECRET=whsec_...      only used with --api-only; otherwise the
                                       listener's own secret wins for this run.
  STRIPE_FORWARD_TO=...                override the local webhook URL.

Logs are written to backend/logs/dev_payments/ (gitignored).
USAGE
}

die() {
  echo "error: $*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --api-only)   API_ONLY=1 ;;
    --check)      CHECK_ONLY=1 ;;
    --allow-live) ALLOW_LIVE=1 ;;
    -h|--help)    usage; exit 0 ;;
    --env-file)   [ "$#" -ge 2 ] || { usage >&2; echo "error: --env-file needs a path" >&2; exit 2; }
                  ENV_FILE="$2"; shift ;;
    --env-file=*) ENV_FILE="${1#*=}" ;;
    *)            usage >&2; echo "error: unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Read `KEY=value` lines without `source`: a value may contain spaces, and the
# file may hold a `#` that is part of the key rather than a comment. Files never
# overwrite a variable that is already set.
load_env_file() {
  local file="$1" line key value
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ''|'#'*) continue ;;
      'export '*) line="${line#export }" ;;
    esac
    case "$line" in
      *=*) ;;
      *) continue ;;
    esac
    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    case "$key" in
      ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;;
    esac
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    if ! declare -p "$key" >/dev/null 2>&1; then
      export "$key=$value"
    fi
  done < "$file"
}

HAD_STRIPE_KEY=0
if [ -n "${STRIPE_SECRET_KEY:-}" ]; then HAD_STRIPE_KEY=1; fi
HAD_WEBHOOK_SECRET=0
if [ -n "${STRIPE_WEBHOOK_SECRET:-}" ]; then HAD_WEBHOOK_SECRET=1; fi

if [ -n "$ENV_FILE" ]; then
  case "$ENV_FILE" in
    /*|[A-Za-z]:[\\/]*) RESOLVED_ENV="$ENV_FILE" ;;
    *)                  RESOLVED_ENV="$CALLER_PWD/$ENV_FILE" ;;
  esac
  [ -f "$RESOLVED_ENV" ] || die "no such env file: $ENV_FILE"
  load_env_file "$RESOLVED_ENV"
  ENV_SOURCE="$ENV_FILE"
else
  load_env_file ".env"
  load_env_file ".env.local"
  ENV_SOURCE="backend/.env, backend/.env.local (whichever exist)"
fi

# A live key is the one thing this script must not start by accident: the API
# would charge real cards. Test keys and "no key" are the ordinary local states,
# so this refusal is narrow.
LIVE_KEY=0
case "${STRIPE_SECRET_KEY:-}" in
  sk_live_*|rk_live_*) LIVE_KEY=1 ;;
esac

if [ "$LIVE_KEY" = "1" ] && [ "$ALLOW_LIVE" = "0" ] && [ "$CHECK_ONLY" = "0" ]; then
  cat >&2 <<'LIVE'
error: STRIPE_SECRET_KEY is a live key, and this API would charge real cards.
       Nothing was started.

       Use a test key (sk_test_...) for local work. To inspect the setup without
       charging anything, run with --check. If you really do mean to take real
       money on this machine, re-run with --allow-live.
LIVE
  exit 2
fi

# PORT is a shared name: an unrelated tool exporting PORT=0 must not silently
# move the API to a random port the Stripe listener is not pointing at.
case "$PORT" in
  ''|*[!0-9]*) die "PORT must be a number, got '$PORT'" ;;
  0) PORT=8000 ;;
esac
if [ "$PORT" -gt 65535 ]; then die "PORT must be 1-65535, got $PORT"; fi

PROBE_HOST="$HOST"
case "$PROBE_HOST" in
  0.0.0.0|::|"") PROBE_HOST="127.0.0.1" ;;
esac

# Whether something already holds the port. A refused connection means free;
# curl is the fallback for a bash built without /dev/tcp, where the connect test
# cannot tell the difference.
port_in_use() {
  local port="$1"
  if (exec 3<>"/dev/tcp/$PROBE_HOST/$port") >/dev/null 2>&1; then
    return 0
  fi
  command -v curl >/dev/null 2>&1 || return 1
  curl -fsS -o /dev/null --max-time 1 "http://$PROBE_HOST:$port/docs" 2>/dev/null
}

# A taken port is an ordinary state, not an error: a second checkout, a
# previous run, or this machine's own PORT=0. Move up until something accepts,
# and build the listener's target from the port that was actually chosen.
if port_in_use "$PORT"; then
  REQUESTED_PORT="$PORT"
  CANDIDATE=$((PORT + 1))
  LAST_PORT=$((PORT + 50))
  if [ "$LAST_PORT" -gt 65535 ]; then LAST_PORT=65535; fi
  while [ "$CANDIDATE" -le "$LAST_PORT" ] && port_in_use "$CANDIDATE"; do
    CANDIDATE=$((CANDIDATE + 1))
  done
  if [ "$CANDIDATE" -gt "$LAST_PORT" ]; then
    die "port $REQUESTED_PORT is in use and nothing between it and $LAST_PORT is free"
  fi
  PORT="$CANDIDATE"
  PORT_SHIFTED=1
  echo "Port $REQUESTED_PORT is in use; using $PORT instead."
fi

FORWARD_TO="${STRIPE_FORWARD_TO:-http://127.0.0.1:${PORT}/api/payments/webhook}"

# run.sh reads PORT from the environment, so the port chosen here has to be
# exported or a shifted port would be ignored and uvicorn would still try the
# taken one.
export PORT

if [ "$PORT_SHIFTED" = "1" ] && [ -n "${STRIPE_FORWARD_TO:-}" ]; then
  echo "note: STRIPE_FORWARD_TO is set, so the listener keeps that target."
  echo "      Make sure it points at port $PORT."
fi

STRIPE_BIN="$(command -v stripe || true)"

# --check starts nothing and prints no secret, so it works on a fresh clone and
# in CI. It still probes the chosen port, but only on loopback.
if [ "$CHECK_ONLY" = "1" ]; then
  if [ -n "${STRIPE_SECRET_KEY:-}" ]; then
    if [ "$HAD_STRIPE_KEY" = "1" ]; then
      KEY_STATE="set (environment)"
    else
      KEY_STATE="set (env file)"
    fi
  else
    KEY_STATE="missing - checkout will answer 503 and orders stay payable"
  fi

  if [ -n "${STRIPE_WEBHOOK_SECRET:-}" ]; then
    if [ "$HAD_WEBHOOK_SECRET" = "1" ]; then
      HOOK_STATE="set (environment)"
    else
      HOOK_STATE="set (env file)"
    fi
  else
    HOOK_STATE="empty - the listener's own secret will be used at startup"
  fi

  VENV_STATE="not found - run.sh will print how to create one"
  for candidate in \
    "../../.venv/Scripts/python.exe" \
    "../../.venv/bin/python" \
    ".venv/Scripts/python.exe" \
    ".venv/bin/python"
  do
    if [ -x "$candidate" ]; then
      VENV_STATE="$candidate"
      break
    fi
  done

  if [ "$API_ONLY" = "1" ]; then
    MODE="API only (--api-only)"
  elif [ -z "${STRIPE_SECRET_KEY:-}" ]; then
    MODE="API only (no STRIPE_SECRET_KEY)"
  elif [ -z "$STRIPE_BIN" ]; then
    MODE="API only (no Stripe CLI)"
  else
    MODE="API + listener"
  fi

  {
    echo "Stripe dev setup (nothing started)"
    echo "  env files:          $ENV_SOURCE"
    echo "  STRIPE_SECRET_KEY:  $KEY_STATE"
    echo "  webhook secret:     $HOOK_STATE"
    if [ "$LIVE_KEY" = "1" ]; then
      if [ "$ALLOW_LIVE" = "1" ]; then
        echo "  live key:           yes - real cards (allowed by --allow-live)"
      else
        echo "  live key:           yes - will refuse to start without --allow-live"
      fi
    else
      echo "  live key:           no"
    fi
    if [ -n "$STRIPE_BIN" ]; then
      echo "  Stripe CLI:         $STRIPE_BIN"
    else
      echo "  Stripe CLI:         not on PATH - the API still runs, but events"
      echo "                      cannot be forwarded (see docs.stripe.com/stripe-cli)"
    fi
    echo "  API:                http://$HOST:$PORT  (via ./run.sh)"
    echo "  interpreter:        $VENV_STATE"
    echo "  webhook target:     $FORWARD_TO"
    echo "  mode:               $MODE"
  }
  exit 0
fi

[ -f "./run.sh" ] || die "run.sh is missing next to this script"

# Kill only the PIDs this script started. On Windows those are native processes,
# which the shell's kill cannot always reach; taskkill is given the recorded PID
# (and its tree) rather than a name, so nothing else can match it.
stop_pid() {
  local pid="${1:-}" waited=0
  [ -n "$pid" ] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  if command -v taskkill >/dev/null 2>&1; then
    taskkill //F //T //PID "$pid" >/dev/null 2>&1 && return 0
  fi
  kill "$pid" 2>/dev/null || true
  while [ "$waited" -lt 20 ] && kill -0 "$pid" 2>/dev/null; do
    sleep 0.1
    waited=$((waited + 1))
  done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  return 0
}

cleanup() {
  if [ "$STOPPING" = "1" ]; then return 0; fi
  STOPPING=1
  trap - EXIT INT TERM
  stop_pid "$API_TAIL_PID"
  stop_pid "$STRIPE_TAIL_PID"
  stop_pid "$API_PID"
  stop_pid "$STRIPE_PID"
  wait 2>/dev/null || true
}

on_signal() {
  echo
  echo "Stopping the API and the Stripe listener..."
  exit 130
}

start_listener() {
  echo "Starting the Stripe listener -> $FORWARD_TO"
  : > "$STRIPE_LOG"
  "$STRIPE_BIN" listen --forward-to "$FORWARD_TO" > "$STRIPE_LOG" 2>&1 &
  STRIPE_PID=$!
  tail -n +1 -f "$STRIPE_LOG" &
  STRIPE_TAIL_PID=$!
}

# `stripe listen` announces the signing secret it will use within a second or
# two. Reading it back is what makes the webhook verifiable without a manual
# copy-and-restart.
listener_secret() {
  local waited=0 found=""
  while [ "$waited" -lt 150 ]; do
    kill -0 "$STRIPE_PID" 2>/dev/null || return 1
    found="$(sed -n 's/.*\(whsec_[A-Za-z0-9][A-Za-z0-9]*\).*/\1/p' "$STRIPE_LOG" 2>/dev/null | head -n 1)" || found=""
    if [ -n "$found" ]; then
      printf '%s' "$found"
      return 0
    fi
    sleep 0.1
    waited=$((waited + 1))
  done
  return 1
}

probe_api() {
  command -v curl >/dev/null 2>&1 || return 2
  curl -fsS -o /dev/null --max-time 2 "http://$PROBE_HOST:$PORT/docs" 2>/dev/null
}

start_api() {
  : > "$API_LOG"
  bash ./run.sh > "$API_LOG" 2>&1 &
  API_PID=$!
  tail -n +1 -f "$API_LOG" &
  API_TAIL_PID=$!
}

wait_for_api() {
  local waited=0 deadline=180
  while [ "$waited" -lt "$deadline" ]; do
    kill -0 "$API_PID" 2>/dev/null || return 1
    local probe=0
    probe_api || probe=$?
    if [ "$probe" = "0" ]; then
      return 0
    fi
    if [ "$probe" = "2" ]; then
      # curl is absent, so "not ready" cannot be measured; give uvicorn a few
      # seconds and trust the PID check above.
      sleep 4
      kill -0 "$API_PID" 2>/dev/null
      return $?
    fi
    sleep 0.25
    waited=$((waited + 1))
  done
  return 1
}

trap on_signal INT TERM
trap cleanup EXIT
mkdir -p "$LOG_DIR"

# The port was free when it was chosen. If something claimed it in the
# meantime, say so instead of burying uvicorn's error in a log; re-running picks
# the next free port.
if port_in_use "$PORT"; then
  die "port $PORT is in use; re-run and the next free port will be used"
fi

LISTENER=0
if [ "$API_ONLY" = "1" ]; then
  echo "API only: Stripe events will not be forwarded."
  echo
elif [ -z "${STRIPE_SECRET_KEY:-}" ]; then
  echo "STRIPE_SECRET_KEY is not set, so checkout answers 503 and the order stays"
  echo "payable later. Put a test-mode key in backend/.env (or pass --env-file)"
  echo "to take money. Starting the API alone."
  echo
elif [ -z "$STRIPE_BIN" ]; then
  echo "The Stripe CLI ('stripe') is not on PATH, so events cannot be forwarded."
  echo "Install it from https://docs.stripe.com/stripe-cli and re-run."
  echo "The success page's polling still confirms a payment on its own; only"
  echo "tab-closed payments need the webhook. Starting the API alone."
  echo
else
  LISTENER=1
fi

if [ "$LIVE_KEY" = "1" ]; then
  echo "LIVE MODE: this API charges real cards; test cards will be declined."
  if [ "$API_ONLY" = "0" ]; then
    echo "The Stripe listener forwards test-mode events. Live events need"
    echo "'stripe listen --live' or a Dashboard endpoint, neither of which this"
    echo "script configures."
  fi
  echo
fi

if [ "$LISTENER" = "1" ]; then
  ENV_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-}"
  start_listener

  if SECRET="$(listener_secret)"; then
    export STRIPE_WEBHOOK_SECRET="$SECRET"
    if [ -n "$ENV_WEBHOOK_SECRET" ] && [ "$ENV_WEBHOOK_SECRET" != "$SECRET" ]; then
      echo "Using the listener's signing secret for this run; the STRIPE_WEBHOOK_SECRET"
      echo "you have set belongs to a Dashboard endpoint and cannot verify CLI-signed"
      echo "events. Use --api-only to start with yours instead."
      echo
    fi
  else
    echo "Could not read the listener's signing secret." >&2
    if ! kill -0 "$STRIPE_PID" 2>/dev/null; then
      tail -n 8 "$STRIPE_LOG" >&2 || true
      echo "Run 'stripe login' once, then re-run this script." >&2
      stop_pid "$STRIPE_TAIL_PID"
      stop_pid "$STRIPE_PID"
      STRIPE_TAIL_PID=""
      STRIPE_PID=""
    fi
    if [ -z "${STRIPE_WEBHOOK_SECRET:-}" ]; then
      echo "Starting the API without it: the webhook route answers 503 until" >&2
      echo "STRIPE_WEBHOOK_SECRET is set. The success page still confirms payments." >&2
    fi
    echo
  fi
fi

start_api

if wait_for_api; then
  echo
  echo "API:       http://$HOST:$PORT   (docs at /docs)"
  if [ -n "$STRIPE_PID" ] && kill -0 "$STRIPE_PID" 2>/dev/null; then
    echo "Webhook:   forwarded to $FORWARD_TO"
  fi
  echo "Test card: 4242 4242 4242 4242, any future expiry, any CVC"
  echo "Logs:      $LOG_DIR/"
  echo "Ctrl+C stops everything this script started."
  echo
else
  echo "The API did not come up." >&2
  tail -n 25 "$API_LOG" >&2 || true
  exit 1
fi

set +e
wait "$API_PID"
API_STATUS=$?
set -e

if [ "$API_STATUS" -ne 0 ]; then
  echo "The API exited with status $API_STATUS. Last lines:" >&2
  tail -n 25 "$API_LOG" >&2 || true
fi
exit "$API_STATUS"
