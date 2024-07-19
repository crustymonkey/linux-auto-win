#!/usr/bin/env python3

import json
import logging
import os
import re
import subprocess as sp
import sys
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from dataclasses import dataclass

# Path containing the video outputs in edid format
SYS_PATH = '/sys/class/drm'
# edid-decode binary
EDID = '/usr/bin/edid-decode'
MON_MAP = '_mon_map_'
ADJWIN = os.path.join(os.environ['HOME'], 'local/bin/adjwin.py')
UNKNOWN_STATE = 'unknown'


@dataclass
class Monitor:
    manufacturer: str
    model: str
    serial: str
    built_in: bool

    def as_dict(self):
        # Do not return the built-in bool
        return {
            'manufacturer': self.manufacturer,
            'model': self.model,
            'serial': self.serial,
        }


def get_args():
    desc = (
        'A script meant for automating the movement of windows using '
        'adjwin.py'
    )
    def_conf = os.path.join(os.environ["HOME"], '.adjwin.json')

    p = ArgumentParser(
        formatter_class=ArgumentDefaultsHelpFormatter,
        description=desc,
    )
    p.add_argument('-c', '--config', default=def_conf,
        help='The path to the JSON config. This should be the same file '
        'as `adjwin.py` uses.')
    p.add_argument('-s', '--state-file', default='/var/tmp/monmap.state',
        help='The path to the state file')
    p.add_argument('-m', '--monitors-only', default=False, action='store_true',
        help='Just output the monitors found and exit')
    p.add_argument('-D', '--debug', action='store_true', default=False,
        help='Add debug output')

    args = p.parse_args()

    return args


def setup_logging(args):
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        format=(
            '%(asctime)s - %(levelname)s - '
            '%(filename)s:%(lineno)d %(funcName)s - %(message)s'
        ),
        level=level,
    )


def get_conf(conf_path):
    with open(conf_path) as fh:
        conf = json.load(fh)

    return conf


def get_state(path):
    if not os.path.isfile(path):
        return None

    with open(path) as fh:
        return fh.read()


def set_state(state, path):
    with open(path, 'w') as fh:
        fh.write(state)


def get_edid_info(path):
    cmd = [EDID, path]
    p = sp.run([EDID, path], stdout=sp.PIPE, encoding='utf-8',
        errors='replace')
    if p.stdout.startswith(f"EDID of '{path}' was empty"):
        return None

    return p.stdout


def get_mon_from_edid(edid_info, built_in):
    mfctr = ''
    model = ''
    serial = ''
    serial_reg = re.compile(r'serial\s+number:\s+[\'"]?([^\'"\s]+)', re.I)

    for line in edid_info.split('\n'):
        if 'manufacturer:' in line.lower():
            mfctr = line.split()[1]
        elif 'model:' in line.lower():
            model = line.split()[1]
        elif m := serial_reg.search(line):
            serial = m.group(1)
        elif serial:
            # If we have a serial, we're done with this monitor
            return Monitor(mfctr, model, serial, False)
        elif (
            mfctr == built_in['manufacturer']
            and model == built_in['model']
        ):
            return Monitor(mfctr, model, serial, True)


def get_conn_monitors(args, conf):
    # Get the built-in monitor for matching
    bi = conf[MON_MAP]['built in']
    monitors = []

    for d in os.listdir(SYS_PATH):
        path = os.path.join(SYS_PATH, d, 'edid')  # /sys/class/drm/card*/edid
        if not os.path.exists(path):
            # This is something like the "version", skip it
            continue

        info = get_edid_info(path)
        if info is None:
            continue

        monitors.append(get_mon_from_edid(info, bi))

    return monitors


def is_mon_match(mons, mlist):
    if len(mons) != len(mlist):
        # fast fail
        return False

    mons_as_d = [m.as_dict() for m in mons]
    for d in mons_as_d:
        if d not in mlist:
            return False

    return True


def get_cur_state_name(mons, conf):
    if len(mons) == 1 and mons[0].built_in:
        # We are just using the built in monitor alone, return the map
        # name for it
        return conf[MON_MAP]['built in']['map']

    # Otherwise we try to match to a monitor config.  First, filter out
    # the built in monitor
    mons = [m for m in mons if not m.built_in]
    for name, mlist in conf[MON_MAP].items():
        if name == 'built in':
            continue

        if is_mon_match(mons, mlist):
            return name

    return None


def adjust_windows(cur_state, args):
    # First, move the windows
    if cur_state != UNKNOWN_STATE:
        logging.debug(f'Adjusting windows to {cur_state}')
        sp.run([ADJWIN, cur_state], check=True)

    # Now save the current state
    logging.debug(f'Saving the current state, {cur_state}, to {args.state_file}')
    set_state(cur_state, args.state_file)


def main():
    args = get_args()
    setup_logging(args)
    conf = get_conf(args.config)
    state = get_state(args.state_file)
    logging.debug(f'Saved state: {state}')

    mons = get_conn_monitors(args, conf)
    if args.monitors_only:
        print(f'Found the following monitors:')
        for mon in mons:
            print(f'    {mon}')
        return 0
    logging.debug(f'Found the following monitors: {mons}')

    # This should be like "home", "work", "laptop"
    cur_state = get_cur_state_name(mons, conf)
    logging.debug(f'Current state: {cur_state}')
    if cur_state is None:
        logging.warning('Failed to match to a monitor config, setting '
            'state to "unknown"')
        cur_state = UNKNOWN_STATE

    # If we get here, we have a matching state
    if state == cur_state:
        # We don't want to reshuffle if the saved state matches the current
        logging.debug(f'The current state matches the saved state, doing nothing')
        return 0

    # Now we need to adjust the windows to match the current config and save
    # the state
    adjust_windows(cur_state, args)

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
