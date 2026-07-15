#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  make test-mysql-down
}
trap cleanup EXIT

make test-mysql-up
make test-mysql
