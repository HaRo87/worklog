import configparser
import os

from worklog.utils import get_logger, get_arg_parser, LOG_LEVELS, CONFIG_FILES
from worklog.log import Log


def dispatch(cfg, cli_args):
    worklog_fp = os.path.expanduser(cfg.get("worklog", "path"))

    log = Log(worklog_fp)

    if cli_args.subcmd == "commit":
        if cli_args.type in ["start", "stop"]:
            log.commit(cli_args.type, cli_args.offset_minutes)
        elif cli_args.type == "undo":
            # entries = WorkLogEntries()
            # entries.parse(worklog_fp)
            # entries.undo()
            # entries.persist(worklog_fp, mode='overwrite')
            pass
    elif cli_args.subcmd == "status":
        hours_target = float(cfg.get("workday", "hours_target"))
        hours_max = float(cfg.get("workday", "hours_max"))
        fmt = cli_args.fmt
        if cli_args.yesterday:
            log.status(hours_target, hours_max, date="yesterday", fmt=fmt)
        else:
            log.status(hours_target, hours_max, fmt=fmt)
    elif cli_args.subcmd == "doctor":
        log.doctor()
    elif cli_args.subcmd == "log":
        n = cli_args.number
        use_pager = cli_args.all or n > 20
        log.log(cli_args.number, use_pager)


def run():
    logger = get_logger()
    parser = get_arg_parser()

    cli_args = parser.parse_args()
    logger.setLevel(LOG_LEVELS[min(cli_args.verbosity, len(LOG_LEVELS) - 1)])

    logger.debug(f"Parsed CLI arguments: {cli_args}")
    logger.debug(f"Path to config files: {CONFIG_FILES}")

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILES)

    dispatch(cfg, cli_args)


if __name__ == "__main__":
    run()
