#!/usr/bin/env python

from argparse import ArgumentParser
from datetime import datetime, timedelta
import warnings

from google.cloud import bigquery

parser = ArgumentParser()
parser.add_argument(
    "-s",
    "--slots",
    default=1000,
    type=int,
    help="Number of reserved slots currently available",
)
parser.add_argument(
    "-S",
    "--state-table",
    "--state_table",
    default="relud-17123.test.shredder_state",
)
parser.add_argument(
    "-d",
    "--days",
    default=28,
    type=int,
    help="Number of days shredder has to run",
)


args = parser.parse_args()
flat_rate_slots = args.slots
state_table = args.state_table
runs_per_month = 365 / 12 / args.days

# calculate the minimum bytes_per_second a job needs to process to reduce cost
# by using flat rate pricing instead of on demand pricing at 100% utilization
seconds_per_month = 60 * 60 * 24 * 7 * 52 / 12
flat_rate_dollars_per_month_per_slot = 8500 / 500
on_demand_bytes_per_dollar = 2 ** 40 / 5
min_flat_rate_bytes_per_second_per_slot = on_demand_bytes_per_dollar * flat_rate_dollars_per_month_per_slot / seconds_per_month

# translate min_flat_rate_bytes_per_second_per_slot to slot_millis_per_byte
slot_millis_per_second_per_slot = 1000
min_flat_rate_slot_millis_per_byte = slot_millis_per_second_per_slot / min_flat_rate_bytes_per_second_per_slot

# determine how fast shredder is running
warnings.filterwarnings("ignore", module="google.auth._default")
client = bigquery.Client()
jobs = [
    job
    for row in client.query(f"SELECT DISTINCT job FROM `{state_table}`")
    for project, location, job_id in [row['job'].split(".")]
    for job in [client.get_job(job_id, project, location)]
    if job.state == "DONE" and not job.errors
]
if False:
    # faster method of collecting jobs for a single project using min_creation_time
    jobs = [
        job
        for job in client.list_jobs('moz-fx-data-bq-batch-prod', min_creation_time=datetime(2020, 1, 22, 5), state_filter="done")
        if job.query.strip().startswith("DELETE") and not job.errors
    ]
total_bytes_processed, slot_millis = map(sum, zip(*((job.total_bytes_processed, job.slot_millis) for job in jobs)))
bytes_per_second = total_bytes_processed / (slot_millis / slot_millis_per_second_per_slot / flat_rate_slots)
print(f"shredder is processing {bytes_per_second*60/2**30:.3f} GiB/min using {flat_rate_slots} slots")

# report cost vs on-demand
slot_millis_per_byte = slot_millis / total_bytes_processed
efficiency = slot_millis_per_byte / min_flat_rate_slot_millis_per_byte
if efficiency <= 1:
    print(f"processing speed is {100-efficiency*100:.2f}% cheaper at 100% utilization than on-demand")
else:
    print(f"processing speed is {100*efficiency-100:.2f}% more expensive at 100% utilization than on-demand")

# report how long it would take to process main summary in 14 days
table = client.get_table("moz-fx-data-shared-prod.telemetry_derived.main_summary_v4")
table2 = client.get_table("moz-fx-data-derived-datasets.telemetry_derived.main_summary_v4")
print(f"{timedelta(seconds=(table.num_bytes+table2.num_bytes)/bytes_per_second)} to process {table.table_id} with {flat_rate_slots} slots")

# report how many slots it would take to process everything except main_v4
from bigquery_etl.shredder.config import DELETE_TARGETS
tables = [client.get_table(t.sql_table_id) for t in DELETE_TARGETS] + [table2]
num_bytes = sum(t.num_bytes for t in tables if t.table_id != "main_v4")
seconds_per_run = seconds_per_month / runs_per_month
slots_needed = num_bytes / seconds_per_run / bytes_per_second * flat_rate_slots
print(f"{slots_needed:.0f} slots needed to process {num_bytes/2**50:.3f} PiB every {args.days} day(s) for everything except main_v4")

# report how much it would cost to process main_v4 on-demand
num_bytes = sum(t.num_bytes for t in tables if t.table_id == "main_v4")
print(f"${num_bytes*runs_per_month/on_demand_bytes_per_dollar:,.2f}/mo to process {num_bytes/2**50:.3f} PiB every {args.days} day(s) on-demand for main_v4")
