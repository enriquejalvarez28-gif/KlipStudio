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
around 1-3 MB at 720px, which is wider than the portrait player ever gets.

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

# A reel plays in a portrait lightbox, which is sized by height: about
# 400px wide on a phone, under 500 on a desktop. Encoding at 1080 wide
# produced 20 MB for a 50-second clip - heavier than the rest of the page
# put together - to carry detail no viewer is ever shown. 720 is still
# above what anyone gets.
MAX_W = 720
LOOP_SECONDS = 6      # the silent card preview
CRF = 28              # at 720 wide this is clean; lower means bigger files
VP9_CRF = 36
WARN_MB = 6           # say so if a finished reel is still heavier than this


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


# Capitalising every word turns "no money for groceries" into "No Money For
# Groceries", which reads like a headline generator. Small words stay down
# unless they open the title or follow a full stop.
SMALL = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in', 'is',
         'nor', 'of', 'on', 'or', 'the', 'to', 'vs', 'with'}


def titleize(name):
    s = re.sub(r'[_]+', ' ', os.path.splitext(name)[0])
    s = re.sub(r'\s+', ' ', s).strip()
    out, opens = [], True
    for w in s.split():
        if w.isupper():
            pass                       # VP, RYJ - leave an acronym alone
        elif opens or w.lower() not in SMALL:
            w = w[:1].upper() + w[1:]
        else:
            w = w.lower()
        out.append(w)
        opens = w.endswith(('.', ':', '?', '!'))
    return ' '.join(out)


def encode(src, slug, w, h, dry):
    """The full reel, a WebM beside it, a silent loop, and a poster."""
    scale = 'scale=%d:-2' % MAX_W if w > MAX_W else 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
    jobs = [
        (os.path.join(OUT, slug + '.mp4'),
         ['ffmpeg', '-y', '-i', src, '-vf', scale, '-c:v', 'libx264', '-crf', str(CRF),
          '-preset', 'slow', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
          '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '96k']),
        (os.path.join(OUT, slug + '.webm'),
         ['ffmpeg', '-y', '-i', src, '-vf', scale, '-c:v', 'libvpx-vp9', '-crf', str(VP9_CRF),
          '-b:v', '0', '-row-mt', '1', '-cpu-used', '2', '-c:a', 'libopus', '-b:a', '80k']),
        # the card preview: silent, short, and small enough to autoplay
        (os.path.join(OUT, slug + '-loop.mp4'),
         ['ffmpeg', '-y', '-i', src, '-t', str(LOOP_SECONDS), '-an',
          '-vf', 'scale=480:-2', '-c:v', 'libx264', '-crf', '31', '-preset', 'slow',
          '-pix_fmt', 'yuv420p', '-movflags', '+faststart']),
        (os.path.join(OUT, slug + '-loop.webm'),
         ['ffmpeg', '-y', '-i', src, '-t', str(LOOP_SECONDS), '-an',
          '-vf', 'scale=480:-2', '-c:v', 'libvpx-vp9', '-crf', '40', '-b:v', '0',
          '-row-mt', '1', '-cpu-used', '3']),
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


def work_filters():
    """The filter keys the Work page actually offers."""
    d = json.load(open(PAGES, encoding='utf-8'))
    for b in d['work']['blocks']:
        if b.get('type') == 'portfolio':
            return [f['key'] for f in (b.get('filters') or [])]
    return []


def add_to_work(slug, title, category, filt, dry):
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
        # The filter key has to be one the page offers. Slugifying the label
        # instead produced 'short-form-social', which matches no button, so
        # the piece vanished under every filter except All.
        ('category', filt),
        ('format', 'reel'),
        ('video', rel),
        # only referenced when the file is actually there and smaller
        ('videoWebm', 'video/reels/%s.webm' % slug
         if os.path.exists(os.path.join(OUT, slug + '.webm')) else ''),
        ('poster', 'img/reel-%s.jpg' % slug),
        ('preview', 'video/reels/%s-loop.webm' % slug
         if os.path.exists(os.path.join(OUT, slug + '-loop.webm')) else ''),
        ('previewMp4', 'video/reels/%s-loop.mp4' % slug),
    ])
    block.setdefault('items', []).insert(0, item)
    if not dry:
        json.dump(d, open(PAGES, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        open(PAGES, 'a', encoding='utf-8').write('\n')
    return True


def mmss(seconds):
    s = int(round(seconds))
    return '%d:%02d' % (s // 60, s % 60)


def add_to_clips(slug, title, show, dur, dry):
    """Put the piece in the Featured Clips rail, if it is not already there.

    Clips live in two files: data/podcasts.json feeds the homepage rail and
    the clips block in data/pages.json feeds the Podcasts page. A clip that
    went into only one of them would be real work on one page and missing on
    the other, so both are written or neither is.
    """
    rel = 'video/reels/%s.mp4' % slug
    item = collections.OrderedDict([
        ('image', 'img/reel-%s.jpg' % slug),
        ('show', show),
        ('title', title),
        ('time', mmss(dur)),
        ('video', rel),
        ('kind', 'clip'),
        ('preview', 'video/reels/%s-loop.webm' % slug
         if os.path.exists(os.path.join(OUT, slug + '-loop.webm')) else ''),
        ('previewMp4', 'video/reels/%s-loop.mp4' % slug),
    ])

    def lists():
        """(path, data, items) for each file that holds the clip rail."""
        pods = os.path.join(ROOT, 'data', 'podcasts.json')
        d = json.load(open(pods, encoding='utf-8'),
                      object_pairs_hook=collections.OrderedDict)
        yield pods, d, d['podcasts'].setdefault('items', [])
        p = json.load(open(PAGES, encoding='utf-8'),
                      object_pairs_hook=collections.OrderedDict)
        for b in p['podcasts']['blocks']:
            if b.get('type') == 'clips':
                yield PAGES, p, b.setdefault('items', [])
                return
        print('    ! no clips block on the Podcasts page')

    wrote = False
    for path, data, items in lists():
        if any(i.get('video') == rel for i in items):
            continue
        items.append(collections.OrderedDict(item))
        if not dry:
            json.dump(data, open(path, 'w', encoding='utf-8'),
                      indent=2, ensure_ascii=False)
            open(path, 'a', encoding='utf-8').write('\n')
        wrote = True
    return wrote


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='work', choices=('work', 'clips'),
                    help='work = the Work page grid; clips = the Featured '
                         'Clips rail on the homepage and the Podcasts page')
    ap.add_argument('--category', default='Short-Form Social',
                    help='the line shown under the title on the tile; with '
                         '--target clips this is the show name')
    ap.add_argument('--filter', default='reels',
                    help='which Work page filter these sit under')
    ap.add_argument('--title',
                    help='the title to use, instead of deriving it from the '
                         'filename. Only with a single file: a filename makes '
                         'a poor Spanish title, and cannot carry punctuation.')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    if not (have('ffmpeg') and have('ffprobe')):
        print('ffmpeg and ffprobe are needed. apt-get install ffmpeg')
        return 1
    os.makedirs(IN, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    keys = work_filters() if a.target == 'work' else []
    if keys and a.filter not in keys:
        print('--filter %r is not one of the Work page filters: %s'
              % (a.filter, ', '.join(keys)))
        return 1

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
        slug, title = slugify(f), (a.title if a.title and len(files) == 1
                                   else titleize(f))
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
                heavy = ('  <- heavy for a web reel'
                         if dest.endswith(('.mp4', '.webm'))
                         and '-loop' not in dest
                         and size / 1048576 > WARN_MB else '')
                print('    %-9s %-34s %6.1f MB%s'
                      % (what, os.path.basename(dest), size / 1048576, heavy))
        # VP9 is usually the smaller file, but not on heavy motion. Both
        # the player and the card preview offer WebM first, so a WebM that
        # lost to its own MP4 would be the one every browser downloads.
        # Keep it only when it wins, for the reel and for the loop.
        for stem in (slug, slug + '-loop'):
            webm = os.path.join(OUT, stem + '.webm')
            mp4 = os.path.join(OUT, stem + '.mp4')
            if (os.path.exists(webm) and os.path.exists(mp4)
                    and os.path.getsize(webm) >= os.path.getsize(mp4)):
                print('    dropping %s.webm: %.2f MB against the MP4\'s %.2f'
                      % (stem, os.path.getsize(webm) / 1048576,
                         os.path.getsize(mp4) / 1048576))
                if not a.dry_run:
                    os.remove(webm)
        where = 'the Featured Clips rail' if a.target == 'clips' else 'the Work page'
        done = (add_to_clips(slug, title, a.category, dur, a.dry_run)
                if a.target == 'clips'
                else add_to_work(slug, title, a.category, a.filter, a.dry_run))
        if done:
            added += 1
            print('    added to %s as %r' % (where, title))
        else:
            print('    already on %s' % where)

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
