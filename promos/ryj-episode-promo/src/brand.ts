// RYJ tokens (RYJ Brand Elevation proposal — pending approval)
import { loadFont } from '@remotion/fonts';
import { staticFile } from 'remotion';

export const C = { black: '#121212', gold: '#F5B51B', chalk: '#F2EFE8', concrete: '#2B2B2B', steel: '#8C8C8C', body: '#CFCBC2' };
export const DISPLAY = 'Anton, Impact, sans-serif';
export const BODY = 'Poppins, Arial, sans-serif';

loadFont({ family: 'Anton', url: staticFile('Anton.woff2') });
for (const w of [400, 600, 800]) loadFont({ family: 'Poppins', url: staticFile(`Poppins-${w}.woff2`), weight: String(w) });
