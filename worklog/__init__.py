import os
from configparser import ConfigParser
from argparse import Namespace, ArgumentError
from datetime import date, timedelta

from worklog.utils import configure_logger, get_arg_parser, LOG_LEVELS, CONFIG_FILES
from worklog.log import Log


def dispatch(log: Log, cli_args: Namespace, cfg: ConfigParser) -> None:
    """
    Dispatch request to Log instance based on CLI arguments and
    configuration values.
    """
    if cli_args.subcmd == "commit":
        if cli_args.type in ["start", "stop"]:
            log.commit(
                "session",
                cli_args.type,
                cli_args.offset_minutes,
                force=cli_args.force,
            )
        elif cli_args.type == "undo":
            # entries = WorkLogEntries()
            # entries.parse(worklog_fp)
            # entries.undo()
            # entries.persist(worklog_fp, mode='overwrite')
            pass
    elif cli_args.subcmd == "task":
        if cli_args.type in ["start", "stop"]:
            if cli_args.id is None:
                raise ArgumentError(
                    cli_args.id, "--id is required when a new task is started/stopped"
                )
            log.commit(
                "task", cli_args.type, cli_args.offset_minutes, identifier=cli_args.id
            )
        elif cli_args.type == "list":
            log.list_tasks()
    elif cli_args.subcmd == "status":
        hours_target = float(cfg.get("workday", "hours_target"))
        hours_max = float(cfg.get("workday", "hours_max"))
        fmt = cli_args.fmt
        query_date = date.today()
        if cli_args.yesterday:
            query_date -= timedelta(days=1)
        log.status(hours_target, hours_max, query_date=query_date, fmt=fmt)
    elif cli_args.subcmd == "doctor":
        log.doctor()
    elif cli_args.subcmd == "log":
        n = cli_args.number
        use_pager = cli_args.all or n > 20
        if not cli_args.all:
            log.log(cli_args.number, use_pager)
        else:
            log.log(-1, use_pager)


def run() -> None:
    """ Main method """
    logger = configure_logger()
    parser = get_arg_parser()

    cli_args = parser.parse_args()
    logger.setLevel(LOG_LEVELS[min(cli_args.verbosity, len(LOG_LEVELS) - 1)])

    logger.debug(f"Parsed CLI arguments: {cli_args}")
    logger.debug(f"Path to config files: {CONFIG_FILES}")

    if cli_args.subcmd is None:
        parser.print_help()
        return

    cfg = ConfigParser()
    cfg.read(CONFIG_FILES)

    worklog_fp = os.path.expanduser(cfg.get("worklog", "path"))
    log = Log(worklog_fp)

    dispatch(log, cli_args, cfg)


if __name__ == "__main__":
    run()
