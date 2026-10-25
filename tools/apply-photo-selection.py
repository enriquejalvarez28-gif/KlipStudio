#!/usr/bin/env python3
"""
KLIP — place the chosen photos from a shoot into /img and wire the rooms.

    python3 tools/apply-photo-selection.py [--include-people]

Reads tools/photo-selection.json, which maps a source frame from the shoot
to the filename it should have on the site and says where it belongs. The
files themselves are expected in img/drive-2048/ under their target names.

It writes each photo into img/ as a JPEG plus a full-size WebP, appends the
room photos to the matching gallery in data/studio.json, then regenerates
the responsive widths. Photos marked "people": true show identifiable faces
and are held back unless --include-people is passed, because publishing
someone's face is a release question and not a build decision.

Re-running is safe. A photo already in a room's gallery is not added twice,
and entries added through /admin are left alone.
"""
import json
import os
import shutil
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'img', 'drive-2048')
IMG = os.path.join(ROOT, 'img')
STUDIO = os.path.join(ROOT, 'data', 'studio.json')
SELECTION = os.path.join(ROOT, 'tools', 'photo-selection.json')

MAX_W = 2000
QUALITY = 82


def rooms_in(data):
    """Every room object in data/studio.json, by name."""
    found = {}

    def walk(o):
        if isinstance(o, dict):
            if 'name' in o and 'image' in o and 'gallery' in o:
                found[o['name']] = o
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(data)
    return found


def main():
    include_people = '--include-people' in sys.argv
    sel = json.load(open(SELECTION, encoding='utf-8'))['selection']
    data = json.load(open(STUDIO, encoding='utf-8'))
    rooms = rooms_in(data)

    placed, held, missing, added = [], [], [], 0

    for entry in sel:
        target = entry['target']
        src = os.path.join(SRC, target)
        if not os.path.exists(src):
            missing.append(target)
            continue
        if entry.get('people') and not include_people:
            held.append(target)
            continue

        stem = os.path.splitext(target)[0]
        with Image.open(src) as im:
            im = im.convert('RGB')
            if im.width > MAX_W:
                im = im.resize((MAX_W, round(im.height * MAX_W / im.width)),
                               Image.LANCZOS)
            im.save(os.path.join(IMG, target), 'JPEG', quality=QUALITY,
                    optimize=True, progressive=True)
            im.save(os.path.join(IMG, stem + '.webp'), 'WEBP',
                    quality=78, method=6)
        placed.append(target)

        room = entry.get('room')
        if not room:
            continue
        if room not in rooms:
            print('  ! no room called %r in data/studio.json' % room)
            continue
        r = rooms[room]
        rel = 'img/' + target
        gal = r.setdefault('gallery', [])
        if rel == r.get('image') or any(g.get('image') == rel for g in gal):
            continue
        gal.append({'image': rel, 'alt': entry.get('alt') or room})
        added += 1

    with open(STUDIO, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')

    print('Placed %d photo(s) into img/.' % len(placed))
    print('Added %d to room galleries.' % added)
    if held:
        print('\nHeld back - these show identifiable people and need a '
              'release before they go live:')
        for t in held:
            print('  . ' + t)
        print('Run again with --include-people once that is confirmed.')
    if missing:
        print('\nNot found in img/drive-2048/:')
        for t in missing:
            print('  ? ' + t)

    print('\nRoom galleries now:')
    for name, r in rooms.items():
        n = len(r.get('gallery') or []) + (1 if r.get('image') else 0)
        print('  %-14s %d photo(s)%s'
              % (name, n, '' if n >= 4 else '   <- wants 4'))

    for cmd in (['python3', '-I', os.path.join(ROOT, 'tools', 'make-sizes.py')],
                ['python3', '-I', os.path.join(ROOT, 'build', 'build.py')]):
        print('\n$ %s' % os.path.basename(cmd[2]))
        subprocess.run(cmd, cwd=ROOT, check=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
