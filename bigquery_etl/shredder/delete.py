"""Delete user data from long term storage."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from textwrap import dedent
import asyncio
import logging
import warnings

from google.cloud import bigquery

from ..util.bigquery_id import FULL_JOB_ID_RE, full_job_id, sql_table_id
from ..util.client_queue import ClientQueue
from ..util.table_filter import add_table_filter_arguments, get_table_filter
from .config import DELETE_TARGETS


parser = ArgumentParser(description=__doc__)
parser.add_argument(
    "-n",
    "--dry_run",
    "--dry-run",
    action="store_true",
    help="Do not make changes, only log actions that would be taken; "
    "use with --log-level=DEBUG to log query contents",
)
parser.add_argument(
    "-l",
    "--log-level",
    "--log_level",
    default=logging.getLevelName(logging.INFO),
    type=str.upper,
)
parser.add_argument(
    "-P",
    "--parallelism",
    default=4,
    type=int,
    help="Maximum number of queries to execute concurrently",
)
parser.add_argument(
    "-e",
    "--end-date",
    "--end_date",
    default=datetime.utcnow().date(),
    type=lambda x: datetime.strptime(x, "%Y-%m-%d").date(),
    help="last date of last date of pings to delete; One day after last date of "
    "deletion requests to process; defaults to today in UTC",
)
parser.add_argument(
    "-s",
    "--start-date",
    "--start_date",
    type=lambda x: datetime.strptime(x, "%Y-%m-%d").date(),
    help="first date of deletion requests to process; DOES NOT apply to ping date; "
    "defaults to 14 days before --end-date in UTC",
)
parser.add_argument(
    "-p",
    "--billing-projects",
    "--billing_projects",
    "--billing-project",
    "--billing_project",
    nargs="+",
    default=["moz-fx-data-bq-batch-prod"],
    help="One or more billing projects over which bigquery jobs should be distributed; "
    "if not specified use the bigquery-batch-prod project",
)
parser.add_argument(
    "--source-project",
    "--source_project",
    help="override the project used for deletion request tables",
)
parser.add_argument(
    "--target-project",
    "--target_project",
    help="override the project used for target tables",
)
parser.add_argument(
    "--max-single-dml-bytes",
    "--max_single_dml_bytes",
    default=10 * 2 ** 40,
    type=int,
    help="Maximum number of bytes in a table that should be processed using a single "
    "DML query; tables above this limit will be processed using per-partition "
    "queries; this option prevents queries against large tables from exceeding the "
    "6-hour time limit; defaults to 10 TiB",
)
parser.add_argument(
    "--priority",
    default=bigquery.QueryPriority.INTERACTIVE,
    type=str.upper,
    choices=[bigquery.QueryPriority.BATCH, bigquery.QueryPriority.INTERACTIVE],
    help="Priority for BigQuery query jobs; BATCH priority may significantly slow "
    "down queries if reserved slots are not enabled for the billing project; "
    "INTERACTIVE priority is limited to 100 concurrent queries per project",
)
parser.add_argument(
    "--state-table",
    "--state_table",
    metavar="TABLE",
    help="Table for recording state; Used to avoid repeating deletes if interrupted; "
    "Create it if it does not exist; By default state is not recorded",
)
add_table_filter_arguments(parser)


def record_state(client, task_id, job, dry_run, start_date, end_date, state_table):
    """Record the job for task_id in state_table."""
    if state_table is not None:
        job_id = "a job_id" if dry_run else full_job_id(job)
        insert_tense = "Would insert" if dry_run else "Inserting"
        logging.info(f"{insert_tense} {job_id} in {state_table} for task: {task_id}")
        if not dry_run:
            client.query(
                dedent(
                    f"""
                    INSERT INTO
                      `{state_table}`(
                        task_id,
                        job,
                        job_started,
                        start_date,
                        end_date
                      )
                    VALUES
                      (
                        "{task_id}",
                        "{job_id}",
                        TIMESTAMP "{job.started:%Y-%m-%d %H:%M:%S} UTC",
                        DATE "{start_date}",
                        DATE "{end_date}"
                      )
                    """
                ).strip()
            ).result()


def wait_for_job(client, states, task_id, dry_run, create_job, **state_kwargs):
    """Get a job from state or create a new job, and wait for the job to complete."""
    job = None
    if task_id in states:
        job = client.get_job(**FULL_JOB_ID_RE.fullmatch(states[task_id]).groupdict())
        if job.errors:
            logging.info(f"Previous attempt failed, retrying for {task_id}")
            job = None
        elif job.ended:
            logging.info(f"Previous attempt succeeded, reusing result for {task_id}")
        else:
            logging.info(f"Previous attempt still running for {task_id}")
    if job is None:
        job = create_job(client)
        record_state(
            client=client, task_id=task_id, dry_run=dry_run, job=job, **state_kwargs
        )
    if not dry_run and not job.ended:
        logging.info(f"Waiting on {full_job_id(job)} for {task_id}")
        job.result()
    return job


def get_task_id(target, partition_id):
    """Get unique task id for state tracking."""
    task_id = sql_table_id(target)
    if partition_id:
        task_id += f"${partition_id}"
    return task_id


async def delete_from_partition(
    executor,
    client_q,
    dry_run,
    partition_condition,
    partition_id,
    priority,
    source,
    source_condition,
    target,
    **wait_for_job_kwargs,
):
    """Process deletion requests for partitions of a target table."""
    # noqa: D202

    def create_job(client):
        query = dedent(
            f"""
            DELETE
              `{sql_table_id(target)}`
            WHERE
              {target.field} IN (
                SELECT DISTINCT
                  {source.field}
                FROM
                  `{sql_table_id(source)}`
                WHERE
                  {source_condition}
              )
              AND {partition_condition}
            """
        ).strip()
        run_tense = "Would run" if dry_run else "Running"
        logging.debug(f"{run_tense} query: {query}")
        return client.query(
            query, bigquery.QueryJobConfig(dry_run=dry_run, priority=priority)
        )

    job = await client_q.async_with_client(
        executor,
        partial(
            wait_for_job,
            create_job=create_job,
            dry_run=dry_run,
            task_id=get_task_id(target, partition_id),
            **wait_for_job_kwargs,
        ),
    )
    return job.total_bytes_processed


def get_partition_expr(table):
    """Get the SQL expression to use for a table's partitioning field."""
    for field in table.schema:
        if field.name != table.time_partitioning.field:
            continue
        if field.field_type == "TIMESTAMP":
            return f"DATE({field.name})"
        return field.name


def list_partitions(client, target):
    """List the partition ids and corresponding dates in a table."""
    return [
        (partition_id, datetime.strptime(partition_id, "%Y%m%d").date())
        for row in client.query(
            dedent(
                f"""
                SELECT
                  partition_id
                FROM
                  [{sql_table_id(target)}$__PARTITIONS_SUMMARY__]
                """
            ).strip(),
            bigquery.QueryJobConfig(use_legacy_sql=True),
        ).result()
        for partition_id in [row["partition_id"]]
    ]


async def delete_from_table(
    client_q, target, dry_run, end_date, max_single_dml_bytes, **kwargs
):
    """Process deletion requests for a target table."""
    client = client_q.default_client
    table = client.get_table(sql_table_id(target))
    partition_expr = get_partition_expr(table)
    bytes_deleted = 0
    bytes_processed = sum(
        await asyncio.gather(
            *[
                delete_from_partition(
                    client_q=client_q,
                    dry_run=dry_run,
                    partition_condition=(
                        f"{partition_expr} <= '{end_date}'"
                        if partition_date is None
                        else f"{partition_expr} = '{partition_date}'"
                    ),
                    partition_expr=partition_expr,
                    partition_id=partition_id,
                    target=target,
                    end_date=end_date,
                    **kwargs,
                )
                for partition_id, partition_date in (
                    list_partitions(client=client, target=target)
                    if table.num_bytes > max_single_dml_bytes
                    else [(None, None)]
                )
                if partition_date is None or partition_date < end_date
            ]
        )
    )
    if dry_run:
        logging.info(f"Would scan {bytes_processed} bytes from {target.table}")
    else:
        bytes_deleted = (
            table.num_bytes - client.get_table(sql_table_id(target)).num_bytes
        )
        logging.info(
            f"Scanned {bytes_processed} bytes and "
            f"deleted {bytes_deleted} from {target.table}"
        )
    return bytes_processed, bytes_deleted


async def main():
    """Process deletion requests."""
    args = parser.parse_args()
    if args.start_date is None:
        args.start_date = args.end_date - timedelta(days=14)
    logging.root.setLevel(args.log_level)
    source_condition = (
        f"DATE(submission_timestamp) >= '{args.start_date}' "
        f"AND DATE(submission_timestamp) < '{args.end_date}'"
    )
    table_filter = get_table_filter(args)
    # expire in 15 days because this script may take up to 14 days
    expiration_date = datetime.utcnow().date() + timedelta(days=15)
    expiration_timestamp = f"{expiration_date} 00:00:00 UTC"
    client_q = ClientQueue(args.billing_projects, args.parallelism)
    states = {}
    if args.state_table:
        client_q.default_client.query(
            dedent(
                f"""
                CREATE TABLE IF NOT EXISTS
                  `{args.state_table}`(
                    task_id STRING,
                    job_id STRING,
                    job_started TIMESTAMP,
                    start_date DATE,
                    end_date DATE
                  )
                """
            ).strip()
        )
        states = {
            row["task_id"]: row["job_id"]
            for row in client_q.default_client.query(
                dedent(
                    f"""
                    SELECT
                      task_id,
                      job_id,
                    FROM
                      `{args.state_table}`
                    WHERE
                      start_date = '{args.start_date}'
                      AND end_date = '{args.end_date}'
                    ORDER BY
                      job_started
                    """
                ).strip()
            ).result()
        }
    with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
        results = await asyncio.gather(
            *[
                delete_from_table(
                    client_q=client_q,
                    executor=executor,
                    target=replace(
                        target, project=args.target_project or target.project
                    ),
                    source=replace(
                        source, project=args.source_project or source.project
                    ),
                    source_condition=source_condition,
                    dry_run=args.dry_run,
                    priority=args.priority,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    max_single_dml_bytes=args.max_single_dml_bytes,
                    state_table=args.state_table,
                    states=states,
                    expiration_timestamp=expiration_timestamp,
                )
                for target, source in DELETE_TARGETS.items()
                if table_filter(target.table)
            ]
        )
    if not results:
        logging.error("No tables selected")
        parser.exit(1)
    bytes_processed, bytes_deleted = map(sum, zip(*results))
    if args.dry_run:
        logging.info(f"Would scan {bytes_processed} in total")
    else:
        logging.info(f"Scanned {bytes_processed} and deleted {bytes_deleted} in total")


if __name__ == "__main__":
    warnings.filterwarnings("ignore", module="google.auth._default")
    asyncio.run(main())
