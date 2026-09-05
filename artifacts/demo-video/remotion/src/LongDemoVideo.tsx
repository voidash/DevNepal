import {Audio, Video} from '@remotion/media';
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';

const FPS = 30;

type Media = {
  kind: 'image' | 'video';
  source: string;
  mobile?: boolean;
  playbackRate?: number;
};

type LongScene = {
  seconds: number;
  chapter: string;
  role: string;
  title: string;
  summary: string;
  proof: string[];
  audio: string;
  audioPlaybackRate: number;
  media: Media[];
};

const scenes: LongScene[] = [
  {
    seconds: 75,
    chapter: '01 / 10',
    role: 'VISITOR · NO ACCOUNT',
    title: 'Start with a public need',
    summary: 'The first screen explains what can be contributed, who owns it, and where to begin.',
    proof: ['No sign-in wall', 'Bilingual discovery', 'Official ownership visible'],
    audio: 'voice-long/01-public-entry.mp3',
    audioPlaybackRate: 1,
    media: [{kind: 'image', source: 'long/01-home-ne.png'}],
  },
  {
    seconds: 120,
    chapter: '02 / 10',
    role: 'VISITOR · PROJECT DISCOVERY',
    title: 'Choose work with enough context',
    summary: 'Government listings stay concise while exposing responsibility, contribution mode, and next steps.',
    proof: ['Approved government listings', 'Legible dummy data', 'Direct route to project detail'],
    audio: 'voice-long/02-project-discovery.mp3',
    audioPlaybackRate: 1,
    media: [
      {kind: 'image', source: 'long/02-project-list-ne.png'},
      {kind: 'image', source: 'long/03-project-top-ne.png'},
    ],
  },
  {
    seconds: 195,
    chapter: '03 / 10',
    role: 'VISITOR · GITHUB SNAPSHOT',
    title: 'Read the project and its current work',
    summary: 'A timestamped GitHub snapshot brings open issues, pull requests, and contributors into one public page.',
    proof: ['4 open issues', 'PR #10 visible', 'Contributor activity visible'],
    audio: 'voice-long/03-project-github.mp3',
    audioPlaybackRate: 1,
    media: [
      {kind: 'image', source: 'long/03-project-top-ne.png'},
      {kind: 'image', source: 'long/03-project-issues-ne.png'},
      {kind: 'image', source: 'long/03-project-contributors-ne.png'},
    ],
  },
  {
    seconds: 135,
    chapter: '04 / 10',
    role: 'VISITOR · ISSUE HANDOFF',
    title: 'Understand the issue before opening GitHub',
    summary: 'DevNepal explains the work; GitHub remains the source of truth for discussion, assignment, and code.',
    proof: ['Full issue body', 'Acceptance criteria', 'Direct GitHub source link'],
    audio: 'voice-long/04-issue-handoff.mp3',
    audioPlaybackRate: 1,
    media: [
      {kind: 'image', source: 'long/04-issue-devnepal-ne.png'},
      {kind: 'image', source: 'long/04-issue-github.png'},
    ],
  },
  {
    seconds: 90,
    chapter: '05 / 10',
    role: 'VISITOR · GITHUB IDENTITY',
    title: 'Use a public GitHub profile—not another résumé',
    summary: 'The contributor view is a cached public GitHub identity tied to visible repository activity.',
    proof: ['Public fields only', 'Repository activity', 'More community profiles'],
    audio: 'voice-long/05-public-profile.mp3',
    audioPlaybackRate: 1,
    media: [{kind: 'image', source: 'long/05-profile-ne.png'}],
  },
  {
    seconds: 165,
    chapter: '06 / 10',
    role: 'MINISTRY PUBLISHER · CREATE',
    title: 'Create a bilingual project around a real repository',
    summary: 'The demo helper fills realistic details, but the publisher still reviews the repository and contribution contract.',
    proof: ['Small demo-fill helper', 'English + Nepali fields', 'Real public repository URL'],
    audio: 'voice-long/06-ministry-create.mp3',
    audioPlaybackRate: 1,
    media: [
      {kind: 'image', source: 'long/06-authoring-dashboard.png'},
      {kind: 'image', source: 'long/06-create-filled-top.png'},
      {kind: 'image', source: 'long/06-create-filled-repository.png'},
    ],
  },
  {
    seconds: 135,
    chapter: '07 / 10',
    role: 'MINISTRY PUBLISHER · LIVE REFRESH',
    title: 'Refresh GitHub activity from the workspace',
    summary: 'One permission-checked POST refreshes the bounded public snapshot and records a new synchronization time.',
    proof: ['CSRF + MFA protected', 'Repository-wide cooldown', 'Last good snapshot preserved on failure'],
    audio: 'voice-long/07-live-refresh.mp3',
    audioPlaybackRate: 1.02,
    media: [
      {kind: 'video', source: 'videos/06-live-github-refresh.webm', playbackRate: 0.72},
      {kind: 'image', source: 'long/07-workspace-refreshed.png'},
      {kind: 'image', source: 'long/07-workspace-contributors.png'},
    ],
  },
  {
    seconds: 105,
    chapter: '08 / 10',
    role: 'PROOF · LIVE GITHUB',
    title: 'Verify the same work at its source',
    summary: 'Issue #11 and pull request #10 remain visible in the real civic-help-directory repository.',
    proof: ['Issue #11 open', 'PR #10 open', 'No duplicated code workflow'],
    audio: 'voice-long/08-github-proof.mp3',
    audioPlaybackRate: 1,
    media: [
      {kind: 'image', source: 'long/08-github-issues.png'},
      {kind: 'image', source: 'long/08-github-prs.png'},
    ],
  },
  {
    seconds: 90,
    chapter: '09 / 10',
    role: 'MOBILE · NEPALI',
    title: 'Keep the same flow on a small screen',
    summary: 'Navigation, project context, and issue discovery remain usable at a 390-pixel mobile viewport.',
    proof: ['No horizontal overflow', 'Nepali navigation', 'Issues remain reachable'],
    audio: 'voice-long/09-mobile-nepali.mp3',
    audioPlaybackRate: 1,
    media: [
      {kind: 'image', source: 'long/09-mobile-home.png', mobile: true},
      {kind: 'image', source: 'long/09-mobile-project.png', mobile: true},
      {kind: 'image', source: 'long/09-mobile-issues.png', mobile: true},
    ],
  },
  {
    seconds: 90,
    chapter: '10 / 10',
    role: 'VALIDATED CLOSE',
    title: 'A narrow, complete contribution loop',
    summary: 'Discover in DevNepal, collaborate in GitHub, and let the ministry monitor a timestamped public projection.',
    proof: ['Visitor-first', 'GitHub-first', 'Publisher-verifiable'],
    audio: 'voice-long/10-resilience-close.mp3',
    audioPlaybackRate: 1.01,
    media: [
      {kind: 'image', source: 'long/03-project-top-ne.png'},
      {kind: 'image', source: 'long/07-workspace-refreshed.png'},
    ],
  },
];

export const LONG_TOTAL_FRAMES = scenes.reduce((sum, scene) => sum + scene.seconds * FPS, 0);

const BrowserFrame = ({media, sceneFrame}: {media: Media; sceneFrame: number}) => {
  const scale = interpolate(sceneFrame, [0, 1800], [1, 1.025], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.quad),
  });
  if (media.mobile) {
    return (
      <div
        style={{
          width: 438,
          height: 820,
          margin: '0 auto',
          border: '3px solid #111827',
          borderRadius: 34,
          background: '#111827',
          padding: '18px 22px',
          boxShadow: '14px 14px 0 #bfdc79',
          overflow: 'hidden',
        }}
      >
        <Img
          src={staticFile(media.source)}
          style={{width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top'}}
        />
      </div>
    );
  }
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        background: '#fff',
      }}
    >
      {media.kind === 'video' ? (
        <Video
          src={staticFile(media.source)}
          muted
          playbackRate={media.playbackRate ?? 1}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      ) : (
        <Img
          src={staticFile(media.source)}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            transform: `scale(${scale})`,
          }}
        />
      )}
    </div>
  );
};

const LongSceneCard = ({scene, index}: {scene: LongScene; index: number}) => {
  const frame = useCurrentFrame();
  const duration = scene.seconds * FPS;
  const mediaLength = Math.ceil(duration / scene.media.length);
  const mediaIndex = Math.min(scene.media.length - 1, Math.floor(frame / mediaLength));
  const localMediaFrame = frame - mediaIndex * mediaLength;
  const fade = interpolate(localMediaFrame, [0, 14], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const intro = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  const totalElapsed = scenes.slice(0, index).reduce((sum, item) => sum + item.seconds, 0);

  return (
    <AbsoluteFill style={{background: '#e9e9e6', color: '#111827'}}>
      <div
        style={{
          position: 'absolute',
          left: 64,
          top: 54,
          width: scene.media[mediaIndex].mobile ? 520 : 1250,
          height: 820,
          border: scene.media[mediaIndex].mobile ? 'none' : '2px solid #111827',
          background: '#fff',
          boxShadow: scene.media[mediaIndex].mobile ? 'none' : '14px 14px 0 #111827',
          opacity: fade,
        }}
      >
        <BrowserFrame media={scene.media[mediaIndex]} sceneFrame={localMediaFrame} />
      </div>
      <aside
        style={{
          position: 'absolute',
          right: 64,
          top: 54,
          width: scene.media[mediaIndex].mobile ? 1190 : 500,
          height: 820,
          padding: '42px 38px',
          boxSizing: 'border-box',
          background: '#111827',
          color: '#fff',
          border: '2px solid #111827',
          opacity: intro,
          transform: `translateX(${(1 - intro) * 24}px)`,
          fontFamily: 'Arial, sans-serif',
        }}
      >
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <span style={{color: '#d9f99d', fontSize: 21, fontWeight: 800, letterSpacing: 1.1}}>
            {scene.chapter}
          </span>
          <span style={{fontSize: 18, color: '#cbd5e1', minWidth: 72, textAlign: 'right'}}>
            {Math.floor(totalElapsed / 60)}:{String(totalElapsed % 60).padStart(2, '0')}
          </span>
        </div>
        <p style={{margin: '54px 0 18px', color: '#d9f99d', fontSize: 19, fontWeight: 800}}>
          {scene.role}
        </p>
        <h1 style={{margin: 0, fontSize: 46, lineHeight: 1.05, letterSpacing: -1.2}}>
          {scene.title}
        </h1>
        <p style={{margin: '30px 0 34px', color: '#e5e7eb', fontSize: 25, lineHeight: 1.45}}>
          {scene.summary}
        </p>
        <div style={{height: 2, background: '#334155', marginBottom: 30}} />
        {scene.proof.map((item) => (
          <div
            key={item}
            style={{
              display: 'flex',
              gap: 13,
              alignItems: 'center',
              margin: '20px 0',
              fontSize: 23,
            }}
          >
            <span style={{width: 13, height: 13, background: '#d9f99d', flex: '0 0 auto'}} />
            {item}
          </div>
        ))}
      </aside>
      <div
        style={{
          position: 'absolute',
          left: 64,
          right: 64,
          bottom: 28,
          height: 7,
          background: '#cbd5e1',
        }}
      >
        <div
          style={{
            width: `${((totalElapsed * FPS + frame) / LONG_TOTAL_FRAMES) * 100}%`,
            height: '100%',
            background: '#315b7d',
          }}
        />
      </div>
      <Audio src={staticFile(scene.audio)} volume={0.88} playbackRate={scene.audioPlaybackRate} />
    </AbsoluteFill>
  );
};

export const LongDemoVideo = () => {
  let from = 0;
  return (
    <AbsoluteFill>
      {scenes.map((scene, index) => {
        const sceneFrom = from;
        const duration = scene.seconds * FPS;
        from += duration;
        return (
          <Sequence
            key={scene.chapter}
            from={sceneFrom}
            durationInFrames={duration}
            premountFor={FPS}
          >
            <LongSceneCard scene={scene} index={index} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
