#!/usr/bin/env python3
"""
CLI to load yaml (single file or recurse directory)
"""
import argparse
import logging
import operator
import os
import re
import requests
import urllib3
import yaml

from functools import reduce

from qdsl.queryable import ALL, q, Queryable, to_queryable  # noqa
from qdsl.boolean import *  # noqa

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("paths", nargs="+")
    return p.parse_args()


def _get_files(path):
    with os.scandir(path) as it:
        for ent in it:
            if ent.is_dir(follow_symlinks=False):
                for pth in _get_files(ent.path):
                    yield pth
            elif ent.is_file(follow_symlinks=False):
                yield ent.path


def analyze(paths, ignore=".*(log|txt)$"):
    ignore = re.compile(ignore).search if ignore else lambda _: False
    results = []

    def load(p):
        if not ignore(p):
            try:
                if p.startswith("http"):
                    data = requests.get(p, verify=False).text
                    doc = yaml.load(data, Loader=Loader)
                else:
                    with open(p) as f:
                        doc = yaml.load(f, Loader=Loader)
                if isinstance(doc, (list, dict)):
                    results.append(to_queryable(doc, source=p))
            except:
                pass

    paths = [paths] if not isinstance(paths, (tuple, list)) else paths
    for path in paths:
        if os.path.isdir(path):
            for p in _get_files(path):
                load(p)
        else:
            load(path)

    return reduce(operator.add, results, Queryable())


def main():
    args = parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level)

    conf = analyze(args.paths)

    import IPython
    from traitlets.config.loader import Config

    IPython.core.completer.Completer.use_jedi = False
    c = Config()
    c.PlainTextFormatter.max_seq_length = 0
    ns = {}
    ns.update(globals())
    ns["q"] = q
    ns["conf"] = conf
    IPython.start_ipython([], user_ns=ns, config=c)


if __name__ == "__main__":
    main()