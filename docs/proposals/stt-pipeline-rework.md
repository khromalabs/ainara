# STT Pipeline Rework — Capture & Transport Architecture

> Reference note for the voice pipeline improvements. Graduated from local
> working notes. Based on a full audit of: `polaris/components/com-ring.js`,
> `polaris/services/stt/whisper.js`, `ainara/framework/stt/faster_whisper.py`,
> `ainara/framework/pybridge.py`, `ainara/framework/wakeword/openwakeword.py`.
>
> Status: proposed. The phased plan below is the working roadmap; see the
> GitHub tracking issue (#20) for current progress.

## 0. Goal and vision

Project motto: **"Just talk to her"**. TTS already delivers (streaming per
phrase, Kokoro on CPU, LLM streaming even with skills). STT is the missing
half for closing the Samantha-style conversational loop. Guiding principle:
everything that can run locally, runs locally (privacy by design,
sovereignty).

Current state: STT only works in a silent environment. General diagnosis:
**it is not the model, it is the capture and transport architecture.** The
proof: `faster_whisper.py` already has Silero `vad_filter`,
`condition_on_previous_text=False` and reasonable parameters — the chain
around them wastes them.

## 1. Map of the current architecture

```
[Mic + Chromium DSP (getUserMedia, flags OK)]
    → MediaRecorder (audio/webm, full recording)
    → Blob → POST /framework/stt (multipart)
    → temp file → faster-whisper → JSON {text, confidence}
    → shouldReview() → direct send or review window
```

Parallel existing paths:

- Wake word: AudioContext → JS downsample → WS /wakeword → openWakeWord → raw scores
- Legacy `listen()` in Python: PyAudio + energy VAD → temp wav → transcribe_file

## 2. Findings by module

### 2.1 com-ring.js (renderer)

- **All-or-nothing transcription on stop**: full blob with leading silence,
  pauses and tail. Latency grows with duration; silence feeds Whisper
  hallucinations.
- **MediaRecorder is a dead end for streaming**: with `start(timeslice)` only
  the first chunk carries the WebM header; the following ones are not
  decodable on their own.
- **Energy VAD only serves auto-stop** (wake word), never segments phrases.
  It sums the full spectrum: the PC fan weighs as much as the voice (if kept,
  use only bins < 4kHz).
- **`downsampleBuffer` decimates without a low-pass filter**: at rates that
  are not multiples of 16kHz it folds high-frequency noise onto the voice
  (aliasing).
- **`ScriptProcessorNode` is deprecated**, runs on the main thread.
- **No duration cap on the PTT path**: `audioChunks` grows unbounded with
  constant noise (Python `listen()` does have a 30s cap).
- DSP flags are already requested in `initializeAudioStream`
  (`echoCancellation`, `noiseSuppression`, `autoGainControl`, mono).
  **PENDING VERIFICATION**: that Chromium actually applies them on
  Linux/PipeWire (see tests §5).
- Useful existing hook: `shouldReview(text, confidence)` and
  `stt.onTranscriptionResult` are ready to receive per-phrase results.
- Bug confirmed by Rubén: the review window **replaces** the previous text
  instead of accumulating. Proposed fix: per-turn accumulator (clear per
  turn, not per phrase).

### 2.2 services/stt/whisper.js (API client)

- It is an OpenAI-compatible client; the model lives in pybridge (Python).
- `language: 'auto'` hardcoded in the formData: **misleading** (the server
  ignores it for the model). Clean up or remove.
- Unnecessary file chain: webm → temp → ffmpeg → wav → temp → server.

### 2.3 framework/stt/faster_whisper.py (pybridge)

- Language: RESOLVED — the Wizard forces `stt.language`, it is always used.
  Only pending: `initial_prompt` in English (put it in the session language).
- **Weak, biased confidence**: `min(exp(avg_logprob))` per segment. With the
  JS threshold at 0.80 this demands avg_logprob ≥ -0.223: strict. Long turns
  almost always go to review.
- **Unexploited gates**: faster-whisper applies `no_speech_threshold=0.6`,
  `compression_ratio_threshold=2.4` and `log_prob_threshold=-1.0` internally
  by default, but the code does not use that metadata for confidence or UI.
- **Bug**: empty result (VAD filters everything) returns confidence 1.0 →
  should be 0.0.
- **Latent bug**: hotwords loaded as a list; faster-whisper expects a string.
  Breaks when configuring real hotwords.
- **Context buffer (dynamic prompt)**: if garbage transcription gets in, it
  gets reinforced in a loop. Only append when confidence is above a floor.
- `cpu_threads` uses all physical cores: leave 2 free (Kokoro + LLM coexist).
- `ALLOW_GPU=False` hardcoded and VRAM detection disabled; DependencyChecker
  already knows about CUDA. Reopen when cuDNN is resolved
  (`nvidia-cudnn-cu12` pip wheels).
- Key opportunity: faster-whisper accepts **numpy float32 @16kHz directly** →
  kill the entire file chain with a `transcribe_pcm()`.

### 2.4 pybridge.py

- **Wake word fires on ONE frame** above threshold, no hysteresis, no
  confirmation. Explains the false positives ("any noise is the wake word").
- Comment says cooldown 2s, code sets 4s.
- **No reconnection**: if pybridge dies, the WS does not recover until the
  app is relaunched.
- flask_sock accepts binary and text frames interleaved → opportunity for a
  **unified audio socket**.
- `/framework/stt` (files) stays as legacy/compatibility.

### 2.5 framework/wakeword/openwakeword.py

- Custom `aye_nah_rah.onnx` model, trained with the official synthetic-voice
  (TTS) notebook, put in production directly. Customs trained on synthetic
  data are nervous with noise; the pre-trained ones (`hey_jarvis`...) carry
  far more real/augmented data.
- No VAD gate: all audio feeds the model (speex helps, does not save).
- No N-of-M: `process_chunk` returns raw scores; the N-of-M gating will be
  implemented in the socket handler (or via `threshold`/`trigger_level` of
  `predict()` if the openwakeword version is ≥ 0.5 — VERIFY version in
  requirements).
- **`model.reset()` is never called after firing**: internal state can drag
  over.
- TODO on its internal `vad_threshold`: known openWakeWord bug with
  onnxruntime (Conv shape error). Don't fight it: gate OUTSIDE with Silero.
- `download_models()` with `HF_HUB_OFFLINE=1`: fails silently, harmless.
- openWakeWord supports **verifier models** per wake word: a trainable second
  line of defense for "Ainara".

## 3. Prioritized work plan

### Phase 1 — Quick wins in faster_whisper.py (~1 afternoon)

1. Confidence gates: track `no_speech_prob > 0.6` and `compression_ratio >
   2.4` per segment; mark empty/discarded result with confidence 0.0.
2. Fix hotwords (list → string).
3. `initial_prompt` in the session language.
4. Dynamic prompt: only append transcriptions above a confidence floor
   (e.g. 0.6).
5. `cpu_threads` = cores − 2.

### Phase 2 — transcribe_pcm, kill the files (~1 afternoon)

1. `transcribe_pcm(pcm: np.float32 @16k)`: no webm, no ffmpeg, no temps.
2. Server-side resampling with soxr (client sends PCM at native rate;
   remove `downsampleBuffer` from the JS).
3. 5-minute test of Chromium DSP in PipeWire (see §5); if it does not apply,
   RNNoise filter in PipeWire as fallback.

### Phase 3 — Unified socket + phrase dictation (the big piece)

- ONE WS audio endpoint: binary frames = PCM; text frames = JSON control:
  `{"type":"mode","value":"wakeword"} | {"type":"mode","value":"dictation"} |
  {"type":"turn_end"}`
- Silero runs ALWAYS in pybridge: in wakeword mode it is a gate (phase 4); in
  dictation it does endpointing (phrase cut with min_silence 500–700ms).
- Per closed phrase: greedy `transcribe_pcm` → return
  `{type:"phrase", text, confidence}`.
- **Full turn**: dispatch to the LLM after long silence (1.5–2s) or on PTT
  release. Do NOT send each phrase as an independent message.
- **Review window = per-turn accumulator**: each phrase is APPENDED (fix of
  the replace bug); clear per turn. Weak parts highlighted (Rubén's OCR-like
  idea, applied without blocking).
- FSM refactor leveraging the constructor TODO: IDLE → LISTENING →
  ENDPOINTING → PROCESSING → SPEAKING. Replaces the soup of ~10 boolean flags
  (symptom: "not showing 2nd time").
- Known landmines in the current typing-mode web (all verified while fixing
  #19 — see `docs/design/polaris-windowing-model.md`): two sources of truth
  for typing mode (main-side flag vs renderer state) that diverge; the
  renderer component's own `isTypingMode` is never assigned (always
  `undefined`, so `typing-key-pressed` always re-enters typing mode);
  `ChatDisplayWindow.onBlur` sends a `set-typing-mode-state` event no
  renderer listens for (dead code), so typing mode persists across
  hide/show cycles; `exit-typing-mode` has multiple handlers across two
  windows with unclear ownership.
- PyAudio `listen()` and MediaRecorder become legacy; duration cap on every
  path.

### Phase 4 — Reliable wake word

1. Silero gate in front: only voice reaches the detector.
2. N-of-M confirmation: 3 of 5 frames (~400ms) above threshold (deque
   maxlen=5).
3. Semantic verification: on trigger, greedy whisper over the last 2s of
   `pcm_history` (~300ms); if the phrase does not appear normalized, cancel.
4. `model.reset()` after every firing.
5. Cooldown 4s (fix the comment) + WS reconnection logic.
6. A/B against pre-trained `hey_jarvis` + TTS self-hearing test (see §5).
7. Depending on results: retrain `aye_nah_rah` with more negatives and
   augmented noise, and/or train a verifier model.

### Phase 5 — Optional / later

- Reopen GPU: DependencyChecker + `nvidia-cudnn-cu12` wheels; large-v3
  `int8_float32` on machines with VRAM. Factory default remains CPU.
- Word-level highlighting with `word_timestamps=True` (with per-phrase
  segments, `avg_logprob` is nearly the phrase confidence already).
- Greedy per phrase + re-decode with beam 5 only if confidence is low (CPU
  economy).
- **Speaker verification layer** (candidate, not yet evaluated): enroll the
  user's voice once (speaker embedding); after capture, compare the segment's
  embedding against the enrolled voice print as a *reliability signal*, never
  a gatekeeper. Use cases: PTT captures dominated by another voice; optional
  second gate after the wakeword. It is speaker *verification* ("is this the
  user?"), deliberately not full diarization (fragile locally in the target
  environment: overlapped speech, identity swaps). Fail-open: verification
  failure degrades to normal transcription. Evaluate first on real noisy home
  audio (dinner-table noise, overlapping voices) measuring true/false-positive
  rates against a cosine-similarity check.

## 4. Recommended parameters

```python
# faster-whisper per phrase (dictation)
language=<config>,               # fixed by the Wizard
beam_size=1,                     # greedy; re-decode beam 5 only if conf low
vad_filter=True,
vad_parameters={"min_silence_duration_ms": 500-700, "threshold": 0.4,
                "min_speech_duration_ms": 250, "speech_pad_ms": 30-50},
condition_on_previous_text=False,
no_speech_threshold=0.6,         # anti-hallucination gate (make explicit)
compression_ratio_threshold=2.4, # anti-loop gate (make explicit)
log_prob_threshold=-1.0,
initial_prompt=<session language + context above confidence floor>,
# confidence
confidence = exp(avg_logprob) with gates; empty → 0.0
# review threshold: recalibrate to 0.70-0.75 after per-phrase segmentation
# (current 0.80 ≈ avg_logprob -0.223, too strict for the weak-link)
```

## 5. Diagnostic tests (5 minutes each)

1. **Chromium DSP**: record 10s with a fan in the background, with and
   without flags, and listen. If they sound equally dirty → the DSP is not
   applied in PipeWire → RNNoise.
2. **TTS self-hearing**: play Kokoro with wake word active and watch the
   scores in logs. If they rise while Polaris speaks → echoCancellation is
   not acting → own-voice false "Hey Ainara".
3. **Model A/B**: load `hey_jarvis` next to `aye_nah_rah`; music/TV in the
   background for 1 min; compare score traces. Jarvis sleeps and the custom
   sings → model quality is the root cause.
4. **Ghost messages**: wake word active, say nothing, check if text appears
   in the chat (hallucination in silence). With `vad_filter` already active:
   if they appear, noise is entering BEFORE Silero (capture).

## 6. Alignment with the vision

Mode 3 (direct send) is the one that sustains "Just talk to her": speaking
without looking at text. Fixed language + verified DSP + Silero phrases +
anti-hallucination gates + barge-in via echoCancellation make it trustworthy
for the first time. The accumulative review window with doubt highlighting
(mode 2) remains a safety net, not a patch.

---

PS. TODO: also record the openwakeword version in requirements when verifying
the `trigger_level` question — it is the only missing datum in this note.
