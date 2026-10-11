# Klip Studio / Klip Media: video-pizarra preset

Client: Klip Studio / Klip Media · Output mode: Klip-branded (Klip's own content only)

Source: Klip identity as recorded in the client-brand-kit skill (black #1D1D1C, red #E40E20,
off-white #EBEBEB, grey #5D5D5C, Montserrat). Status: approved Klip identity.
[placeholder] No Klip mascot exists yet. Until Enrique approves one, use the Klip logo as the
mascot or no mascot. Never use the upstream `clawd` character (another brand's character).

## Look
- Feel: clean studio, confident, modern. Red is the accent for one key word per scene, not a fill for everything.
- Recommended engine: `template-estilos/` with `style: 'klip'` (see below); use the chalkboard engine (`template/`) only when Enrique asks for the hand-drawn look.
- Language: English by default; Spanish when the post targets the Spanish-speaking audience (ask if unclear).

## Styles engine (`template-estilos/video.js`)
Generate the style once per project: `python3 .../scripts/brand_style.py klip` → `styles/klip.js`
(#EBEBEB background, #1D1D1C ink, #E40E20 accent and button, Montserrat 700 headlines). Tested 2026-10-11.
```js
style: 'klip',
mascot: 'none',     // or { image: 'assets/klip-logo.png' }: [placeholder] transparent PNG of the Klip mark
person: false,      // or { photo: 'assets/persona.png' } with an approved photo (cutout.py)
```

## Chalkboard engine (`template/scenes.js`, second argument of `bootVideo`)
```js
palette: { ink: '#1D1D1C', orange: '#E40E20', red: '#E40E20', gray: '#5D5D5C', paper: '#EBEBEB', cream: '#F5F5F3' },
hatches: { klip: ['#E40E20', '#B30A19'] },
mascotTheme: 'klip',
```
Fonts: add to the project's `index.html` `<link>`: `family=Montserrat:wght@600;800`, and the CSS class
`.brand{font-family:Montserrat,Arial,sans-serif;font-weight:800}`. Use `cls: 'brand'` for headlines and the CTA;
keep `hand`/`kalam` for the drawn-in-the-moment lines so it still reads as a whiteboard.
Scenes: use `BG.solid('#1D1D1C')` for chalk scenes and `BG.paper` for light ones; avoid the sepia/kraft backgrounds.

## CTA
Primary CTA from the Klip website bible: **Book Your Session** (alternates: Book Studio Time, Book Now).
Add theklipstudio.com as the URL only after confirming it is the live booking link.
