/**
 * KLIP — regenerate the WebP copies of every JPEG in /img, and the
 * list the site reads to know which ones exist.
 *
 * Images uploaded through /admin work straight away without this; the
 * site just serves the JPEG. Run this when you want those uploads to
 * get the smaller WebP version too (roughly 45% less to download).
 *
 *   node tools/make-webp.js
 *
 * Needs sharp once:  npm install sharp
 */
const fs = require('fs');
const path = require('path');

const IMG = path.join(__dirname, '..', 'img');
const LIST = path.join(__dirname, '..', 'data', 'webp.json');

let sharp;
try {
  sharp = require('sharp');
} catch (e) {
  console.error('sharp is not installed. Run:  npm install sharp');
  process.exit(1);
}

(async () => {
  const jpegs = fs.readdirSync(IMG).filter((f) => /\.jpe?g$/i.test(f));
  let made = 0;

  for (const file of jpegs) {
    const out = file.replace(/\.jpe?g$/i, '.webp');
    const outPath = path.join(IMG, out);
    const srcTime = fs.statSync(path.join(IMG, file)).mtimeMs;
    if (fs.existsSync(outPath) && fs.statSync(outPath).mtimeMs >= srcTime) continue;
    await sharp(path.join(IMG, file)).webp({ quality: 80, effort: 6 }).toFile(outPath);
    console.log('wrote img/' + out);
    made++;
  }

  const list = fs.readdirSync(IMG).filter((f) => f.endsWith('.webp')).sort();
  fs.writeFileSync(LIST, JSON.stringify(list, null, 0));
  console.log(`\n${made} new, ${list.length} WebP files listed in data/webp.json`);
})();
