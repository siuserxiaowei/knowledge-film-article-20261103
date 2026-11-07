import {Composition} from 'remotion';
import {Film} from './Film';
import timelineJson from './generated/timeline.json';
import type {FilmTimeline} from './types';

const timeline = timelineJson as FilmTimeline;

export const Root = () => <Composition
  id="KnowledgeFilm"
  component={Film}
  fps={timeline.fps || 30}
  width={timeline.width || 1920}
  height={timeline.height || 1080}
  durationInFrames={Math.max(1,timeline.durationInFrames || 90)}
/>;
