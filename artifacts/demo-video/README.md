# DevNepal GitHub-first demo video

The Playwright source recordings show the live Django application and the real
`voidash/civic-help-directory` repository. The Remotion composition adds role
labels, scene titles, captions, and ElevenLabs narration.

The current captioned preview is `DevNepal-GitHub-flow-preview.mp4`.

To create the narrated delivery:

1. Export `ELEVENLABS_API_KEY` (and optionally `ELEVENLABS_VOICE_ID`).
2. Run `node scripts/generate-voiceover.mjs` from `remotion/`.
3. Run `npm run render` from `remotion/`.

The narration generator fails explicitly when the ElevenLabs key is absent; it
does not substitute another speech engine.
