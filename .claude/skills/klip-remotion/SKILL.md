---
name: klip-remotion
description: Use with the Remotion skills (remotion-best-practices, remotion-create, remotion-render…) when building a Remotion (React) video for Klip Studio, Respect Your Journey or a client. Adds brand tokens, cloud-render fixes and Klip's delivery rules.
---

# klip-remotion

Remotion's own skills (Anthropic Directory plugin "Remotion", or `npx skills add remotion-dev/skills`)
cover how to write and render Remotion. This file only adds what's specific to Klip.

## When Remotion vs the other video tools
- **Remotion:** branded motion pieces built from data or templates: episode promos, guest cards, stat reels, lower thirds, end cards, many variants of one template.
- **klip-video-pizarra:** whiteboard / explainer reels with a mascot and drawn text.
- **HyperFrames (caption-motion-studio):** captions over real footage on Enrique's PC.

## Brand tokens
Identify the client first (client-brand-kit). Put tokens in `src/brand.ts` and use them everywhere.
- **Klip:** bg `#EBEBEB`, ink `#1D1D1C`, accent `#E40E20`, grey `#5D5D5C`; Montserrat (700 headlines). CTA "Book Your Session".
- **RYJ:** bg `#121212`, text `#F2EFE8`, accent `#F5B51B` (one key word per scene), panels `#2B2B2B`, muted `#8C8C8C`;
  Anton UPPERCASE headlines, Poppins body. (From the RYJ Brand Elevation proposal, pending approval.)
- Full voice/mascot/compliance notes: `.claude/skills/klip-video-pizarra/brands/klip.md` and `ryj.md`.

## Rendering in a cloud session (tested 2026-10-11, Remotion 4.0.534)
- Browser: `--browser-executable=/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell`
  (the full `chromium` binary fails: "Old Headless mode has been removed").
- Fonts: `@remotion/google-fonts` fails in the cloud (the proxy's certificate isn't trusted by headless Chrome).
  Download the woff2 with `curl` into `public/` and load it with `@remotion/fonts` `loadFont({ family, url: staticFile('X.woff2') })`.
  Never use `--ignore-certificate-errors`. Local fonts are also more reliable on the PC.

## Delivery rules
- Render a still (`npx remotion still … --frame=N`) of every scene and inspect it before the full render.
- Only licensed/owned music, footage and fonts; log them in `CLIENTS/<client>/approvals/asset-log.md`.
- Deliver as DRAFT; nothing is posted or sent without Enrique's approval.
- License: Remotion is free for individuals and small companies; larger companies need a paid company license.
  Check remotion.dev/license if Klip's headcount grows.
