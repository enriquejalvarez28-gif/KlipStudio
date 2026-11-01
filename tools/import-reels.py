#!/usr/bin/env python3
"""
KLIP — turn client reels into work the site can play.

    mkdir -p video/reels-in
    # drop the .mp4 files in there, one per piece of work
    python3 tools/import-reels.py

For each file it writes, into video/reels/ and img/:

    <slug>.mp4           the reel itself, re-encoded for the web
    <slug>.webm          a smaller copy for browsers that take it
    <slug>-loop.mp4      a short silent loop, for the card preview
    <slug>-loop.webm
    img/reel-<slug>.jpg  a poster frame, so the card has something to show

and adds the piece to data/pages.json -> work -> the portfolio block, so it
appears on the Work page. It is not added to the homepage grid: that grid is
four hand-picked tiles and choosing them is an editorial decision.

Why re-encode rather than upload what came off the phone: a reel exported
from Instagram or a camera is tens of megabytes and often 4K. Cloudflare
will serve it, but a visitor on a phone pays for every byte. These come out
around 1-3 MB at 1080px, which is the same picture on a phone screen.

Naming: the filename becomes the title, so call the file what the work is.
"Acme Dental - launch reel.mp4" becomes "Acme Dental - Launch Reel".

    python3 tools/import-reels.py --category "Short-Form Social"
    python3 tools/import-reels.py --dry-run

Nothing is deleted from video/reels-in/; re-running skips anything already
imported, so it is safe to run twice.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, 'video', 'reels-in')
OUT = os.path.join(ROOT, 'video', 'reels')
IMG = os.path.join(ROOT, 'img')
PAGES = os.path.join(ROOT, 'data', 'pages.json')

MAX_W = 1080          # a reel is 9:16; 1080 wide is already more than a phone shows
LOOP_SECONDS = 6      # the silent card preview
CRF = 26              # visually clean at this size; lower means bigger files


def have(cmd):
    return shutil.which(cmd) is not None


def run(args):
    return subprocess.run(args, capture_output=True, text=True)


def probe(path):
    """width, height, duration — or None if ffprobe cannot read the file."""
    r = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height:format=duration',
             '-of', 'json', path])
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout)
        st = (d.get('streams') or [{}])[0]
        return (int(st.get('width') or 0), int(st.get('height') or 0),
                float((d.get('format') or {}).get('duration') or 0))
    except Exception:
        return None


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '-', os.path.splitext(name)[0].lower()).strip('-')
    return (s or 'reel')[:48]


def titleize(name):
    s = re.sub(r'[_]+', ' ', os.path.splitext(name)[0])
    s = re.sub(r'\s+', ' ', s).strip()
    return ' '.join(w if w.isupper() else w.capitalize() for w in s.split())


def encode(src, slug, w, h, dry):
    """The full reel, a WebM beside it, a silent loop, and a poster."""
    scale = 'scale=%d:-2' % MAX_W if w > MAX_W else 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
    jobs = [
        (os.path.join(OUT, slug + '.mp4'),
         ['ffmpeg', '-y', '-i', src, '-vf', scale, '-c:v', 'libx264', '-crf', str(CRF),
          '-preset', 'slow', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
          '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '128k']),
        (os.path.join(OUT, slug + '.webm'),
         ['ffmpeg', '-y', '-i', src, '-vf', scale, '-c:v', 'libvpx-vp9', '-crf', '34',
          '-b:v', '0', '-row-mt', '1', '-c:a', 'libopus', '-b:a', '96k']),
        # the card preview: silent, short, and small enough to autoplay
        (os.path.join(OUT, slug + '-loop.mp4'),
         ['ffmpeg', '-y', '-i', src, '-t', str(LOOP_SECONDS), '-an',
          '-vf', 'scale=640:-2', '-c:v', 'libx264', '-crf', '30', '-preset', 'slow',
          '-pix_fmt', 'yuv420p', '-movflags', '+faststart']),
        (os.path.join(OUT, slug + '-loop.webm'),
         ['ffmpeg', '-y', '-i', src, '-t', str(LOOP_SECONDS), '-an',
          '-vf', 'scale=640:-2', '-c:v', 'libvpx-vp9', '-crf', '38', '-b:v', '0',
          '-row-mt', '1']),
        (os.path.join(IMG, 'reel-%s.jpg' % slug),
         ['ffmpeg', '-y', '-ss', '1', '-i', src, '-frames:v', '1',
          '-vf', scale, '-q:v', '4']),
    ]
    made = []
    for dest, cmd in jobs:
        if os.path.exists(dest):
            made.append((dest, os.path.getsize(dest), 'kept'))
            continue
        if dry:
            made.append((dest, 0, 'would make'))
            continue
        r = run(cmd + [dest])
        if r.returncode != 0 or not os.path.exists(dest):
            tail = (r.stderr or '').strip().splitlines()[-1:] or ['ffmpeg failed']
            print('    ! %s — %s' % (os.path.basename(dest), tail[0][:110]))
            return None
        made.append((dest, os.path.getsize(dest), 'made'))
    return made


def add_to_work(slug, title, category, dry):
    """Put the piece on the Work page, if it is not already there."""
    d = json.load(open(PAGES, encoding='utf-8'),
                  object_pairs_hook=collections.OrderedDict)
    block = None
    for b in d['work']['blocks']:
        if b.get('type') == 'portfolio':
            block = b
            break
    if block is None:
        print('    ! no portfolio block on the Work page')
        return False
    rel = 'video/reels/%s.mp4' % slug
    if any(i.get('video') == rel for i in (block.get('items') or [])):
        return False
    item = collections.OrderedDict([
        ('image', 'img/reel-%s.jpg' % slug),
        ('title', title),
        ('sub', category),
        ('category', re.sub(r'[^a-z0-9]+', '-', category.lower()).strip('-')),
        ('format', 'reel'),
        ('video', rel),
        ('videoWebm', 'video/reels/%s.webm' % slug),
        ('poster', 'img/reel-%s.jpg' % slug),
        ('preview', 'video/reels/%s-loop.webm' % slug),
        ('previewMp4', 'video/reels/%s-loop.mp4' % slug),
    ])
    block.setdefault('items', []).insert(0, item)
    if not dry:
        json.dump(d, open(PAGES, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        open(PAGES, 'a', encoding='utf-8').write('\n')
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--category', default='Short-Form Social',
                    help='what kind of work these are (shown under the title)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    if not (have('ffmpeg') and have('ffprobe')):
        print('ffmpeg and ffprobe are needed. apt-get install ffmpeg')
        return 1
    os.makedirs(IN, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    files = sorted(f for f in os.listdir(IN)
                   if f.lower().endswith(('.mp4', '.mov', '.m4v', '.webm')))
    if not files:
        print('Nothing in video/reels-in/. Drop the reels there and run again.')
        return 0

    added = 0
    for f in files:
        src = os.path.join(IN, f)
        info = probe(src)
        if not info:
            print('  ? %-42s not a video ffprobe can read — skipped' % f)
            continue
        w, h, dur = info
        slug, title = slugify(f), titleize(f)
        shape = 'reel' if h > w else 'landscape'
        print('  %-42s %dx%d  %.0fs  %.1f MB  %s'
              % (f, w, h, dur, os.path.getsize(src) / 1048576, shape))
        if shape != 'reel':
            print('    note: this is landscape, not 9:16. It still imports, but '
                  'it will sit in a reel-shaped tile.')
        made = encode(src, slug, w, h, a.dry_run)
        if made is None:
            continue
        for dest, size, what in made:
            if what != 'kept':
                print('    %-9s %-34s %6.1f MB'
                      % (what, os.path.basename(dest), size / 1048576))
        if add_to_work(slug, title, a.category, a.dry_run):
            added += 1
            print('    added to the Work page as %r' % title)
        else:
            print('    already on the Work page')

    print('\n%d piece(s) added.' % added)
    if a.dry_run:
        print('Dry run — nothing was written.')
        return 0
    for cmd in (['python3', '-I', os.path.join(ROOT, 'tools', 'make-sizes.py')],
                ['python3', '-I', os.path.join(ROOT, 'build', 'build.py')]):
        print('\n$ %s' % os.path.basename(cmd[2]))
        subprocess.run(cmd, cwd=ROOT, check=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
