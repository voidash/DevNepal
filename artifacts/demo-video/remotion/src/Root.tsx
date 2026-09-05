import {Composition} from 'remotion';

import {DemoVideo, TOTAL_FRAMES} from './DemoVideo';
import {LongDemoVideo, LONG_TOTAL_FRAMES} from './LongDemoVideo';

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="DevNepalNarrated"
        component={DemoVideo}
        durationInFrames={TOTAL_FRAMES}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{withAudio: true}}
      />
      <Composition
        id="DevNepalSilent"
        component={DemoVideo}
        durationInFrames={TOTAL_FRAMES}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{withAudio: false}}
      />
      <Composition
        id="DevNepal20MinuteNepali"
        component={LongDemoVideo}
        durationInFrames={LONG_TOTAL_FRAMES}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
