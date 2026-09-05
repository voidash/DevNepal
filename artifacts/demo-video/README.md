# DevNepal GitHub-first demo video

The Playwright source recordings show the live Django application and the real
`voidash/civic-help-directory` repository. They are captured with Brave through
Playwright's Chromium API. The Remotion composition adds role labels, scene
titles, captions, and Piper narration.

The current captioned preview is `DevNepal-GitHub-flow-preview.mp4`.

The validated flow covers anonymous discovery, ministry project setup, live
GitHub issue #11, the refreshed public issue snapshot, a GitHub-only contributor
profile, and the ministry view of four issues, PR #10, and repository activity.
The issue is created through the authenticated GitHub CLI because attaching
automation to a personal Brave profile would expose browser credentials; Brave
records the resulting canonical GitHub page.

To refresh the Brave recordings, run `npm run record:brave` from `remotion/`.

To create the narrated delivery with Piper:

1. Download a voice, for example `python -m piper.download_voices en_US-lessac-medium`.
2. Export `PIPER_BIN` and `PIPER_MODEL` with the absolute binary and `.onnx` paths.
3. Run `npm run voice:piper` from `remotion/`.
4. Run `npm run render` from `remotion/`.

The narration generator fails explicitly when the model is absent or Piper
cannot synthesize a scene.
