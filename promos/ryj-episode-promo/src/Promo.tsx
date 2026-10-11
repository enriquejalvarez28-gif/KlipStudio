import React from 'react';
import { AbsoluteFill, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing } from 'remotion';
import { z } from 'zod';
import { C, DISPLAY, BODY } from './brand';

// Every field here shows up as an editable box in `npm run studio`.
export const promoSchema = z.object({
  episode: z.string().describe('Episode tag, e.g. EP 24'),
  guest: z.string().describe('Guest name'),
  credential: z.string().describe('One-line credential'),
  quote: z.string().describe('Real line from the episode. *Word* in asterisks turns gold'),
  release: z.string().describe('e.g. OUT THURSDAY'),
  platforms: z.string(),
  youtube: z.string().describe('YouTube handle'),
  instagram: z.string().describe('Instagram handle'),
  photo: z.string().describe('Guest photo file name in public/ (leave empty for none)'),
});
export type PromoProps = z.infer<typeof promoSchema>;

// Scene timing in frames (30 fps). Change these to retime the whole promo.
const T = { sting: 36, newEp: 45, guest: 90, quote: 108, social: 78, end: 93 };
export const DURATION = T.sting + T.newEp + T.guest + T.quote + T.social + T.end; // 450 = 15 s

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;
const rise = (f: number, start: number, dist = 70) => ({
  opacity: interpolate(f, [start, start + 6], [0, 1], clamp),
  transform: `translateY(${interpolate(f, [start, start + 10], [dist, 0], { ...clamp, easing: ease })}px)`,
});
const punch = (f: number, fps: number, start: number) => spring({ frame: f - start, fps, config: { damping: 9, stiffness: 220, mass: 0.6 } });

// Two roads meet: the crossroad from the RYJ brand
const Path: React.FC<{ start: number; opacity?: number }> = ({ start, opacity = 1 }) => {
  const f = useCurrentFrame();
  const p = interpolate(f, [start, start + 14], [0, 1], { ...clamp, easing: ease });
  return (
    <svg width={1080} height={1920} style={{ position: 'absolute', opacity }}>
      {['M 180 1920 L 540 1080', 'M 900 1920 L 540 1080'].map((d) => (
        <path key={d} d={d} stroke={C.concrete} strokeWidth={70} fill="none" strokeDasharray={1400} strokeDashoffset={1400 * (1 - p)} />
      ))}
    </svg>
  );
};

const Drift: React.FC<{ dur: number; children: React.ReactNode }> = ({ dur, children }) => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{ transform: `scale(${interpolate(f, [0, dur], [1, 1.05])})` }}>{children}</AbsoluteFill>;
};

const Corner: React.FC = () => <Img src={staticFile('ryj-logo.png')} style={{ position: 'absolute', top: 120, right: 80, width: 240 }} />;

const Sting: React.FC = () => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.black, alignItems: 'center', justifyContent: 'center' }}>
      <Path start={0} />
      <Img src={staticFile('ryj-logo.png')} style={{ width: 980, transform: `scale(${punch(f, fps, 5)}) translateY(-60px)` }} />
    </AbsoluteFill>
  );
};

const NewEp: React.FC<{ episode: string }> = ({ episode }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.gold, alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
      <Drift dur={T.newEp}>
        <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ fontFamily: DISPLAY, fontSize: 290, lineHeight: 0.88, color: C.black, transform: `scale(${punch(f, fps, 0)})` }}>NEW<br />EPISODE</div>
          <div style={{ ...rise(f, 10, 40), marginTop: 40, background: C.black, color: C.gold, fontFamily: BODY, fontWeight: 800, fontSize: 56, letterSpacing: 8, padding: '10px 34px' }}>{episode}</div>
        </AbsoluteFill>
      </Drift>
      <Img src={staticFile('ryj-logo-black.png')} style={{ position: 'absolute', top: 120, right: 80, width: 240 }} />
    </AbsoluteFill>
  );
};

const Guest: React.FC<PromoProps> = ({ episode, guest, credential, photo }) => {
  const f = useCurrentFrame();
  const bar = interpolate(f, [12, 22], [0, 1], { ...clamp, easing: ease });
  return (
    <AbsoluteFill style={{ background: C.black }}>
      {photo ? <Img src={staticFile(photo)} style={{ width: '100%', height: 1150, objectFit: 'cover', transform: `scale(${interpolate(f, [0, T.guest], [1.1, 1])})` }} />
        : <div style={{ height: 1150, background: `repeating-linear-gradient(135deg, ${C.concrete} 0 40px, #232323 40px 80px)`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: BODY, fontWeight: 600, fontSize: 40, color: C.steel }}>[GUEST PHOTO]</div>}
      <div style={{ position: 'absolute', top: 700, height: 450, width: '100%', background: `linear-gradient(transparent, ${C.black})` }} />
      <div style={{ position: 'absolute', left: 80, right: 80, top: 1080, transform: `translateY(${interpolate(f, [0, T.guest], [0, -30])}px)` }}>
        <div style={{ ...rise(f, 0, 30), display: 'inline-block', background: C.gold, color: C.black, fontFamily: BODY, fontWeight: 800, fontSize: 40, padding: '6px 20px', letterSpacing: 4 }}>NEW · {episode}</div>
        <div style={{ ...rise(f, 4), fontFamily: DISPLAY, fontSize: 170, lineHeight: 0.95, color: C.chalk, textTransform: 'uppercase', marginTop: 28 }}>{guest}</div>
        <div style={{ marginTop: 34, height: 6, width: `${bar * 100}%`, background: C.gold }} />
        <div style={{ ...rise(f, 16, 30), fontFamily: BODY, fontWeight: 600, fontSize: 44, color: C.body, marginTop: 24 }}>{credential}</div>
      </div>
      <Corner />
    </AbsoluteFill>
  );
};

const Quote: React.FC<{ quote: string }> = ({ quote }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: C.gold }}>
      <Drift dur={T.quote}>
        <AbsoluteFill style={{ padding: 80, justifyContent: 'center' }}>
          <div style={{ fontFamily: DISPLAY, fontSize: 300, color: C.black, lineHeight: 0.6, height: 140, opacity: interpolate(f, [0, 4], [0, 1]) }}>“</div>
          <div style={{ fontFamily: DISPLAY, fontSize: 128, lineHeight: 1.1, textTransform: 'uppercase' }}>
            {quote.split(' ').map((w, i) => {
              const key = w.includes('*');
              return <span key={i} style={{ display: 'inline-block', marginRight: 28, marginBottom: 8, color: key ? C.gold : C.black, background: key ? C.black : 'transparent', padding: key ? '0 14px' : 0, ...rise(f, 3 + i * 2.5, 50) }}>{w.replace(/\*/g, '')}</span>;
            })}
          </div>
        </AbsoluteFill>
      </Drift>
      <Img src={staticFile('ryj-logo-black.png')} style={{ position: 'absolute', top: 120, right: 80, width: 240 }} />
    </AbsoluteFill>
  );
};

const YouTubeIcon = () => (
  <svg width={150} height={106} viewBox="0 0 150 106"><rect width={150} height={106} rx={28} fill="#FF0000" /><path d="M60 30 L60 76 L100 53 Z" fill="#FFF" /></svg>
);
const InstagramIcon = () => (
  <svg width={130} height={130} viewBox="0 0 130 130">
    <defs><linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stopColor="#FEDA75" /><stop offset="0.35" stopColor="#FA7E1E" /><stop offset="0.65" stopColor="#D62976" /><stop offset="1" stopColor="#4F5BD5" /></linearGradient></defs>
    <rect width={130} height={130} rx={34} fill="url(#ig)" /><rect x={28} y={28} width={74} height={74} rx={22} fill="none" stroke="#FFF" strokeWidth={9} />
    <circle cx={65} cy={65} r={17} fill="none" stroke="#FFF" strokeWidth={9} /><circle cx={91} cy={39} r={5.5} fill="#FFF" />
  </svg>
);

const Social: React.FC<PromoProps> = ({ youtube, instagram }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const clicked = f >= 30; // the Subscribe button gets "pressed"
  const press = interpolate(f, [26, 30, 36], [1, 0.88, 1], clamp);
  const row: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 40, background: C.concrete, borderRadius: 36, padding: '40px 48px', width: 920 };
  return (
    <AbsoluteFill style={{ background: C.black, alignItems: 'center', justifyContent: 'center', gap: 56, transform: `scale(${interpolate(f, [0, T.social], [1, 1.05])})` }}>
      <div style={{ ...rise(f, 0, 40), fontFamily: DISPLAY, fontSize: 150, lineHeight: 0.95, color: C.chalk, textAlign: 'center' }}>DON'T MISS <span style={{ color: C.gold }}>A JOURNEY</span></div>
      <div style={{ ...row, transform: `scale(${punch(f, fps, 6)})` }}>
        <YouTubeIcon />
        <div style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          <div style={{ fontFamily: BODY, fontWeight: 800, fontSize: 44, color: C.chalk, overflow: 'hidden', textOverflow: 'ellipsis' }}>{youtube}</div>
          <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 30, color: C.steel, marginBottom: 18 }}>YouTube</div>
          <span style={{ display: 'inline-block', transform: `scale(${press})`, background: clicked ? '#3A3A3A' : '#FF0000', color: '#FFF', fontFamily: BODY, fontWeight: 800, fontSize: 32, padding: '16px 30px', borderRadius: 999 }}>{clicked ? 'SUBSCRIBED ✓' : 'SUBSCRIBE'}</span>
        </div>
      </div>
      <div style={{ ...row, transform: `scale(${punch(f, fps, 14)})` }}>
        <InstagramIcon />
        <div style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          <div style={{ fontFamily: BODY, fontWeight: 800, fontSize: 44, color: C.chalk, overflow: 'hidden', textOverflow: 'ellipsis' }}>{instagram}</div>
          <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 30, color: C.steel, marginBottom: 18 }}>Instagram</div>
          <span style={{ display: 'inline-block', background: C.gold, color: C.black, fontFamily: BODY, fontWeight: 800, fontSize: 32, padding: '16px 30px', borderRadius: 999 }}>FOLLOW</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const End: React.FC<PromoProps> = ({ release, platforms, episode }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.gold, alignItems: 'center', justifyContent: 'center', textAlign: 'center', transform: `scale(${interpolate(f, [0, T.end], [1, 1.06])})` }}>
      <Img src={staticFile('ryj-logo-black.png')} style={{ width: 860, transform: `scale(${punch(f, fps, 0)})` }} />
      <div style={{ ...rise(f, 8, 30), fontFamily: BODY, fontWeight: 800, fontSize: 44, letterSpacing: 8, color: C.black, marginTop: 70 }}>{episode}</div>
      <div style={{ fontFamily: DISPLAY, fontSize: 190, lineHeight: 0.95, color: C.black, textTransform: 'uppercase', transform: `scale(${punch(f, fps, 12)})`, margin: '10px 60px' }}>{release}</div>
      <div style={{ ...rise(f, 20, 30), fontFamily: BODY, fontWeight: 600, fontSize: 42, color: C.black }}>{platforms}</div>
    </AbsoluteFill>
  );
};

export const Promo: React.FC<PromoProps> = (props) => {
  const f = useCurrentFrame();
  const order = [T.sting, T.newEp, T.guest, T.quote, T.social];
  const cuts = order.map((_, i) => order.slice(0, i + 1).reduce((a, b) => a + b, 0));
  // quick chalk flash on every cut
  const flash = Math.max(...cuts.map((at) => interpolate(f, [at - 2, at, at + 4], [0, 0.85, 0], clamp)));
  let at = 0; const seq = (dur: number) => { const s = at; at += dur; return { from: s, durationInFrames: dur }; };
  return (
    <AbsoluteFill style={{ background: C.black }}>
      <Sequence {...seq(T.sting)}><Sting /></Sequence>
      <Sequence {...seq(T.newEp)}><NewEp episode={props.episode} /></Sequence>
      <Sequence {...seq(T.guest)}><Guest {...props} /></Sequence>
      <Sequence {...seq(T.quote)}><Quote quote={props.quote} /></Sequence>
      <Sequence {...seq(T.social)}><Social {...props} /></Sequence>
      <Sequence {...seq(T.end)}><End {...props} /></Sequence>
      <AbsoluteFill style={{ background: C.chalk, opacity: flash * 0.8, pointerEvents: 'none' }} />
    </AbsoluteFill>
  );
};
