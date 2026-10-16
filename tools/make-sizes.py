#!/usr/bin/env python3
"""
KLIP — generate the smaller image widths phones should get.

    python3 tools/make-sizes.py

For every JPEG in /img it writes WebP copies at 480, 768, 1200 and 1600px
(only widths smaller than the original), into img/r/. The build reads
data/srcset.json and emits srcset + sizes, so a 390px phone downloads the
480px file instead of a 2000px one.

Re-run it after adding images through /admin. Needs Pillow:
    pip install pillow
"""
import json
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, 'img')
OUT = os.path.join(IMG, 'r')
WIDTHS = [480, 768, 1200, 1600]

os.makedirs(OUT, exist_ok=True)
manifest = {}
made = 0

for name in sorted(os.listdir(IMG)):
    if not name.lower().endswith(('.jpg', '.jpeg')):
        continue
    src = os.path.join(IMG, name)
    stem = os.path.splitext(name)[0]
    with Image.open(src) as im:
        w0, h0 = im.size
        widths = [w for w in WIDTHS if w < w0]
        if not widths:
            continue
        entries = []
        for w in widths:
            out_name = '%s-%d.webp' % (stem, w)
            out_path = os.path.join(OUT, out_name)
            if not os.path.exists(out_path) or \
                    os.path.getmtime(out_path) < os.path.getmtime(src):
                im.convert('RGB').resize(
                    (w, max(1, round(h0 * w / w0))), Image.LANCZOS
                ).save(out_path, 'WEBP', quality=78, method=6)
                made += 1
            entries.append([w, 'img/r/' + out_name])
        # the full-size WebP closes the set
        full = stem + '.webp'
        if os.path.exists(os.path.join(IMG, full)):
            entries.append([w0, 'img/' + full])
        manifest['img/' + name] = entries

with open(os.path.join(ROOT, 'data', 'srcset.json'), 'w', encoding='utf-8') as fh:
    json.dump(manifest, fh, indent=0, sort_keys=True)

total = sum(len(v) for v in manifest.values())
print('%d new files; %d images with %d sources listed in data/srcset.json'
      % (made, len(manifest), total))
