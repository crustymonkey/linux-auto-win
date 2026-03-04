#!/usr/bin/env python3

from argparse import ArgumentParser
import json
import logging
import os
import subprocess as sp
import sys
from typing import List, Dict, Any


WMCTRL = '/usr/bin/wmctrl'
WCI = None
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
        try:
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
        except Exception as e:
            logging.warning(f'Invalid parsed line: {i}')

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
    p.add_argument('-s', '--show-cur', default=False, action='store_true',
        help='Show the current window config.  **with '
        'window-calls gnome extension only**. [default: %(default)s]')
    p.add_argument('-g', '--gen-conf', default=False, action='store_true',
        help='Generate an adjwin.json file (output to cur dir) '
        'based on the current window configuration **with '
        'window-calls gnome extension only**. [default: %(default)s]')
    p.add_argument('-D', '--debug', action='store_true', default=False,
        help='Add debug output [default: %(default)s]')
    p.add_argument('profile', nargs='?',
        help='The profile to use for window adjustment')

    args = p.parse_args()

    if args.show_cur and not win_calls_installed():
        p.error('--show-cur will only work with a window-calls extension')

    if args.gen_conf and not win_calls_installed():
        p.error('--gen-conf can only be used with window-calls extension')

    if args.gen_conf and not args.profile:
        p.error('You must supply a profile name for the conf you are '
            'generating')

    if not args.profile and not args.gen_conf and not args.show_cur:
        p.error('You must supply a profile')

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


def is_wayland():
    return os.environ['XDG_SESSION_TYPE'].lower() == 'wayland'


def win_calls_installed():
    global WCI
    if WCI is not None:
        return WCI

    cmd = ['gdbus', 'call',
        '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell/Extensions/Windows',
        '--method', 'org.gnome.Shell.Extensions.Windows.List',
    ]
    p = sp.run(cmd, capture_output=True)
    WCI = p.returncode == 0

    logging.debug(f'Window calls extension installed: {WCI}')

    return WCI


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


def set_window_ext(winid: int, conf):
    mv_cmd = [
        'gdbus', 'call',
        '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell/Extensions/Windows',
        '--method', 'org.gnome.Shell.Extensions.Windows.MoveResize',
    ]
    ws_cmd = [
        'gdbus', 'call',
        '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell/Extensions/Windows',
        '--method', 'org.gnome.Shell.Extensions.Windows.MoveToWorkspace',
    ]

    # First, resize the window and set it to its position
    cmd = mv_cmd + [
        str(winid), str(conf['xoff']), str(conf['yoff']),
        str(conf['width']), str(conf['height']),
    ]
    logging.debug(f'Moving window with id: {winid}')
    sp.run(cmd, capture_output=True, check=True)

    # Now, move it to it's workspace
    cmd = ws_cmd + [str(winid), str(conf['desk'])]
    logging.debug(f'Moving window {winid} to workspace {conf["desk"]}')
    sp.run(cmd, capture_output=True, check=True)


def mv_w_extension(windows: Dict[str, List[Dict[str, Any]]], conf, args):
    for win_conf in conf[args.profile]:
        to_rem = None

        for i, win in enumerate(windows):
            if win_conf['name'] in win['title']:
                logging.debug(f'Adjusting window {win["title"]}')
                to_rem = i
                set_window_ext(win['id'], win_conf)
                break

        if to_rem is not None:
            del windows[to_rem]
            to_rem = None


def move_windows(procs: List[ProcInfo], conf, args):
    if win_calls_installed():
        logging.debug('Moving windows with the win calls extension')
        return mv_w_extension(procs, conf, args)

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


def get_windows() -> Dict[str, List[Dict[str, Any]]]:
    cmd = [
        'gdbus', 'call',
        '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell/Extensions/Windows',
        '--method', 'org.gnome.Shell.Extensions.Windows.List',
    ]
    details_cmd = [
        'gdbus', 'call',
        '--session',
        '--dest', 'org.gnome.Shell',
        '--object-path', '/org/gnome/Shell/Extensions/Windows',
        '--method', 'org.gnome.Shell.Extensions.Windows.Details',
    ]

    p = sp.run(cmd, capture_output=True, encoding='utf-8', errors='ignore')
    stripped = p.stdout.strip("\"',()\n")
    if stripped[2] == '\\':
        # Things get commented out in a weird way when there are ' or " chars
        # in a window title.  This fixes the escape formatting.
        stripped = stripped.replace('\\', '')
    windows = json.loads(stripped)

    # Get window details and append them
    for win in windows:
        try:
            cmd = details_cmd + [str(win['id'])]
        except Exception as e:
            logging.exception('Something has gone horribly wrong')
            sys.exit(1)
        p = sp.run(cmd, capture_output=True, encoding='utf-8', errors='ignore')
        stripped = p.stdout.strip("',()\n")
        o = json.loads(stripped)
        win.update(o)

    return sorted(windows, key=lambda x: x['id'])


def show_cur():
    windows = get_windows()
    print(f'{json.dumps(windows, indent=4)}')


def gen_conf(args):
    windows = get_windows()
    conf = {args.profile: []}

    for win in windows:
        conf[args.profile].append({
            'name': win['title'],
            'desk': win['workspace'],
            'xoff': win['x'],
            'yoff': win['y'],
            'width': win['width'],
            'height': win['height'],
        })

    with open('adjwin.json', 'w') as fh:
        json.dump(conf, fh, indent=4)
    print('Configuration written to adjwin.json')


def main():
    args = get_args()
    setup_logging(args)

    if args.show_cur:
        show_cur()
        return 0

    if args.gen_conf:
        gen_conf(args)
        return 0

    procs = get_windows() if win_calls_installed() else get_proc_info()
    conf = get_profiles(args)
    if args.profile not in conf:
        raise RuntimeError(f'The profile must be one of: {list(conf.keys())}')
    move_windows(procs, conf, args)


if __name__ == '__main__':
    main()
