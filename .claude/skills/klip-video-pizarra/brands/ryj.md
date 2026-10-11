# Respect Your Journey (RYJ): video-pizarra preset

Client: Respect Your Journey (sports podcast) · Output mode: client-branded (no Klip branding unless Enrique says so)

Source: "RYJ Brand Elevation Proposal" deck (claude.ai artifact, 2026-10-10), color, type and voice slides.
Status: PROPOSAL, not yet approved. Confirm with Enrique before using in published work and
update this file if the approved palette changes.

## Palette (from the proposal)
| Name | Hex | Role |
|---|---|---|
| Locker Black | #121212 | 60% · the stage |
| Apex Gold | #F5B51B | 15% · the earned color (key word, the Y) |
| Chalk | #F2EFE8 | 20% · type |
| Concrete | #2B2B2B | panels |
| Steel | #8C8C8C | secondary text |

Rule from the deck: "Black is the stage. Gold is earned." Gold goes on ONE key word per scene.

## Type
- Headlines: **Anton**, always UPPERCASE, key word in gold.
- Labels and body: **Poppins** (ExtraBold / SemiBold / Regular).

## Voice
The Teammate (Hero × Everyman): casual, serious, bold, local. Says: grind, process, comeback,
put in the work, real talk. Never: trash kids, clickbait that doesn't pay off, chase clout.

## Mascot / signature
The gold **Y-mark** (the crossroad) is RYJ's signature: use it as a stamp, chapter marker or end card.
[placeholder] Needs the Y-mark as a transparent PNG at `assets/ryj-y.png` (it's in the proposal deck assets).
No cartoon mascot by default; if one is wanted, a simple drawn athlete in gold/black, approved by Enrique first.
Never use the upstream `clawd` character.

## Styles engine (`template-estilos/video.js`)
Generate the style once per project: `python3 .../scripts/brand_style.py ryj` → `styles/ryj.js`
(Locker Black background, Chalk text, Apex Gold accent and button, Anton uppercase headlines, Poppins body). Tested 2026-10-11.
```js
style: 'ryj',
mascot: 'none',     // or { image: 'assets/ryj-y.png' }
person: false,
```

## Chalkboard engine (`template/scenes.js`) (fits RYJ well: locker-room chalkboard, coach's play diagram)
```js
palette: { ink: '#121212', orange: '#F5B51B', chalk: '#F2EFE8', chalkO: '#F5B51B', gray: '#8C8C8C', graphite: '#2B2B2B', paper: '#F2EFE8' },
hatches: { gold: ['#F5B51B', '#C98F00'] },
mascotTheme: 'gold',
```
Fonts: add `family=Anton&family=Poppins:wght@400;600;800` to `index.html` plus
`.anton{font-family:Anton,Impact,sans-serif;text-transform:uppercase}` and `.pop{font-family:Poppins,Arial,sans-serif;font-weight:600}`.
Headlines `cls: 'anton'`; keep `chalk` scenes (`newScene('chalk', { filter: 'url(#chalk)' })`) on `BG.solid('#121212')`.

## Compliance
Minors: no names, faces or likeness of youth athletes without guardian consent on file. Only licensed music.
