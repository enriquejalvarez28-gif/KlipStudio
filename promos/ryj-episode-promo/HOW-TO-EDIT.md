# RYJ Episode Promo: how to edit

15-second vertical promo (1080×1920) for every new RYJ episode.

## Every new episode (2 minutes)
1. Open **`episode.json`** and change the text between the quotes:

   | Field | Example |
   |---|---|
   | `episode` | `EP 24` |
   | `guest` | `AJ Braziel` |
   | `credential` | `Former D1 linebacker` |
   | `quote` | A REAL line from the episode. Put `*asterisks*` around the word you want in gold. |
   | `release` | `OUT THURSDAY` |
   | `platforms` | `YouTube · Spotify · Apple Podcasts` |
   | `youtube`, `instagram` | RYJ's handles (set once, then leave them) |
   | `photo` | Drop the guest photo or thumbnail in `public/` and type its file name, e.g. `aj.jpg`. Leave `""` for none. |

2. Render: `npm run render` → **`out/RYJ_promo.mp4`**

## Prefer clicking instead of editing a file?
`npm run studio` opens a preview in your browser. Every field above is a text box on the right,
the video updates live, and the **Render** button exports the MP4.

## First time on a computer
Needs Node.js 18+. In this folder run `npm install` once.

## Change the look or timing
- Colors and fonts: `src/brand.ts`
- Scene lengths (in frames, 30 = 1 second): the `T` line near the top of `src/Promo.tsx`
- Logos: `public/ryj-logo.png` (on black) and `public/ryj-logo-black.png` (on gold). Keep the same file names if you replace them.

## Rules
- The quote must be something the guest actually said.
- No music is included. Add only music RYJ owns or has licensed.
- It's a DRAFT until Enrique approves it.

## Logos (repo copy only)
This repo is public, so the RYJ logo files are not committed. Put `ryj-logo.png` and `ryj-logo-black.png`
in `public/` (from the RYJ brand kit or the template zip) before rendering.
