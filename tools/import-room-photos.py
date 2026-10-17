#!/usr/bin/env python3
"""
KLIP — bulk-import room photos and wire them into the galleries.

    python3 tools/import-room-photos.py

Drop the studio photos into img/rooms-in/ and run this. It resizes them for
the web, writes them into img/, regenerates the responsive widths, and fills
in gallery[] for the matching room in data/studio.json. Then rebuild.

It never guesses which room a photo belongs to. A file is matched only by a
room word in its filename, and anything it cannot place is listed and left
alone rather than being filed somewhere plausible:

    podcast        -> Klip Room
    black          -> Kapture Room
    green / screen -> Kreator Room
    white-wall / headshot / kanvas -> Kanvas Room
    lobby / overview / facility    -> not a room; skipped

The Drive set in "Contenido Un edited > KLIP Facility" and the numbered
"google-apple-*" photos already use these words, so they sort themselves.

Re-running is safe: a photo already in a room's gallery is not added twice.
Existing gallery entries are kept, so anything added through /admin survives.

Adding one or two photos is easier through /admin -> Studio & rooms -> the
room -> Photo gallery. This script is for doing fifteen at once.
"""
import json
import os
import re
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, 'img', 'rooms-in')
IMG = os.path.join(ROOT, 'img')
STUDIO = os.path.join(ROOT, 'data', 'studio.json')
MAX_W = 2000          # plenty for a full-screen gallery image
QUALITY = 82

# Checked in order, so the most specific word wins.
RULES = [
    ('Kanvas Room', ('white-wall', 'whitewall', 'headshot', 'kanvas')),
    ('Kreator Room', ('green', 'screen', 'kreator')),
    ('Kapture Room', ('black', 'kapture')),
    ('Klip Room', ('podcast', 'klip-room', 'kliproom')),
]
SKIP = ('lobby', 'overview', 'facility', 'exterior', 'brand-wall', 'neon')


def room_for(name):
    low = name.lower()
    if any(w in low for w in SKIP):
        return None
    for room, words in RULES:
        if any(w in low for w in words):
            return room
    return None


def alt_for(name, room):
    """A readable description from the filename, so no image ships without
    alt text. Edit it afterwards in /admin if you want something better."""
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r'^\d+[-_]', '', stem)
    stem = re.sub(r'google[-_]apple[-_]', '', stem, flags=re.I)
    stem = re.sub(r'\s*\(\d+\)$', '', stem)
    words = re.sub(r'[-_]+', ' ', stem).strip()
    for r, _ in RULES:
        words = re.sub(re.escape(r.split()[0]) + r'\s*room\s*', '', words, flags=re.I)
    words = re.sub(r'\s+', ' ', words).strip()
    return ('%s — %s' % (room, words)) if words else room


def main():
    if not os.path.isdir(IN):
        os.makedirs(IN, exist_ok=True)
        print('Created %s\nPut the room photos in there and run this again.' % IN)
        return 0

    files = [f for f in sorted(os.listdir(IN))
             if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    if not files:
        print('No photos in %s — nothing to do.' % IN)
        return 0

    with open(STUDIO, encoding='utf-8') as fh:
        data = json.load(fh)
    rooms = {r['name']: r for r in data['studio']['rooms']}

    placed, skipped = 0, []
    for f in files:
        room = room_for(f)
        if not room or room not in rooms:
            skipped.append(f)
            continue

        stem = re.sub(r'[^a-z0-9]+', '-', os.path.splitext(f)[0].lower()).strip('-')
        stem = re.sub(r'^\d+-', '', stem)[:48]
        out_name = '%s.jpg' % stem
        rel = 'img/' + out_name
        out_path = os.path.join(IMG, out_name)

        with Image.open(os.path.join(IN, f)) as im:
            im = im.convert('RGB')
            if im.width > MAX_W:
                im = im.resize((MAX_W, round(im.height * MAX_W / im.width)),
                               Image.LANCZOS)
            im.save(out_path, 'JPEG', quality=QUALITY, optimize=True,
                    progressive=True)
            im.save(os.path.join(IMG, '%s.webp' % stem), 'WEBP',
                    quality=78, method=6)

        r = rooms[room]
        gal = r.setdefault('gallery', [])
        if rel == r.get('image') or any(g.get('image') == rel for g in gal):
            print('  = %-46s already in %s' % (f, room))
            continue
        gal.append({'image': rel, 'alt': alt_for(f, room)})
        placed += 1
        print('  + %-46s -> %s' % (f, room))

    with open(STUDIO, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')

    if skipped:
        print('\nNot placed (no room word in the filename):')
        for f in skipped:
            print('  ? ' + f)
        print('Rename them with the room word, or add them in /admin.')

    print('\n%d photo(s) added.' % placed)
    print('Gallery sizes now:')
    for name, r in rooms.items():
        n = len(r.get('gallery') or []) + (1 if r.get('image') else 0)
        print('  %-14s %d photo(s)%s' % (name, n, '' if n >= 4 else '   <- needs 4'))

    # responsive widths, then the pages
    for cmd in (['python3', '-I', os.path.join(ROOT, 'tools', 'make-sizes.py')],
                ['python3', '-I', os.path.join(ROOT, 'build', 'build.py')]):
        if os.path.exists(cmd[2]):
            print('\n$ %s' % ' '.join(cmd[2:]))
            subprocess.run(cmd, cwd=ROOT, check=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
