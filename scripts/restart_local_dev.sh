#!/usr/bin/env bash
# Kills any locally-running `moto.server`/`flask run`/consumer-poller from a
# previous session, then redoes the full local bootstrap from scratch: a fresh
# moto server (so any inconsistent/partial state from a previous botched run
# is gone too), the table/GSI's/event bus/queues/Cognito pool + its two demo
# users (admin@demo.nl / klant@demo.nl, see README's "Demo-inloggegevens"),
# the product seed, a background poller standing in for the SQS-Lambda
# triggers real AWS has but moto doesn't (see README's
# "Orderstatus-levenscyclus" -- without this, every order stays stuck on "In
# afwachting van betaling" forever), and finally `flask run` itself -- all in
# the foreground of this one script, so Ctrl-C stops Flask and the trap below
# stops moto and the poller with it. See README's "Lokaal draaien" for what
# each step does individually.
#
# Usage: ./scripts/restart_local_dev.sh
# Override the ports with: MOTO_PORT=5002 FLASK_PORT=5051 ./scripts/restart_local_dev.sh
#
# FLASK_PORT defaults to 5050, not Flask's own default of 5000: on macOS
# Monterey+, AirPlay Receiver listens on port 5000 by default and answers
# anything else trying to bind/use it with its own "Access to 127.0.0.1 was
# denied -- HTTP ERROR 403" page, which looks exactly like a real app error
# but has nothing to do with this app. Disabling AirPlay Receiver (System
# Settings -> General -> AirDrop & Handoff) also fixes it, but not needing
# that toggle at all is more robust.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PORT="${MOTO_PORT:-5001}"
FLASK_PORT="${FLASK_PORT:-5050}"

echo "==> Stopping any existing local moto-server / flask run / consumer-poller..."
pkill -f "moto\.server -p $PORT" 2>/dev/null && sleep 1 || true
pkill -f "flask run" 2>/dev/null && sleep 1 || true
pkill -f "scripts.run_local_consumers" 2>/dev/null && sleep 1 || true

export SECRET_KEY="${SECRET_KEY:-dev-secret-key}"
export FLASK_APP="app.main:app"
export FLASK_DEBUG=1
export TABLE_NAME="${TABLE_NAME:-WebshopTableLocal}"
export EVENT_BUS_NAME="${EVENT_BUS_NAME:-webshop-event-bus-local}"

CONSUMER_PID=""

echo "==> Starting a fresh moto server on port $PORT..."
uv run python -m moto.server -p "$PORT" &
MOTO_PID=$!
trap 'echo "==> Stopping moto server + consumer-poller..."; kill "$MOTO_PID" 2>/dev/null || true; [ -n "$CONSUMER_PID" ] && kill "$CONSUMER_PID" 2>/dev/null || true' EXIT

# Give moto a moment to bind before the bootstrap step below hits it.
sleep 1.5

export DYNAMODB_ENDPOINT_URL="http://localhost:$PORT"
export EVENTS_ENDPOINT_URL="http://localhost:$PORT"
export SQS_ENDPOINT_URL="http://localhost:$PORT"
export COGNITO_IDP_ENDPOINT_URL="http://localhost:$PORT"

echo "==> Bootstrapping table + GSI's + event bus/queues/rules + Cognito pool + demo users..."
eval "$(uv run python -m scripts.bootstrap_local_infra)"

echo "==> Seeding products..."
uv run python -m scripts.seed_products

echo "==> Starting the local consumer-poller (stands in for real AWS's SQS-Lambda triggers)..."
uv run python -m scripts.run_local_consumers &
CONSUMER_PID=$!

echo "==> Starting flask run on http://127.0.0.1:$FLASK_PORT (Ctrl-C to stop everything)..."
uv run flask run --port "$FLASK_PORT"
