# DevNepal GitHub-first demo video

The Playwright source recordings show the live Django application and the real
`voidash/civic-help-directory` repository. They are captured with Brave through
Playwright's Chromium API. The Remotion composition adds role labels, scene
titles, captions, and Nepali Kala TTS narration.

The current captioned preview is `DevNepal-GitHub-flow-preview.mp4`.

The validated flow covers anonymous discovery, ministry project setup, live
GitHub issue #11, the refreshed public issue snapshot, a GitHub-only contributor
profile, and the ministry view of four issues, PR #10, and repository activity.
The issue is created through the authenticated GitHub CLI because attaching
automation to a personal Brave profile would expose browser credentials; Brave
records the resulting canonical GitHub page.

To refresh the Brave recordings, run `npm run record:brave` from `remotion/`.

To create the narrated delivery with Kala TTS:

1. Run `npm run voice:kala` from `remotion/`. It uses
   `uvx --from kala-tts` and the `kala` speaker by default.
2. Run `npm run render` from `remotion/`.

Set `KALA_TTS_BIN`, `KALA_TTS_SPEAKER`, or `KALA_TTS_SPEED` to override the
runtime, speaker, or pace. The generator fails explicitly if synthesis fails.
Kala TTS code is MIT licensed; the model and voice data are CC-BY-SA 4.0.
