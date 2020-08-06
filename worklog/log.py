from typing import List, Tuple, Optional
from datetime import datetime, date, timedelta, timezone
import logging
import sys
import pandas as pd  # type: ignore
import numpy as np  # type: ignore
import subprocess
import tempfile
from pathlib import Path
from io import StringIO

from worklog.utils import (
    LOCAL_TIMEZONE,
    format_timedelta,
    empty_df_from_schema,
    get_datetime_cols_from_schema,
    check_order_session,
    sentinel_datetime,
    get_active_task_ids,
    extract_intervals,
    get_pager,
    get_or_update_dt,
)

logger = logging.getLogger("worklog")


class Log(object):
    # In-memory representation of log
    _log_df: pd.DataFrame = None

    # Backend file config
    _log_fp: Optional[str] = None
    _separator: Optional[str] = None
    _schema: List[Tuple[str, str]] = [
        ("commit_dt", "datetime64[ns]",),
        ("log_dt", "datetime64[ns]",),
        ("category", "object",),
        ("type", "object",),
        ("identifier", "object",),
    ]

    # Error messages
    _err_msg_empty_log = (
        "Fatal: No log data available. Start a new log entry with 'wl commit start'.\n"
    )
    _err_msg_empty_log_short = "N/A"
    _err_msg_log_data_missing_for_date = "No log data available for {query_date}.\n"
    _err_msg_log_data_missing_for_date_short = "N/A"
    _err_msg_commit_active_tasks = (
        "Fatal. Cannot stop, because tasks are still running. "
        "Stop running tasks first: {active_tasks:} or use --force flag.\n"
    )

    def __init__(self, fp: str, separator: str = "|") -> None:
        self._log_fp = fp
        self._separator = separator

        Path(self._log_fp).touch(mode=0o660)
        self._read()

    def _read(self) -> None:
        """
        Read data from input file.
        This method uses `pandas.read_csv` to parse the data.
        """
        date_cols = get_datetime_cols_from_schema(self._schema)
        header = [col for col, _ in self._schema]
        try:
            self._log_df = pd.read_csv(
                self._log_fp,
                sep=self._separator,
                parse_dates=date_cols,
                header=None,
                names=header,
            ).sort_values(by=["log_dt"])
        except pd.errors.EmptyDataError:
            self._log_df = empty_df_from_schema(self._schema)

        self._log_df = pd.concat(
            [self._log_df, self._extract_date_and_time(self._log_df)], axis=1
        )

    def _extract_date_and_time(
        self, df: pd.DataFrame, source_col: str = "log_dt"
    ) -> pd.DataFrame:
        """
        Extracts date and time information from a given pandas DataFrame.
        By default the source column is `log_dt`.
        """
        date = df[source_col].apply(lambda x: x.date)
        time = df[source_col].apply(lambda x: x.time)
        return pd.DataFrame(dict(date=date, time=time))

    def _persist(self, df: pd.DataFrame, mode="a") -> None:
        cols = [col for col, _ in self._schema]
        df[cols].to_csv(
            self._log_fp, mode=mode, sep=self._separator, index=False, header=False
        )

    def commit(
        self,
        category: str,
        type_: str,
        offset_min: int,
        time: Optional[str],
        identifier: str = None,
        force: bool = False,
    ) -> None:
        if type_ not in ["start", "stop"]:
            raise ValueError(f'Type must be one of {", ".join(type_)}')

        commit_date = datetime.now(timezone.utc).astimezone().replace(microsecond=0)
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        log_date = commit_date + timedelta(minutes=offset_min)

        if time is not None:
            log_date = get_or_update_dt(log_date, time)

        # Test if there are running tasks
        if category == "session":
            active_tasks = get_active_task_ids(self._log_df, log_date.date())
            if len(active_tasks) > 0:
                if not force:
                    msg = self._err_msg_commit_active_tasks.format(
                        active_tasks=active_tasks
                    )
                    sys.stderr.write(msg)
                    sys.exit(1)
                else:
                    for task_id in active_tasks:
                        self.commit("task", "stop", offset_min, time, task_id)

        cols = [col for col, _ in self._schema]
        values = [
            pd.to_datetime(commit_date),
            pd.to_datetime(log_date),
            category,
            type_,
            identifier,
        ]

        record = pd.DataFrame(dict(zip(cols, values)), index=[0],)
        record_t = pd.concat([record, self._extract_date_and_time(record)], axis=1)

        # append record to in-memory log
        self._log_df = pd.concat((self._log_df, record_t))
        # and persist to disk
        self._persist(record_t, mode="a")

        # Because we allow for time offsets sorting is not guaranteed at this point.
        # Update sorting of values in-memory.
        self._log_df = self._log_df.sort_values(by=["log_dt"])

    def doctor(self) -> None:
        self._log_df.groupby(["date"]).apply(
            lambda group: check_order_session(group, logger)
        )

    def _is_active(self, df: pd.DataFrame):
        """
        Returns True if the last entry in a given pandas DataFrame has 
        `type == 'start'`.

        Note: This method does not check for anything else. If this should
        just be applied to a single category, make sure to filter the pandas
        DataFrame first.
        """
        return df.iloc[-1]["type"] == "start" if df.shape[0] > 0 else False

    def _check_nonempty_or_exit(self, fmt: Optional[str]):
        """
        Tests if the log file has at least a single value.
        Exits with code 0 if no entry is available.
        """
        if self._log_df.shape[0] == 0:
            if fmt is None:
                sys.stderr.write(self._err_msg_empty_log)
            else:
                sys.stdout.write(self._err_msg_empty_log_short)
            sys.exit(0)

    def _filter_date_category_limit_cols(
        self,
        query_date: date,
        filter_category: str = "session",
        columns: List[str] = ["log_dt", "type"],
    ):
        """
        Filters the worklog DataFrame by query date and category.
        The returned DataFrame only includes the columns listed in the
        `columns` parameter.
        """
        # Extract the day of interest by selecting a subset of the log
        # dataframe that matches the queried day.
        mask = (self._log_df.date == query_date) & (
            self._log_df.category == filter_category
        )
        df = self._log_df[mask]
        df = df[columns]
        return df

    def _add_sentinel(self, query_date: date, df: pd.DataFrame):
        is_active = self._is_active(df)
        ret = df
        if is_active:
            sdt = sentinel_datetime(query_date)
            # attach another row with the current time
            sentinel_df = pd.DataFrame(
                {"log_dt": pd.to_datetime(sdt.isoformat()), "type": "stop",}, index=[0],
            )
            ret = pd.concat((ret, sentinel_df))
            logger.warning(f"Set sentinel stop value: {sdt}")
        return ret

    def _calc_facts(self, df: pd.DataFrame, hours_target: float, hours_max: float):
        shifted_dt = df["log_dt"].shift(1)
        stop_mask = df["type"] == "stop"
        total_time = (df[stop_mask]["log_dt"] - shifted_dt[stop_mask]).sum()
        total_time_str = format_timedelta(total_time)

        hours_target_dt = timedelta(hours=hours_target)
        hours_max_dt = timedelta(hours=hours_max)

        now = datetime.now(timezone.utc).astimezone().replace(microsecond=0)
        end_time = now + (hours_target_dt - total_time)
        end_time_str = end_time.strftime("%H:%M:%S")
        remaining_time = max(end_time - now, timedelta(minutes=0))
        remaining_time_str = format_timedelta(remaining_time)
        overtime = max(total_time - hours_target_dt, timedelta(minutes=0))
        overtime_str = format_timedelta(overtime)

        percentage = round(
            total_time.total_seconds() / hours_target_dt.total_seconds() * 100
        )
        percentage_remaining = max(0, 100 - percentage)
        percentage_overtime = max(
            round(
                overtime.total_seconds()
                / (hours_max_dt - hours_target_dt).total_seconds()
                * 100
            ),
            0,
        )
        return dict(
            percentage=percentage,
            end_of_work=end_time_str,
            total_time=total_time_str,
            remaining_time=remaining_time_str,
            remaining_time_short=remaining_time_str[: len("00:00")],
            percentage_remaining=percentage_remaining,
            overtime=overtime_str,
            overtime_short=overtime_str[: len("00:00")],
            percentage_overtime=percentage_overtime,
        )

    def status(
        self, hours_target: float, hours_max: float, query_date: date, fmt: str = None
    ) -> None:
        self._check_nonempty_or_exit(fmt)

        df_day = self._filter_date_category_limit_cols(query_date)

        if df_day.shape[0] == 0:
            if fmt is None:
                msg = self._err_msg_log_data_missing_for_date.format(
                    query_date=query_date
                )
                sys.stderr.write(msg)
            else:
                sys.stdout.write(self._err_msg_log_data_missing_for_date_short)
            return

        is_active = self._is_active(df_day)
        logger.debug(f"Is active: {is_active}")

        df_day = self._add_sentinel(query_date, df_day)
        facts = self._calc_facts(df_day, hours_target, hours_max)

        active_tasks = get_active_task_ids(self._log_df, query_date)

        lines = [
            ("Status", "Tracking {status}"),
            ("Total time", "{total_time} ({percentage:3}%)"),
            ("Remaining time", "{remaining_time} ({percentage_remaining:3}%)"),
            ("Overtime", "{overtime} ({percentage_overtime:3}%)"),
            ("Active tasks", "[{active_tasks}]",),
        ]

        if is_active and date == "today":
            lines += [("End of work", facts["end_time_str"],)]

        key_max_len = max([len(line[0]) for line in lines])
        fmt_string = "{:" + str(key_max_len + 1) + "s}: {}"

        stdout_fmt = "\n".join(fmt_string.format(*line) for line in lines) + "\n"

        sys.stdout.write(
            (stdout_fmt if fmt is None else fmt).format(
                **facts,
                status="on" if is_active else "off",
                active_tasks=", ".join(active_tasks),
            )
        )

    def log(self, n: int, use_pager: bool, filter_category: List[str]) -> None:
        if self._log_df.shape[0] == 0:
            sys.stdout.write("No data available\n")
            return

        fields = ["date", "time", "category", "type", "identifier"]
        df = self._log_df[fields].iloc[::-1]  # sort in reverse (latest first)
        df["identifier"] = df["identifier"].fillna("-")
        if filter_category:
            df = df[df["category"] == filter_category]
        if n > 0:
            df = df.head(n=n)
        if not use_pager:
            sys.stdout.write(df.to_string(index=False) + "\n")
        else:
            with tempfile.NamedTemporaryFile(mode="w") as fh:
                logger.debug(f"Write content to temporary file: {fh.name}")
                fh.write(df.to_string(index=False))
                fh.flush()
                pager = get_pager()
                if pager is None:
                    sys.stdout.write(df.to_string(index=False) + "\n")
                else:
                    logger.debug(f"Set pager to {pager}")
                    process = subprocess.Popen([pager, fh.name])
                    process.wait()

    def list_tasks(self):
        task_df = self._log_df[self._log_df["category"] == "task"]
        sys.stdout.write("These tasks are listed in the log:\n")
        for task_id in sorted(task_df["identifier"].unique()):
            sys.stdout.write(f"{task_id}\n")

    def task_report(self, task_id):
        task_mask = self._log_df["category"] == "task"
        task_id_mask = self._log_df["identifier"] == task_id
        mask = task_mask & task_id_mask
        task_df = self._log_df[mask]

        if task_df.shape[0] == 0:
            sys.stderr.write(
                (
                    f"Task ID {task_id} is unknown. "
                    "See 'wl task list' to list all known tasks.\n"
                )
            )
            exit(1)

        intervals = extract_intervals(task_df, logger=logger)

        intervals_detailed = intervals[["date", "start", "stop", "interval"]].rename(
            columns={
                "date": "Date",
                "start": "Start",
                "stop": "Stop",
                "interval": "Duration",
            }
        )
        print("Log entries:\n")
        print(
            intervals_detailed.to_string(
                index=False,
                formatters={
                    "Start": lambda x: x.strftime("%H:%M:%S"),
                    "Stop": lambda x: x.strftime("%H:%M:%S"),
                    "Duration": lambda x: format_timedelta(
                        timedelta(microseconds=int(x) / 1e3)
                    ),
                },
            )
        )

        print("---")
        print("Daily aggregated:\n")
        intervals_daily = intervals.groupby(by="date")[["interval"]].sum()
        intervals_daily.index.name = "Date"
        intervals_daily = intervals_daily.rename(columns={"interval": "Duration"})
        print(intervals_daily.to_string())

        print(f"---\nTotal: {intervals_detailed['Duration'].sum()}")

    def report(
        self, time: Optional[str],
    ):
        raise NotImplementedError()  # TODO: Finish implementation

        dt = datetime.now(timezone.utc).astimezone().replace(microsecond=0)
        if time is not None:
            dt = get_or_update_dt(dt, time)

        sub_df = (
            self._log_df.set_index("log_dt")
            .loc[dt.isoformat()[: len("2000-01-01")]]
            .reset_index()
        )
        sub_df_session = sub_df[sub_df.category == "session"]
        print(sub_df_session)

