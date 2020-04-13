from typing import List, Iterable, Tuple, Dict, Optional
from pandas import DataFrame, Series  # type: ignore
import logging
import sys
import argparse
import os
from functools import reduce
from datetime import datetime, date, timezone, timedelta, tzinfo

LOG_FORMAT: str = logging.BASIC_FORMAT
LOG_LEVELS: List[int] = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]

CONFIG_FILES: List[str] = [
    os.path.expanduser("~/.config/worklog/config"),
    os.path.join(os.path.abspath(os.path.dirname(__file__)), "config.cfg"),
]

LOCAL_TIMEZONE: Optional[tzinfo] = datetime.now(timezone.utc).astimezone().tzinfo


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("worklog")
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(LOG_FORMAT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def format_timedelta(td: timedelta) -> str:
    try:
        total_secs = td.total_seconds()
        hours, remainder = divmod(total_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
    except ValueError:
        return "{:02}:{:02}:{:02}".format(0, 0, 0)


def _positive_int(value: str) -> int:
    value_int = int(value)
    if value_int <= 0:
        raise argparse.ArgumentTypeError(f"{value} is not a positive int value.")
    return value_int


def get_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Worklog", description="Simple CLI tool to log work and projects."
    )
    parser.add_argument("-v", "--verbose", dest="verbosity", action="count", default=0)

    subparsers = parser.add_subparsers(dest="subcmd")

    commit_parser = subparsers.add_parser("commit")
    commit_parser.add_argument(
        "type",
        choices=["start", "stop", "undo"],
        help="Commits a new entry to the log.",
    )
    commit_parser.add_argument(
        "--offset-minutes",
        type=float,
        default=0,
        help="Offset of the start/stop time in minutes",
    )
    commit_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force command, will auto-stop running tasks",
    )

    task_parser = subparsers.add_parser("task")
    task_parser.add_argument(
        "type",
        choices=["start", "stop", "list", "report"],
        help="Starts/stops or list tasks",
    )
    task_parser.add_argument(
        "--id", type=str, help="Task identifier",
    )
    task_parser.add_argument(
        "--offset-minutes",
        type=float,
        default=0,
        help="Offset of the start/stop time in minutes",
    )

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument(
        "--yesterday",
        action="store_true",
        help="Returns the status of yesterday instead of today.",
    )
    status_parser.add_argument(
        "--fmt", type=str, default=None, help="Use a custom formatted string"
    )

    doctor_parser = subparsers.add_parser("doctor")

    log_parser = subparsers.add_parser("log")
    log_parser.add_argument(
        "-n",
        "--number",
        type=_positive_int,
        default=10,
        help="Defines many log entries should be shown. System pager will be used if n > 20.",
    )
    log_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Show all entries. System pager will be used.",
    )

    return parser


def empty_df_from_schema(schema: Iterable[Tuple[str, str]]) -> DataFrame:
    def reducer(acc: Dict, x: Tuple[str, str]):
        acc[x[0]] = Series(dtype=x[1])
        return acc

    return DataFrame(reduce(reducer, schema, {}))


def get_datetime_cols_from_schema(schema: Iterable[Tuple[str, str]]) -> List[str]:
    def reducer(acc: List, x: Tuple[str, str]):
        if "datetime" in x[1]:
            acc.append(x[0])
        return acc

    return reduce(reducer, schema, [])


def check_order_session(df_group: DataFrame, logger: logging.Logger):
    last_type = None
    for i, row in df_group.where(df_group["category"] == "session").iterrows():
        if i == 0 and row["type"] != "start":
            logger.error(
                f'First entry of type "session" on date {row.date} is not "start".'
            )
        if row["type"] == last_type:
            logger.error(
                f'"session" entries on date {row.date} are not ordered correctly.'
            )
        last_type = row["type"]
    if last_type != "stop":
        logger.error(f"Date {row.date} has no stop entry.")


def sentinel_datetime(
    target_date: date, tzinfo: Optional[tzinfo] = LOCAL_TIMEZONE
) -> datetime:
    if target_date > datetime.now().date():
        raise ValueError("Only dates on the same day or in the past are supported.")
    return min(
        datetime.now(timezone.utc).astimezone(tz=tzinfo).replace(microsecond=0),
        datetime(
            target_date.year, target_date.month, target_date.day, 23, 59, 59, 0, tzinfo,
        ).astimezone(tz=tzinfo),
    )


def get_active_task_ids(df: DataFrame, query_date: date):
    df_day = df[df["date"] == query_date]
    df_day = df_day[df_day.category == "task"]
    df_day = df_day[["log_dt", "type", "identifier"]]
    df_grouped = df_day.groupby("identifier").tail(1)
    return sorted(df_grouped[df_grouped["type"] == "start"]["identifier"].unique())


def extract_intervals(
    df: DataFrame,
    dt_col: str = "log_dt",
    token_start: str = "start",
    token_stop: str = "stop",
    logger: Optional[logging.Logger] = None,
):
    def log_error(msg):
        if logger:
            logger.error(msg)

    intervals = []
    last_start: Optional[datetime] = None
    for i, row in df.iterrows():
        if row["type"] == "start":
            if last_start is not None:
                log_error(f"Start entry at {last_start} has no stop entry. Skip entry.")
            last_start = row[dt_col]
        elif row["type"] == "stop":
            if last_start is None:
                log_error("No start entry found. Skip entry.")
                continue  # skip this entry
            td = row[dt_col] - last_start
            d = last_start.date()
            intervals.append(
                {"date": d, "start": last_start, "stop": row[dt_col], "interval": td}
            )
            last_start = None
        else:
            log_error(f"Found unknown type {row['type']}. Skip entry.")
            continue
    if last_start is not None:
        log_error(f"Start entry at {last_start} has no stop entry. Skip entry.")

    return DataFrame(intervals)