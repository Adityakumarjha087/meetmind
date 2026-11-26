# Engineering decisions & scope notes

This file records the trade-offs behind MeetMind, including where scope was cut (depth, never
correctness) and what is known to be limited.

## 1. Pluggable speech pipeline with offline defaults

| Stage | Default (no keys, no downloads) | Production options |
|---|---|---|
| Normalise | FFmpeg → 16 kHz mono PCM, high-pass + EBU R128 loudnorm. Pure-Python WAV fallback when FFmpeg is absent (unit tests / CI) | same |
| Speech-to-text | `sidecar`: uses an uploaded transcript (JSON/SRT/VTT/TXT) or a SHA-256-keyed fixture; otherwise VAD-derived placeholder segments, clearly labelled | `faster_whisper` (`uv sync --extra ml`), `openai_whisper` |
| Diarization | `spectral`: energy VAD → 2 s windows → log-mel mean/std + autocorrelation F0 → average-linkage clustering | `pyannote` (`speaker-diarization-3.1`, needs `HF_TOKEN`) |
| Insights | `offline`: rule-based extraction + TF-IDF summary + lexicon sentiment | `anthropic` (default model `claude-opus-5-5`), `openai`, `gemini`, `ollama` |
| Embeddings | `hashing`: signed feature hashing (uni+bigrams), 384-d, L2-normalised | `openai` (`text-embedding-3-small`, 384-d) |

Why: the brief requires the whole system (tests, CI, docker smoke test) to run with zero
secrets. Every backend sits behind a small `Protocol` (`Transcriber`, `Diarizer`, `ChatModel`,
`Embedder`) and is chosen by env var, so swapping in Whisper/pyannote/Claude is configuration.

**Honest limitation:** the offline STT backend does not recognise speech. A browser recording
uploaded without a transcript yields placeholder segments (correct timings and speakers, no
words), so its summary is minimal. Real transcription requires `STT_BACKEND=faster_whisper`
(not exercised in CI because it downloads models).

### Diarizer calibration
The spectral diarizer's two hyper-parameters were tuned on the bundled data (`ml/scripts/eval_diarization.py`,
plus 1/2/4/5-speaker synthetic sets):
- pitch is kept on an **absolute** log-F0 scale (×80) while spectral features are z-scored; an earlier
  fully z-scored version lost a speaker in 4-speaker meetings because standardisation shrinks
  pitch gaps as speakers are added;
- the merge threshold (2.2) sits in the middle of the range (2.0-2.4) where every set gets the right
  speaker count.

Result on the `say`-voiced demo meeting: **DER 1.65 %** (0 % confusion, 1.6 % false alarm from VAD
padding), 0.003× real time. This is a small, partly synthetic benchmark: expect materially worse
numbers on real far-field audio with overlapping speech, which is exactly what pyannote is for.

## 2. LLM integration
- One `ChatModel.complete(system, prompt, json_schema)` interface; `LLMEngine` builds prompts and
  validates output with Pydantic, repairing once on invalid JSON and dropping individually
  malformed items instead of failing the meeting.
- Anthropic uses the official SDK (`anthropic` 2.x on `httpx2`), structured outputs via
  `output_config.format`, `effort: medium`, and server-side refusal fallback (`fallbacks="default"`).
  No `thinking` parameter is sent (Opus 5.5 always uses adaptive thinking).
- Prompt injection: transcripts are wrapped in `<transcript>` tags, delimiter look-alikes inside
  the transcript are neutralised, and the system prompt declares the content untrusted. Output is
  schema-constrained, so an injected instruction cannot change the response shape. Slack output
  escapes `<`, `>` and `&` so transcript text cannot ping `<!channel>` or smuggle links.
- Failure policy: provider errors/timeouts (`LLM_TIMEOUT_S`) raise `LLMError`; with
  `LLM_FALLBACK_OFFLINE=true` (default) the pipeline and `/ask` degrade to the offline engine and
  say so (`engine: "offline (fallback)"`), otherwise the meeting is marked failed / `/ask` returns 502.
- **Long meetings:** recordings longer than `LONG_MEETING_THRESHOLD_S` (1 h) are split into ~10-minute
  windows (map), each analysed independently, then merged (reduce) with de-duplication.
  The map step is sequential; parallelising it is a straightforward follow-up.

## 3. Reliability
- **At-most-one active run per meeting:** the pipeline claims a meeting with a conditional
  `UPDATE … WHERE status IN (queued, failed) OR (processing AND updated_at < now - stale)`
  and stamps a `pipeline_run_id`. Every later write re-checks ownership; a superseded run stops
  silently. Concurrent duplicate deliveries are therefore harmless (tested with 4 threads).
- **Crash recovery:** every stage bumps `updated_at` (heartbeat). On worker start (Celery
  `worker_ready`) and API start in inline mode, meetings stuck in `processing` beyond
  `PIPELINE_STALE_AFTER_S` are re-queued. Celery runs with `acks_late` and a Redis visibility
  timeout above the stale window, so a job whose worker dies is redelivered. Users can also hit
  *Reprocess* on a stale meeting.
- Progress is persisted on the meeting row and pushed over Socket.IO (Redis pub/sub between the
  worker and API). The UI also polls while a meeting is processing, so a blocked websocket only
  costs latency.

## 4. Security
- Access tokens (15 min) in memory on the client; refresh tokens (14 d) in an httpOnly,
  `SameSite=Lax` cookie scoped to `/api/v1/auth`, stored server-side hashed by `jti`, rotated on
  every use, with **reuse detection** that revokes the whole token family.
- Audio is streamed through the API with short-lived, meeting-bound *media* tokens (media
  elements cannot send headers); a media token is rejected as an access token.
- Workspace RBAC (viewer < member < admin < owner). Resources outside the caller's workspaces
  return **404**, not 403, so IDs cannot be probed. Last-owner protections.
- Share links: 192-bit random tokens, expiring (default 30 days, 410 after expiry), revocable.
- Rate limiting: fixed window per IP and route class, Redis-backed (shared across replicas) with
  an in-process fallback if Redis is down.
- Security headers on every API response (CSP `default-src 'none'`, `nosniff`, `DENY` framing);
  Next.js sets its own. CORS is an explicit allow-list (wildcard rejected in production).
- Startup validation: production refuses the dev JWT secret; a selected LLM/S3 backend without
  its credentials fails fast.
- Logs are structured JSON with a redaction processor for password/token/secret/webhook keys.
- Slack webhooks must be `https` on an allow-listed host (SSRF guard).

## 5. Data & search
- PostgreSQL + pgvector (HNSW, cosine) in deployment; tests use SQLite with a portable
  `EmbeddingVector` type (JSON + NumPy cosine), keeping the 160-test suite fast and dependency-free.
  CI additionally runs migrations and the seed against real Postgres + pgvector.
- Retrieval units are ~60-word windows of consecutive segments with one-line overlap, carrying
  start/end timestamps and speakers, so every RAG citation deep-links to a moment in the audio.

## 6. Scope cuts (depth, not correctness)
- **Google Calendar** import is implemented (OAuth with calendar.readonly, token refresh,
  idempotent import of timed events) and tested against mocked Google endpoints only — no real
  Google credentials were available.
- **Slack** posting is tested against a mocked webhook only; the live smoke test verifies the
  "not configured" path.
- **Google OAuth login** is implemented and tested with mocks; not exercised against Google.
- No email invitations: members must already have an account to be added.
- The offline sentiment model is a lexicon; it is a baseline, not a claim of accuracy.
- Waveform peaks are precomputed server-side (800 buckets) so long recordings render instantly;
  the client does not decode audio.
- shadcn/ui components were written by hand in the shadcn style (Radix + CVA + tailwind-merge)
  rather than via the CLI.
