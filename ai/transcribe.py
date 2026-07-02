"""
Voice-message transcription via Deepgram.

Active only when DEEPGRAM_API_KEY is configured (config.VOICE_ENABLED).
Telegram voice notes are OGG/Opus, which Deepgram accepts directly — no
transcoding needed.
"""

import logging

from deepgram import DeepgramClient, PrerecordedOptions, FileSource

import config

log = logging.getLogger(__name__)

_client = DeepgramClient(config.DEEPGRAM_API_KEY) if config.VOICE_ENABLED else None


async def transcribe_voice(file_path: str) -> str:
    """
    Transcribe a local audio file and return the recognised text.

    Raises
    ------
    RuntimeError
        If Deepgram is not configured.
    """
    if _client is None:
        raise RuntimeError("Deepgram is not configured (DEEPGRAM_API_KEY missing).")

    with open(file_path, "rb") as f:
        payload: FileSource = {"buffer": f.read()}

    options = PrerecordedOptions(
        model=config.DEEPGRAM_MODEL,
        language=config.DEEPGRAM_LANGUAGE,
        smart_format=True,
    )

    response = await _client.listen.asyncrest.v("1").transcribe_file(payload, options)
    transcript = response.results.channels[0].alternatives[0].transcript
    return transcript.strip()
