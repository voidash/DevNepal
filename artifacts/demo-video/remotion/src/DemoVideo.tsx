import {Audio, Video} from '@remotion/media';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';

const FPS = 30;

type Scene = {
  duration: number;
  playbackRate: number;
  eyebrow: string;
  title: string;
  caption: string;
  video: string;
  audio: string;
};

const scenes: Scene[] = [
  {
    duration: 390,
    playbackRate: 0.87,
    eyebrow: 'VISITOR · NO ACCOUNT REQUIRED',
    title: 'Find public work worth contributing to',
    caption:
      'Visitors browse approved government work without an account, choose Civic Help Directory, and see the public need before deciding whether to contribute.',
    video: 'videos/01-visitor.webm',
    audio: 'voice/01-visitor.wav',
  },
  {
    duration: 420,
    playbackRate: 0.79,
    eyebrow: 'MINISTRY PUBLISHER · REVIEW BEFORE SAVE',
    title: 'Create a project and connect GitHub',
    caption:
      'A ministry publisher starts a bilingual project, uses the small demo-fill helper, and connects the real Civic Help Directory repository before review and publication.',
    video: 'videos/02-ministry-create.webm',
    audio: 'voice/02-ministry-create.wav',
  },
  {
    duration: 420,
    playbackRate: 0.94,
    eyebrow: 'LIVE GITHUB · RECORDED IN BRAVE',
    title: 'Create the issue where the work lives',
    caption:
      'Issue #11 was created in the live voidash/civic-help-directory repository. GitHub remains the source of truth for discussion, assignment, and code.',
    video: 'videos/03-github-proof.webm',
    audio: 'voice/03-github-proof.wav',
  },
  {
    duration: 480,
    playbackRate: 0.92,
    eyebrow: 'VISITOR · ISSUES AND PUBLIC GITHUB PROFILE',
    title: 'Understand the issue before leaving DevNepal',
    caption:
      'After synchronization, issue #11 appears inside DevNepal with its complete goal and acceptance criteria, a safe GitHub handoff, and a public GitHub-only contributor profile.',
    video: 'videos/04-visitor-issue-profile.webm',
    audio: 'voice/04-visitor-issue-profile.wav',
  },
  {
    duration: 420,
    playbackRate: 0.81,
    eyebrow: 'MINISTRY · REPOSITORY ACTIVITY',
    title: 'See issues, pull requests, and contributors',
    caption:
      'The ministry workspace now shows four open issues, pull request #10, and the public contributor snapshot. It reports activity without pretending that open work is verified.',
    video: 'videos/05-ministry-activity.webm',
    audio: 'voice/05-ministry-activity.wav',
  },
];

export const TOTAL_FRAMES = scenes.reduce((sum, scene) => sum + scene.duration, 0);

const SceneCard = ({scene, withAudio}: {scene: Scene; withAudio: boolean}) => {
  const frame = useCurrentFrame();
  const intro = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  return (
    <AbsoluteFill style={{backgroundColor: '#e9e9e6', color: '#111827'}}>
      <div
        style={{
          position: 'absolute',
          inset: '54px 80px 178px',
          border: '2px solid #151515',
          background: '#fff',
          boxShadow: '16px 16px 0 #151515',
          overflow: 'hidden',
        }}
      >
        <Video
          src={staticFile(scene.video)}
          muted
          playbackRate={scene.playbackRate}
          objectFit="cover"
          style={{width: '100%', height: '100%'}}
        />
      </div>
      <div
        style={{
          position: 'absolute',
          left: 80,
          top: 22,
          padding: '8px 14px',
          background: '#d9f99d',
          border: '2px solid #151515',
          fontFamily: 'Arial, sans-serif',
          fontSize: 20,
          fontWeight: 800,
          letterSpacing: 1.2,
          opacity: intro,
          transform: `translateY(${(1 - intro) * -16}px)`,
        }}
      >
        {scene.eyebrow}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 80,
          right: 80,
          bottom: 34,
          minHeight: 118,
          display: 'grid',
          gridTemplateColumns: '520px 1fr',
          gap: 38,
          alignItems: 'center',
          padding: '22px 28px',
          background: '#111827',
          border: '2px solid #111827',
          color: '#fff',
          fontFamily: 'Arial, sans-serif',
          opacity: intro,
        }}
      >
        <div style={{fontSize: 30, lineHeight: 1.08, fontWeight: 850}}>{scene.title}</div>
        <div style={{fontSize: 23, lineHeight: 1.4, color: '#f3f4f6'}}>{scene.caption}</div>
      </div>
      {withAudio ? <Audio src={staticFile(scene.audio)} volume={0.82} /> : null}
    </AbsoluteFill>
  );
};

export const DemoVideo = ({withAudio}: {withAudio: boolean}) => {
  let from = 0;

  return (
    <AbsoluteFill>
      {scenes.map((scene) => {
        const sceneFrom = from;
        from += scene.duration;
        return (
          <Sequence key={scene.video} from={sceneFrom} durationInFrames={scene.duration} premountFor={30}>
            <SceneCard scene={scene} withAudio={withAudio} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
