#!/usr/bin/env python3

from argparse import ArgumentParser
import json
import logging
import os
import subprocess as sp
from typing import List, Dict


WMCTRL = '/usr/bin/wmctrl'
PROC_CACHE = []


class ProcInfo():

    def __init__(self, input_line):
        self.wid = None
        self.desktop = -1
        self.pid = -1
        self.xpos = 0
        self.ypos = 0
        self.width = 0
        self.height = 0
        self.name = ''
        self._parse_input(input_line.strip())

    def _parse_input(self, line):
        i = line.split(maxsplit=8)
        self.wid = i[0]
        self.desktop = int(i[1])
        self.pid = int(i[2])
        self.xpos = int(i[3])
        self.ypos = int(i[4])
        self.width = int(i[5])
        self.height = int(i[6])
        self.name = i[8]
        self.shell = self.is_shell()

    def is_shell(self) -> bool:
        global PROC_CACHE
        if not PROC_CACHE:
            PROC_CACHE = _get_procs()

        return 'gnome-terminal' in PROC_CACHE[self.pid][10]

    def __repr__(self):
        return f'Procinfo: {self.__dict__}'


def get_args():
    cdefault = os.path.join(os.environ['HOME'], '.adjwin.json')
    p = ArgumentParser()
    p.add_argument('-c', '--profile-config', default=cdefault,
        help='The path to the profile config [default: %(default)s]')
    p.add_argument('-D', '--debug', action='store_true', default=False,
        help='Add debug output [default: %(default)s]')
    p.add_argument('profile', help='The profile to use for window adjustment')

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


def get_current_desktop() -> int:
    res = sp.run([WMCTRL, '-d'], stdout=sp.PIPE, encoding='utf-8',
        errors='ignore')
    for line in res.stdout.split('\n'):
        parts = line.split()
        if parts[1] == '*':
            return int(parts[0])


def get_work_area_off():
    res = sp.run([WMCTRL, '-d'], stdout=sp.PIPE, encoding='utf-8',
        errors='ignore')
    items = res.stdout.split('\n')[0].split()
    xy = items[7]
    x, y = [int(i) for i in xy.split(',')]
    return (x, y)


def get_proc_info() -> List[ProcInfo]:
    ret = []
    cmd = [WMCTRL, '-l', '-G', '-p']
    logging.debug(f'Running: {" ".join(cmd)}')
    res = sp.run(cmd, stdout=sp.PIPE, encoding='utf-8',
        errors='ignore')

    for line in res.stdout.split('\n'):
        if not line.strip():
            continue
        ret.append(ProcInfo(line))

    return ret


def get_profiles(args):
    logging.debug(f'Getting profiles from {args.profile_config}')
    with open(args.profile_config) as fh:
        conf = json.load(fh)

    return conf


def set_window(wid, prof):
    # First, move the window to its position
    cmd = [WMCTRL, '-ir']
    cmd.extend([wid, '-e', f'0,{prof["xoff"]},{prof["yoff"]},'
        f'{prof["width"]},{prof["height"]}'])
    logging.debug(f'Running: {" ".join(cmd)}')
    sp.run(cmd)

    # Now, move the window to its desktop
    cmd = [WMCTRL, '-ir', wid, '-t', str(prof["desk"])]
    logging.debug(f'Running: {" ".join(cmd)}')
    sp.run(cmd)


def move_windows(procs: List[ProcInfo], conf, args):
    prof = conf[args.profile]

    for win in prof:
        to_rem = None

        for i, pi in enumerate(procs):
            if win['name'] in pi.name:
                logging.debug(f'Adjusting window {pi.name}')
                to_rem = i
                set_window(pi.wid, win)
                break

        if to_rem is not None:
            del procs[to_rem]
            to_rem = None


def _get_procs() -> Dict[int, List[str]]:
    ret = {}
    res = sp.run(['ps', 'auxww'], stdout=sp.PIPE, encoding='utf-8',
        errors='ignore')

    for line in res.stdout.split('\n'):
        line = line.strip()
        if line.startswith('USER') or not line:
            continue
        parts = line.strip().split(maxsplit=10)
        ret[int(parts[1])] = parts

    return ret


def main():
    args = get_args()
    setup_logging(args)

    procs = get_proc_info()
    conf = get_profiles(args)
    if args.profile not in conf:
        raise RuntimeError(f'The profile must be one of: {list(conf.keys())}')
    move_windows(procs, conf, args)


if __name__ == '__main__':
    main()
