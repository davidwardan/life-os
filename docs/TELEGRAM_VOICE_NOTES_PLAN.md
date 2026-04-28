# Telegram Voice Notes Plan

## Goal

Enable Telegram voice notes so they are transcribed into text and then processed by the existing Life OS logging workflow.

## Current Branch Scope

- Add Telegram `voice` update handling.
- Download the Telegram voice file through the bot API.
- Transcribe the audio with an interchangeable transcription backend.
- Send the transcript through the same workflow used by text Telegram messages.
- Keep non-text, non-voice Telegram messages ignored.
- Document what has to be configured for local and hosted use.

## Implemented Backend Options

### Local `faster-whisper`

This is the default backend:

```text
TELEGRAM_VOICE_TRANSCRIPTION_BACKEND=faster-whisper
TELEGRAM_VOICE_TRANSCRIPTION_MODEL=base
TELEGRAM_VOICE_TRANSCRIPTION_DEVICE=cpu
TELEGRAM_VOICE_TRANSCRIPTION_COMPUTE_TYPE=int8
```

It runs transcription inside the Life OS process. The first voice note downloads the selected model from Hugging Face and caches it on the host.

This is useful for local development or a host with enough CPU/RAM, but it is not the best fit for Render free because cold starts, sleeping instances, and model caching can make voice notes slow or unreliable.

### OpenAI-Compatible API

The app can also call a separate transcription service:

```text
TELEGRAM_VOICE_TRANSCRIPTION_BACKEND=api
TELEGRAM_VOICE_TRANSCRIPTION_BASE_URL=https://your-transcription-service.example/v1
TELEGRAM_VOICE_TRANSCRIPTION_API_KEY=your-shared-secret
TELEGRAM_VOICE_TRANSCRIPTION_MODEL=base
```

This lets the Render web service stay lightweight while another host keeps the Whisper model available.

## Recommended Free Hosted Plan

Use this architecture:

```text
Telegram -> Render Life OS -> Hugging Face Space transcription API -> Life OS logs transcript
```

Recommended setup:

- Keep Life OS on Render free.
- Host a small OpenAI-compatible `faster-whisper` transcription API on Hugging Face Spaces CPU Basic.
- Use `base`, `cpu`, and `int8` for the first version.
- Protect the Space with a shared secret checked by the transcription API.
- Configure Render to call the Space with `TELEGRAM_VOICE_TRANSCRIPTION_BACKEND=api`.

Hugging Face Spaces CPU Basic is the best free non-local candidate discussed because it has more practical CPU/RAM headroom for `faster-whisper` than Koyeb, Railway, or Render free. It can still sleep, so first requests may be slow.

## Next Work

- Add a small Docker/FastAPI transcription service for Hugging Face Spaces.
- Make it OpenAI-compatible at `POST /v1/audio/transcriptions`.
- Add shared-secret authentication.
- Add deployment docs for creating the Hugging Face Space.
- Update Render `.env` instructions for pointing Life OS at that Space.
