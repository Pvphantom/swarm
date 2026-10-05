#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PORT="${1:-8010}"
exec env PYTHONPATH=. uvicorn backend.main:app --host 127.0.0.1 --port "$PORT" --reload
