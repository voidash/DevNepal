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
  eyebrow: string;
  title: string;
  caption: string;
  video: string;
  audio: string;
};

const scenes: Scene[] = [
  {
    duration: 515,
    eyebrow: 'VISITOR · NO ACCOUNT REQUIRED',
    title: 'Find public work worth contributing to',
    caption:
      'Visitors browse approved government projects without signing in. Civic Help Directory is published by the Department of Information Technology and linked to a real public repository.',
    video: 'videos/01-visitor.webm',
    audio: 'voice/01-visitor.mp3',
  },
  {
    duration: 514,
    eyebrow: 'MINISTRY PUBLISHER · REVIEW BEFORE SAVE',
    title: 'Create a project and connect GitHub',
    caption:
      'A ministry publisher starts a project and uses Fill demo details for bilingual content, the approved licence, and the Civic Help Directory repository. The publisher still reviews every field before saving.',
    video: 'videos/02-ministry-create.webm',
    audio: 'voice/02-ministry-create.mp3',
  },
  {
    duration: 317,
    eyebrow: 'REAL REPOSITORY · GITHUB IS THE SOURCE OF TRUTH',
    title: 'The connection points to live public work',
    caption:
      'The connected repository is voidash slash civic-help-directory. Its issues and pull requests remain on GitHub while DevNepal makes them discoverable in a government project context.',
    video: 'videos/05-github-proof.webm',
    audio: 'voice/03-github-proof.mp3',
  },
  {
    duration: 654,
    eyebrow: 'VISITOR · ISSUES AND PUBLIC GITHUB PROFILE',
    title: 'Understand the issue before leaving DevNepal',
    caption:
      'Visitors see open issues synchronized from GitHub inside DevNepal. Issue seven includes its goal and acceptance criteria, then links to GitHub. Contributor profiles contain only cached public GitHub information.',
    video: 'videos/03-visitor-issue-profile.webm',
    audio: 'voice/04-visitor-issue-profile.mp3',
  },
  {
    duration: 471,
    eyebrow: 'MINISTRY · REPOSITORY ACTIVITY',
    title: 'See issues, pull requests, and contributors',
    caption:
      'The ministry workspace shows three open issues, pull request ten, and nine commits from at voidash. Open pull requests stay work in progress; merged work can then enter contribution verification.',
    video: 'videos/04-ministry-activity.webm',
    audio: 'voice/05-ministry-activity.mp3',
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
      {withAudio ? <Audio src={staticFile(scene.audio)} volume={1} /> : null}
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
