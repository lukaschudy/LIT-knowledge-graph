# Ask Atlas microphone dictation

The public Ask Atlas microphone records a question and puts the transcript into the editable draft. Open the chat, tap the microphone, allow browser microphone access, speak, and tap again to stop. Review the words, especially gene/variant notation, before pressing Send. Enter while recording stops capture without submitting the previous draft. Dictation replaces the untouched demo suggestion; it appends to a user-written draft and retains edits made while transcription runs.

## Hosted path

`getUserMedia → MediaRecorder → same-origin POST /api/voice/transcribe → Cloudflare Workers AI Whisper → editable draft`

The provider is Cloudflare's hosted OpenAI model `@cf/openai/whisper-large-v3-turbo`. It uses the Worker's `AI` binding; no model credentials are exposed in the browser and no connection to the developer's computer is required. This is speech transcription, not a change to the deterministic GRIN answer engine. Audio is sent to Cloudflare for processing. Atlas does not save recordings or put them in the proposal inbox; only a user-submitted question enters the normal Ask Atlas flow.

The interface supports 60-second recordings, WebM/Opus, Ogg/Opus or MP4 depending on browser support. The endpoint also accepts WAV for verification. Uploads are capped at 4 MiB while streaming; the recording-duration limit is enforced by the browser, not by a server audio decoder. Requests require the same Origin and an allowed audio content type. Anonymous requests are throttled to 10 per minute per IP per Cloudflare location. This is an abuse guard, not a strict global spending cap. Server transcription waits up to 90 seconds; the client times out after 120 seconds. Cancellation aborts the client request and discards late results; an already-started provider job may still finish.

Closing the chat, cancellation and leaving the page release microphone tracks. Permission denial, silence and provider failures preserve the draft and offer a retry. Hiding the tab stops recording. A cancelled permission request that later succeeds immediately releases its returned stream.

## Local compatibility

`GET /api/voice/status` advertises the provider and whether a workspace token is required. Hosted mode sets `requires_token: false` and does not request `/api/research/state`. The separate local research backend retains its workspace token and local faster-whisper service; absence of the new flag keeps that token requirement. The hosted UI explicitly labels processing via Cloudflare instead of claiming transcription happens on the user's computer.

A local Worker preview with Workers AI can use remote inference and incur provider usage. Offline browser tests stub transcription and need no account or physical microphone.

## Verification

- Python tests cover routing, transcription payloads, same-origin checks, MIME/body validation, streamed size limits, throttling, provider failure/timeout and empty speech results.
- `NODE_PATH=<Playwright modules> node scripts/check_voice_capture.cjs` uses Chromium's fake microphone with a real MediaRecorder and a stubbed transcription response. Nine scenarios cover draft replacement/preservation, Enter-to-stop, cancellation, chat closure, late responses, silence, provider failure and denied permission.
- The broader graph/chat regression suite includes capture cleanup when permission resolves after cancellation.
- To capture an encoded synthetic speech sample for a separately authorized live provider check, pass `ATLAS_TEST_AUDIO=/absolute/synthetic.wav` and `ATLAS_CAPTURE_OUTPUT=/tmp/capture.webm` to the browser test. These are test-only environment variables; they never enable access to a physical microphone.

The deployed status and transcription endpoints were checked with synthetic WAV and browser-recorded WebM/Opus. Release evidence is in `deploy/cloudflare/voice-release.json`. Real-device microphone quality and transcription of uncommon gene names still depend on the browser, input device, pronunciation and model; users can edit before sending.

Provider references: [Whisper model and input contract](https://developers.cloudflare.com/workers-ai/models/whisper-large-v3-turbo/), [rate-limit binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).
