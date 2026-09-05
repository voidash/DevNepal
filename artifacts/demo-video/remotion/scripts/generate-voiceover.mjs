import {spawn} from 'node:child_process';
import {mkdir, unlink} from 'node:fs/promises';
import path from 'node:path';

const kalaBinary = process.env.KALA_TTS_BIN || 'uvx';
const kalaSpeaker = process.env.KALA_TTS_SPEAKER || 'kala';
const kalaSpeed = process.env.KALA_TTS_SPEED || '1.12';
const ffmpegBinary = process.env.FFMPEG_BIN || 'ffmpeg';
const usesUvx = !process.env.KALA_TTS_BIN;

const lines = [
  [
    '01-visitor.wav',
    'डेभनेपाल सार्वजनिक आवश्यकताबाट सुरु हुन्छ। आगन्तुकले साइन इन नगरी स्वीकृत सरकारी परियोजना हेर्छन्, सिभिक हेल्प डाइरेक्टरी खोल्छन् र योगदान दिनुअघि परियोजना बुझ्छन्।',
  ],
  [
    '02-ministry-create.wav',
    'मन्त्रालयका प्रकाशकले द्विभाषिक परियोजना सुरु गर्छन्, डेमो विवरण भर्नुहोस् प्रयोग गर्छन् र सिभिक हेल्प डाइरेक्टरीको वास्तविक रिपोजिटरी जोड्छन्। प्रकाशनअघि सबै विवरण समीक्षा गरिन्छ।',
  ],
  [
    '03-github-proof.wav',
    'यो ब्रेभमा खुलेको वास्तविक रिपोजिटरी हो। इश्यू नम्बर एघार गिटहबमै सिर्जना गरिएको हो। छलफल, जिम्मेवारी र कोडको आधिकारिक स्रोत गिटहब नै रहन्छ।',
  ],
  [
    '04-visitor-issue-profile.wav',
    'सिङ्क भएपछि इश्यू नम्बर एघार डेभनेपालमा उद्देश्य र स्वीकृति मापदण्डसहित देखिन्छ। आगन्तुक सुरक्षित रूपमा गिटहबमा जान सक्छन्। प्रोफाइलमा सार्वजनिक गिटहब जानकारी मात्र देखिन्छ।',
  ],
  [
    '05-ministry-activity.wav',
    'यही जडानबाट मन्त्रालयले चार खुला इश्यू, पुल रिक्वेस्ट नम्बर दस र सार्वजनिक योगदानकर्ता सारांश देख्छ। डेभनेपालले अधुरो कामलाई प्रमाणित नभनी वास्तविक रिपोजिटरी गतिविधि देखाउँछ।',
  ],
];

const outputDirectory = path.resolve('public/voice');
await mkdir(outputDirectory, {recursive: true});

const run = (command, commandArguments, label) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, commandArguments, {
      stdio: ['ignore', 'inherit', 'inherit'],
    });

    child.once('error', (error) => {
      reject(new Error(`Unable to start ${label}`, {cause: error}));
    });
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(
        new Error(
          `${label} failed: ${signal ? `signal ${signal}` : `exit ${code}`}`,
        ),
      );
    });
  });

for (const [filename, text] of lines) {
  const outputPath = path.join(outputDirectory, filename);
  const rawPath = path.join(outputDirectory, `.${filename}.raw.wav`);
  try {
    await run(
      kalaBinary,
      [
        ...(usesUvx ? ['--from', 'kala-tts', 'kala-tts'] : []),
        text,
        '--speaker',
        kalaSpeaker,
        '--speed',
        kalaSpeed,
        '--out',
        rawPath,
      ],
      `Kala TTS for ${filename}`,
    );
    await run(
      ffmpegBinary,
      [
        '-y',
        '-loglevel',
        'error',
        '-i',
        rawPath,
        '-af',
        'loudnorm=I=-16:TP=-2:LRA=7',
        '-ar',
        '48000',
        '-ac',
        '1',
        outputPath,
      ],
      `audio normalization for ${filename}`,
    );
  } finally {
    try {
      await unlink(rawPath);
    } catch (error) {
      if (error?.code !== 'ENOENT') {
        throw new Error(`Unable to remove temporary narration for ${filename}`, {
          cause: error,
        });
      }
    }
  }
}
