import {spawn} from 'node:child_process';
import {mkdir} from 'node:fs/promises';
import path from 'node:path';

const piperBinary = process.env.PIPER_BIN || 'piper';
const piperModel = process.env.PIPER_MODEL;

if (!piperModel) {
  throw new Error(
    'PIPER_MODEL must point to a Piper .onnx voice model. See artifacts/demo-video/README.md.',
  );
}

const lines = [
  ['01-visitor.wav', 'Dev Nepal starts with the public need. Without creating an account, a visitor browses approved government work, opens Civic Help Directory, and understands the project before choosing to contribute.'],
  ['02-ministry-create.wav', 'A ministry publisher starts a bilingual project, uses the small demo fill helper, and connects the real Civic Help Directory repository. The ministry still reviews the details before publication.'],
  ['03-github-proof.wav', 'Here is the live repository in Brave. Issue eleven was created on GitHub, the source of truth for discussion, assignment, and code, then synchronized into Dev Nepal.'],
  ['04-visitor-issue-profile.wav', 'After synchronization, issue eleven appears inside Dev Nepal with its complete goal and acceptance criteria. The visitor gets a safe GitHub handoff, while the contributor page uses only public GitHub information.'],
  ['05-ministry-activity.wav', 'The same connection lets the ministry see four open issues, pull request ten, and the public contributor snapshot. Dev Nepal reports repository activity without pretending that unfinished work has been verified.'],
];

const outputDirectory = path.resolve('public/voice');
await mkdir(outputDirectory, {recursive: true});

const synthesize = (filename, text) =>
  new Promise((resolve, reject) => {
    const outputPath = path.join(outputDirectory, filename);
    const child = spawn(
      piperBinary,
      [
        '--model',
        piperModel,
        '--output_file',
        outputPath,
        '--length-scale',
        '0.92',
        '--sentence-silence',
        '0.16',
      ],
      {stdio: ['pipe', 'inherit', 'inherit']},
    );

    child.once('error', (error) => {
      reject(new Error(`Unable to start Piper for ${filename}`, {cause: error}));
    });
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(
        new Error(
          `Piper failed for ${filename}: ${signal ? `signal ${signal}` : `exit ${code}`}`,
        ),
      );
    });
    child.stdin.on('error', (error) => {
      reject(new Error(`Unable to send narration text to Piper for ${filename}`, {cause: error}));
    });
    child.stdin.end(`${text}\n`);
  });

for (const [filename, text] of lines) {
  await synthesize(filename, text);
}
