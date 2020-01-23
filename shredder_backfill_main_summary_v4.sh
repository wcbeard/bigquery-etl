#!/bin/bash -x

exec script/generate_incremental_table \
  main_summary_v4.sql \
  --destination_table=moz-fx-data-shared-prod:telemetry_derived.main_summary_v4 \
  --start=2019-10-24 \
  --end=2016-03-11 \
  --noreplace \
  --project_id=moz-fx-data-bq-batch-prod \
  --max_procs=2 \
  "$@"
