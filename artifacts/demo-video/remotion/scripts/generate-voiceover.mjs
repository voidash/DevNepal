import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';

const apiKey = process.env.ELEVENLABS_API_KEY;

if (!apiKey) {
  throw new Error('ELEVENLABS_API_KEY is required to generate the demo narration.');
}

const voiceId = process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8ikWAM';
const lines = [
  ['01-visitor.mp3', 'DevNepal starts with the public need. Without creating an account, a visitor browses approved government work, opens Civic Help Directory, and understands the project before choosing to contribute.'],
  ['02-ministry-create.mp3', 'A ministry publisher starts a bilingual project, uses the small demo-fill helper, and connects the real Civic Help Directory repository. The ministry still reviews the details before publication.'],
  ['03-github-proof.mp3', 'Here is the live repository in Brave. Issue eleven was created on GitHub, the source of truth for discussion, assignment, and code, then synchronized into DevNepal.'],
  ['04-visitor-issue-profile.mp3', 'After synchronization, issue eleven appears inside DevNepal with its complete goal and acceptance criteria. The visitor gets a safe GitHub handoff, while the contributor page uses only cached public GitHub information.'],
  ['05-ministry-activity.mp3', 'The same connection lets the ministry see four open issues, pull request ten, and the public contributor snapshot. DevNepal reports repository activity without pretending that unfinished work has been verified.'],
];

const outputDirectory = path.resolve('public/voice');
await mkdir(outputDirectory, {recursive: true});

for (const [filename, text] of lines) {
  const response = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'audio/mpeg',
      'xi-api-key': apiKey,
    },
    body: JSON.stringify({
      text,
      model_id: 'eleven_turbo_v2_5',
      voice_settings: {
        stability: 0.58,
        similarity_boost: 0.76,
        style: 0.18,
        use_speaker_boost: true,
        speed: 1.03,
      },
    }),
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(`ElevenLabs failed for ${filename}: ${response.status} ${details}`);
  }

  const audio = Buffer.from(await response.arrayBuffer());
  await writeFile(path.join(outputDirectory, filename), audio);
}
