import React from 'react';
import { Composition } from 'remotion';
import './brand';
import { Promo, promoSchema, DURATION } from './Promo';
import episode from '../episode.json';

// Edit episode.json (or the fields in `npm run studio`). Never invent a quote: use a real line from the episode.
export const Root: React.FC = () => (
  <Composition id="RyjPromo" component={Promo} schema={promoSchema} durationInFrames={DURATION} fps={30} width={1080} height={1920}
    defaultProps={episode} />
);
