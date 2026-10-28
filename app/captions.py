"""Free caption formatting helpers.

These helpers format user-supplied text into approximate-timing SRT/VTT.
They do not perform speech recognition or align words to actual audio.
"""
from __future__ import annotations

import re


def _timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{millis:03d}"


def generate_captions(text: str, duration_seconds: float, words_per_caption: int = 6) -> dict:
    """Split supplied text into evenly distributed approximate caption cues."""
    if not text or not text.strip():
        raise ValueError("Enter a transcript or script first.")
    if len(text) > 100_000:
        raise ValueError("Text is too long. Keep it under 100,000 characters.")
    if duration_seconds <= 0 or duration_seconds > 3600:
        raise ValueError("Duration must be greater than 0 and no more than 3600 seconds.")
    if not 1 <= words_per_caption <= 20:
        raise ValueError("Words per caption must be between 1 and 20.")

    words = re.findall(r"\S+", text.strip())
    chunks = [words[i:i + words_per_caption] for i in range(0, len(words), words_per_caption)]
    total_weight = sum(len(chunk) for chunk in chunks)
    elapsed = 0.0
    cues = []
    for index, chunk in enumerate(chunks, start=1):
        cue_duration = duration_seconds * len(chunk) / total_weight
        start = elapsed
        end = duration_seconds if index == len(chunks) else elapsed + cue_duration
        cues.append({
            "index": index,
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "text": " ".join(chunk),
        })
        elapsed = end

    srt_blocks = []
    vtt_blocks = []
    for cue in cues:
        srt_blocks.append(
            f'{cue["index"]}\n{_timestamp(cue["start_seconds"], ",")} --> '
            f'{_timestamp(cue["end_seconds"], ",")}\n{cue["text"]}'
        )
        vtt_blocks.append(
            f'{_timestamp(cue["start_seconds"], ".")} --> '
            f'{_timestamp(cue["end_seconds"], ".")}\n{cue["text"]}'
        )

    return {
        "ok": True,
        "cue_count": len(cues),
        "cues": cues,
        "srt": "\n\n".join(srt_blocks) + "\n",
        "vtt": "WEBVTT\n\n" + "\n\n".join(vtt_blocks) + "\n",
        "timing": "Approximate timing distributed across the supplied duration; not speech-recognition or audio-aligned timing.",
    }
