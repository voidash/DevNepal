# DevNepal GitHub-first demo video

The Playwright source recordings show the live Django application and the real
`voidash/civic-help-directory` repository. They are captured with Brave through
Playwright's Chromium API. The Remotion composition adds role labels, scene
titles, captions, and Nepali Kala TTS narration.

The short narrated delivery is `DevNepal-GitHub-flow-demo.mp4`. The complete
presentation cut is `DevNepal-20-minute-Nepali-demo.mp4`; it is exactly 20:00
at 30 frames per second and uses ten deliberately paced chapters.

The validated flow covers anonymous discovery, ministry project setup, live
GitHub issue #11, the refreshed public issue snapshot, a GitHub-only contributor
profile, and the ministry view of four issues, PR #10, and repository activity.
The issue is created through the authenticated GitHub CLI because attaching
automation to a personal Brave profile would expose browser credentials; Brave
records the resulting canonical GitHub page.

To refresh the Brave recordings, run `npm run record:brave` from `remotion/`.
The publisher-triggered GitHub refresh is recorded separately with
`npm run record:refresh`. It performs a real GitHub App refresh against the
prepared Django server, so it changes the snapshot timestamp and adds an audit
event. `npm run capture:long` captures the desktop, GitHub, publisher, and
390-pixel mobile proof frames used by the long cut.

To create the narrated delivery with Kala TTS:

1. Run `npm run voice:kala` from `remotion/`. It uses
   `uvx --from kala-tts` and the `kala` speaker by default.
2. Run `npm run render` from `remotion/`.

Set `KALA_TTS_BIN`, `KALA_TTS_SPEAKER`, or `KALA_TTS_SPEED` to override the
runtime, speaker, or pace. The generator fails explicitly if synthesis fails.
Kala TTS code is MIT licensed; the model and voice data are CC-BY-SA 4.0.

To regenerate the complete presentation:

1. Start the prepared branch on `http://127.0.0.1:9997` with the GitHub App
   environment loaded.
2. Run `npm run record:refresh`; the script keeps both the source recording and
   the Remotion public copy in sync.
3. Run `npm run capture:long`.
4. Run `npm run voice:long`.
5. Run `npm run render:long`.

The long narration says “timestamped synchronized snapshot,” not “real-time
stream.” Visitor page loads never call GitHub. Only the authorized publisher
POST invokes the bounded refresh, which keeps public traffic fast and preserves
the last good snapshot if GitHub is unavailable.
