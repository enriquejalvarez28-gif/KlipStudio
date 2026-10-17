#!/usr/bin/env python3
"""
KLIP — check that /admin declares every key the data files contain.

Sveltia and Decap write back only the fields the config declares. A key
that exists in a data file but not in admin/config.yml is dropped the
first time someone saves that screen, silently and permanently.

This has bitten the project twice, so it is a test rather than a habit.
Run it after changing any data shape:

    python3 tools/qa-admin-keys.py
"""
import json
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# keys the build generates or that are internal; never edited in /admin
IGNORE = {'_note', 'mobileLabel', 'attr', 'href'}


def declared(fields, out=None, hidden=None):
    """Field names the config declares, and separately the ones marked
    hidden. A hidden widget round-trips whatever sits beneath it, so its
    whole subtree is safe and must not be reported."""
    out = set() if out is None else out
    hidden = set() if hidden is None else hidden
    for f in fields or []:
        out.add(f.get('name'))
        if f.get('widget') == 'hidden':
            hidden.add(f.get('name'))
        if f.get('fields'):
            declared(f['fields'], out, hidden)
        if f.get('field'):
            declared([f['field']], out, hidden)
        for t in (f.get('types') or []):
            declared(t.get('fields'), out, hidden)
    return out, hidden


def keys(o, hidden, out=None):
    """Every key in the data, not descending into a hidden subtree."""
    out = set() if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            out.add(k)
            if k in hidden:
                continue
            keys(v, hidden, out)
    elif isinstance(o, list):
        for x in o:
            keys(x, hidden, out)
    return out


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, 'admin', 'config.yml'),
                              encoding='utf-8'))
    problems = []
    checked = 0
    for col in cfg['collections']:
        entries = col.get('files')
        if not entries:
            continue
        for f in entries:
            if not f.get('file'):
                continue
            path = os.path.join(ROOT, f['file'])
            if not os.path.exists(path):
                problems.append((f['file'], ['FILE MISSING']))
                continue
            data = json.load(open(path, encoding='utf-8'))
            have, hidden = declared(f.get('fields'))
            missing = sorted(keys(data, hidden) - have - IGNORE)
            checked += 1
            if missing:
                problems.append((f['file'], missing))

    print('Checked %d admin screens.' % checked)
    if not problems:
        print('No keys would be lost on save.')
        return 0
    print('\nKeys present in data but NOT declared in admin — these are')
    print('dropped the first time the screen is saved:\n')
    for path, miss in problems:
        print('  %-28s %s' % (path, ', '.join(miss)))
    return 1


if __name__ == '__main__':
    sys.exit(main())
