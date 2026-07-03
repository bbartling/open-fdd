#!/usr/bin/env bash
# Back-compat wrapper — prefer openfdd_rigorous_bench_report.sh
exec "$(dirname "$0")/openfdd_rigorous_bench_report.sh" "$@"
