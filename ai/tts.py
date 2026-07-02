"""
Text-to-speech for voice replies.

Deepgram's TTS (Aura) has no Russian voice, so voice replies use edge-tts —
the free Microsoft Edge voices, which have high-quality Russian (ru-RU). Edge
returns MP3, so we transcode to Ogg/Opus 48 kHz mono via a pip-bundled ffmpeg
(imageio-ffmpeg) — that is the format Telegram renders as a proper voice note
(with waveform and inline player).
"""

import asyncio
import logging
import os

import edge_tts
import imageio_ffmpeg

import config

log = logging.getLogger(__name__)

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


async def synthesize_voice(text: str, out_path: str) -> str:
    """
    Synthesize `text` into an Ogg/Opus voice note written to `out_path`.

    Returns the path on success. Raises on failure (caller falls back to text).
    """
    mp3_path = out_path + ".mp3"
    try:
        communicate = edge_tts.Communicate(text, config.TTS_VOICE)
        await communicate.save(mp3_path)

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            raise RuntimeError("edge-tts produced no audio")

        proc = await asyncio.create_subprocess_exec(
            _FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-i", mp3_path,
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000", "-ac", "1",
            out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed ({proc.returncode}): "
                f"{stderr.decode(errors='ignore')[:300]}"
            )
        return out_path
    finally:
        if os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except OSError:
                pass
