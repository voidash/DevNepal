import {Composition} from 'remotion';

import {DemoVideo, TOTAL_FRAMES} from './DemoVideo';

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
    </>
  );
};
