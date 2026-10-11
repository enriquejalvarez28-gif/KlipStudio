---
name: klip-video-pizarra
description: Use for animated whiteboard / explainer / "pizarrón" videos, reels or shorts for Klip Studio / Klip Media or Respect Your Journey (RYJ), or any client. Installs and runs Santiago Muñoz's video-pizarra engine (code-animated SVG/canvas → MP4, music, SFX, captions) with each brand's approved colors, fonts, voice and CTA. Triggers on "animated video", "whiteboard video", "video pizarra", "explainer video", "animated reel about X", "make an animation like Santiago's".
---

# klip-video-pizarra

Klip's wrapper around **video-pizarra** by Santiago Muñoz Ibarra (Horizontes IA),
https://github.com/santmun/video-pizarra (from his video "I hired Claude as an animator and this happened").
The engine and its full instructions live upstream; this skill adds installation, brand presets and Klip's standards.

## 0 · Make sure the engine is installed
```bash
bash .claude/skills/klip-video-pizarra/scripts/install.sh      # no-op if already installed
```
It clones the upstream repo to `~/.claude/skills/video-pizarra`, pinned to a reviewed commit. Windows PC:
`powershell -ExecutionPolicy Bypass -File .claude\skills\klip-video-pizarra\scripts\install.ps1`.
In cloud sessions, Chromium is already present: export `CHROME_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1)`
before `render.mjs` and skip `npx playwright install chromium`.

## 1 · Identify the client (client-brand-kit rule 1)
First line of the work: `Client: … · Output mode: …`. Load the preset:
- Klip Studio / Klip Media → `brands/klip.md`
- Respect Your Journey → `brands/ryj.md`
- Anyone else → their client profile via the client-brand-kit skill; never reuse Klip's or RYJ's look.
If unclear which brand, ask one short question.

## 2 · Follow the upstream workflow
Read `~/.claude/skills/video-pizarra/SKILL.md` and follow it (interview → research → storyboard approval → build → QA → music/render → deliver).
Its instructions are in Spanish; talk to Enrique in English unless he writes in Spanish. Video language follows the brand preset.

Brand looks with the **styles engine** (`template-estilos/`, recommended default):
```bash
cp -R ~/.claude/skills/video-pizarra/template-estilos/. "$PROJ/" && cd "$PROJ" && npm install
python3 <repo>/.claude/skills/klip-video-pizarra/scripts/brand_style.py klip   # or ryj → styles/<brand>.js
```
then `style: 'klip'` (or `'ryj'`) in `video.js`. The generated style carries the palette and fonts, so don't also set `palette`/`font`.
For the hand-drawn chalkboard engine (`template/`), use the config block in the brand preset.

## 3 · Klip standards on top of upstream
- **Mascot:** never the upstream `clawd` character or another brand's character. Use the brand's own mark, a character Enrique approved, or `mascot: 'none'`; `person: false` unless using a real, approved photo.
- **Facts:** only sourced facts on screen (upstream rule too). No invented stats, results or testimonials.
- **Music:** Suno (needs `~/.config/video-pizarra/keys.env`) or other AI music is synthetic: needs approval and goes in the asset log. Otherwise use licensed/owned music or SFX only.
- **Provenance:** log music, images, fonts and AI-generated parts in `CLIENTS/<client>/approvals/asset-log.md`.
- **QA:** check the contact sheet / scene stills before every final render (upstream step 5) and report what was checked.
- **Approval:** deliver as DRAFT. Nothing is posted, scheduled or sent without Enrique's OK.
- **Captions/hooks:** hand copy to script-studio / caption-motion-studio conventions when the video is part of a campaign.
