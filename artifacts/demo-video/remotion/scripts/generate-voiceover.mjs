import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';

const apiKey = process.env.ELEVENLABS_API_KEY;

if (!apiKey) {
  throw new Error('ELEVENLABS_API_KEY is required to generate the demo narration.');
}

const voiceId = process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8ikWAM';
const lines = [
  ['01-visitor.mp3', 'DevNepal starts with the public need. Visitors browse approved government projects without signing in. Civic Help Directory is published by the Department of Information Technology and linked to a real public repository.'],
  ['02-ministry-create.mp3', 'A ministry publisher starts a government project and uses Fill demo details for bilingual content, the approved licence, and the Civic Help Directory repository. The publisher still reviews every field before saving.'],
  ['03-github-proof.mp3', 'The connected repository is voidash slash civic-help-directory. Its issues and pull requests remain on GitHub, while DevNepal makes them discoverable in a government project context.'],
  ['04-visitor-issue-profile.mp3', 'Visitors see open issues synchronized from GitHub inside DevNepal. Issue seven includes its complete goal and acceptance criteria, then links to the original GitHub issue. Contributor profiles show only cached public GitHub information.'],
  ['05-ministry-activity.mp3', 'The ministry workspace uses the same connection to show three open issues, pull request ten, and nine commits from at voidash. Open pull requests stay marked as work in progress. Merged work can then enter contribution verification.'],
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
