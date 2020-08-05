# Worklog - Simple CLI util to track work hours

Worklog is a simple and straight-forward tool to track working times via CLI.
It uses a plain text file as it's storage backend which makes it easy to
process the logged information with other tools.

## Getting started

You need to have Python >= 3.6 installed.

```bash
# Install from PyPi Test-Servers as long as the version has not been published
# to the official registry yet.
pip install --index-url https://test.pypi.org/simple/ dcs-worklog
```

### Command Line Interface (CLI)

The tool registers itself as a CLI tool with the name `wl` (short for
`worklog`).

It provides the basic commands to start and stop tracking work times.

```bash
wl commit start    # starts a new work session
wl commit stop     # stops a running session
```

It's also possible to give a time offset to the current time:

```bash
wl commit start --offset-minutes 5
wl commit stop --offset-minutes -5
```

Learn about all options by using the `--help` flag for any command:

```bash
wl commit --help   # show more options
```

To see how the current status of the worklog use the `status` command:

```
$ wl status

Status         : Tracking on
Total time     : 07:49:40 ( 98%)
Remaining time : 00:10:20 (  2%)
Overtime       : 00:00:00 (  0%)
End of work    : 17:18:27
```

To see historical entries use the `log` command:

```bash
wl log             # shows the last 10 records (latest first)
wl log --all       # shows all records  (latest first)
```

### Configuration

By default the log file is written to `~/.worklog`.
The format is CSV with pipe symbols (`|`) as delimiters.

A working day is configured to have 8 hours.
2 hours are set as a (soft) limit for overtime.

This configuration can be changed by creating a config file in `~/.config/worklog/config` with the following content (or parts of it):

```ini
[worklog]
path = ~/.worklog

[workday]
hours_target = 8
hours_max = 10
```

### Integration in task bars

tbd

```bash
wl status --fmt '{status} | {remaining_time} (percentage}%'
```

### Sanity check

The current log file can be sanity-checked with the `doctor` command.
In case entries are missing the doctor command will tell so:

```
$ wl doctor
ERROR:worklog:Date 2020-04-08 has no stop entry.
```

## Development

Clone this repository and install the development version:

```bash
pip install -e ".[testing]"
```

Run tests via

```bash
pytest worklog/
```

### Create a release

**Attention**: Currently the software is released to the PyPi-Test-Channel
*only.

To create a release, update the version number in setup.py first.
Then execute the following commands:

```bash
python setup.py sdist bdist_wheel
twine upload -r testpypi dist/*
```

## Planned features

```bash
wl task create <NAME>
wl task list
wl task delete <NAME>
wl commit start --task <taskID>

wl report --today
wl report --yesterday
wl report --current-month
wl report --last-month
wl report --month 2020-04
wl report --date 2020-04-08

wl config get working_time.daily_hours
wl config set working_time.daily_hours 8

wl edit 2020-04-08
```