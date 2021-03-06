r"""Metric counting.

```bash
python3 -m bigquery_etl.glam.bucket_counts
```
"""
from argparse import ArgumentParser
from jinja2 import Environment, PackageLoader

from bigquery_etl.format_sql.formatter import reformat


def render_query(**kwargs) -> str:
    """Render the main query."""
    env = Environment(loader=PackageLoader("bigquery_etl", "glam/templates"))
    sql = env.get_template("bucket_counts_v1.sql")
    return reformat(sql.render(**kwargs))


def telemetry_variables():
    """Variables for bucket_counts."""
    attributes_list = ["os", "app_version", "app_build_id", "channel"]
    return dict(
        source_table="telemetry_derived.clients_scalar_aggregates_v1",
        attributes=",".join(attributes_list),
        scalar_metric_types="""
            "scalars",
            "keyed-scalars"
        """,
        boolean_metric_types="""
            "boolean",
            "keyed-scalar-boolean"
        """,
        aggregate_attributes="""
            metric,
            metric_type,
            key,
            process
        """,
        aggregate_attributes_type="""
            metric STRING,
            metric_type STRING,
            key STRING,
            process STRING
        """,
    )


def glean_variables():
    """Variables for bucket_counts."""
    attributes_list = ["ping_type", "os", "app_version", "app_build_id", "channel"]
    return dict(
        source_table="glam_etl.fenix_clients_scalar_aggregates_v1",
        attributes=",".join(attributes_list),
        # does _not_ include boolean
        scalar_metric_types="""
            "counter",
            "quantity",
            "labeled_counter"
        """,
        boolean_metric_types="""
            "boolean"
        """,
        aggregate_attributes="""
            metric,
            metric_type,
            key
        """,
        aggregate_attributes_type="""
            metric STRING,
            metric_type STRING,
            key STRING
        """,
    )


def main():
    """Generate query for bucketing."""
    parser = ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--ping-type",
        default="telemetry",
        choices=["glean", "telemetry"],
        help="determine attributes and user data types to aggregate",
    )
    args = parser.parse_args()
    module_name = "bigquery_etl.glam.bucket_counts"
    header = f"-- generated by: python3 -m {module_name}"
    header += " " + " ".join(
        [f"--{k} {v}" for k, v in vars(args).items() if k != "init"]
    )
    variables = (
        telemetry_variables() if args.ping_type == "telemetry" else glean_variables()
    )
    print(render_query(header=header, **variables))


if __name__ == "__main__":
    main()
