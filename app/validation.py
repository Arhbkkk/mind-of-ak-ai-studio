"""Evidence-based validation helpers for subtitle files and supplied transcripts.

These checks validate structure and timing. They do not perform speech recognition,
prove that subtitles match the audio, or semantically verify image relevance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


TIMESTAMP_RE = re.compile(
    r"^(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?$"
)


def timestamp_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    h, m, s, ms = int(hours), int(minutes), int(seconds), int(millis)
    if m >= 60 or s >= 60:
        raise ValueError("Minutes and seconds in SRT timestamps must be below 60.")
    return h * 3600 + m * 60 + s + ms / 1000


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.casefold(), flags=re.UNICODE)


def parse_srt(srt_text: str) -> list[dict[str, Any]]:
    """Parse SRT cues and reject malformed timestamps, empty cues, and bad order."""
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n").strip().lstrip("\ufeff")
    if not normalized:
        raise ValueError("SRT is empty.")
    blocks = re.split(r"\n\s*\n", normalized)
    cues: list[dict[str, Any]] = []
    for block_number, block in enumerate(blocks, start=1):
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2:
            raise ValueError(f"Cue {block_number} must include a timestamp and subtitle text.")
        match = TIMESTAMP_RE.match(lines[0].strip())
        if not match:
            raise ValueError(f"Cue {block_number} has an invalid SRT timestamp.")
        values = match.groups()
        start = timestamp_seconds(*values[:4])
        end = timestamp_seconds(*values[4:])
        text = "\n".join(lines[1:]).strip()
        if not text:
            raise ValueError(f"Cue {block_number} has empty subtitle text.")
        if end <= start:
            raise ValueError(f"Cue {block_number} ends at or before it starts.")
        if cues and start < cues[-1]["start_seconds"]:
            raise ValueError(f"Cue {block_number} starts before the previous cue.")
        cues.append({
            "index": len(cues) + 1,
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "duration_seconds": round(end - start, 3),
            "text": text,
        })
    return cues


def validate_subtitles(srt_text: str, duration_seconds: float) -> dict[str, Any]:
    """Return PASS/WARNING/FAIL checks; never claim audio alignment without a transcript."""
    try:
        cues = parse_srt(srt_text)
    except ValueError as exc:
        return {
            "status": "FAIL",
            "checks": [{"name": "srt_structure", "status": "FAIL", "detail": str(exc)}],
            "cues": [],
        }

    checks = [{"name": "srt_structure", "status": "PASS", "detail": f"{len(cues)} valid subtitle cues parsed."}]
    overlaps = []
    out_of_bounds = []
    long_cues = []
    short_cues = []
    for i, cue in enumerate(cues):
        if cue["end_seconds"] > duration_seconds + 0.05:
            out_of_bounds.append(cue["index"])
        if cue["duration_seconds"] > 7:
            long_cues.append(cue["index"])
        if cue["duration_seconds"] < 0.7:
            short_cues.append(cue["index"])
        if i and cue["start_seconds"] < cues[i - 1]["end_seconds"] - 0.001:
            overlaps.append(cue["index"])

    checks.append({
        "name": "timeline_bounds",
        "status": "FAIL" if out_of_bounds else "PASS",
        "detail": ("Cues extend beyond video duration: " + ", ".join(map(str, out_of_bounds)))
        if out_of_bounds else "All cues end within the video duration.",
    })
    checks.append({
        "name": "cue_overlaps",
        "status": "WARNING" if overlaps else "PASS",
        "detail": ("Overlapping cues: " + ", ".join(map(str, overlaps)))
        if overlaps else "No overlapping subtitle cues detected.",
    })
    checks.append({
        "name": "reading_duration",
        "status": "WARNING" if long_cues or short_cues else "PASS",
        "detail": f"Cues under 0.7 s: {short_cues or 'none'}; cues over 7 s: {long_cues or 'none'}. Review against reading speed and context.",
    })
    checks.append({
        "name": "audio_alignment",
        "status": "NOT_VERIFIED",
        "detail": "No speech-recognition transcript was provided. SRT timestamps and text have not been verified against spoken audio.",
    })
    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else (
        "WARNING" if any(c["status"] in ("WARNING", "NOT_VERIFIED") for c in checks) else "PASS"
    )
    return {"status": status, "checks": checks, "cue_count": len(cues), "cues": cues}


def compare_script_to_transcript(script: str, transcript: str | None) -> dict[str, Any]:
    """Compare text only when an actual transcript is supplied by a trusted ASR step."""
    if not transcript or not transcript.strip():
        return {
            "status": "NOT_VERIFIED",
            "detail": "No audio transcript was supplied; script-to-spoken-audio validation was not performed.",
            "script_word_count": len(normalize_words(script)),
        }
    expected = normalize_words(script)
    actual = normalize_words(transcript)
    if not expected:
        return {"status": "WARNING", "detail": "The script is empty.", "script_word_count": 0}
    from difflib import SequenceMatcher
    ratio = SequenceMatcher(a=expected, b=actual, autojunk=False).ratio()
    matcher = SequenceMatcher(a=expected, b=actual, autojunk=False)
    missing, extra = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            missing.extend(expected[i1:i2])
        if tag in ("insert", "replace"):
            extra.extend(actual[j1:j2])
    return {
        "status": "PASS" if ratio >= 0.98 and not missing and not extra else "WARNING",
        "detail": "Text similarity is a screening signal, not proof of correct pronunciation or meaning.",
        "similarity": round(ratio, 4),
        "script_word_count": len(expected),
        "transcript_word_count": len(actual),
        "missing_or_changed_words": missing[:100],
        "extra_or_changed_words": extra[:100],
    }


def validate_timeline_segments(segments: Any, source_duration: float, max_clips: int = 12, max_total_duration: float = 300.0) -> list[tuple[float, float]]:
    """Validate ordered edit ranges against one source and return normalized ranges."""
    if not isinstance(segments, list) or not 1 <= len(segments) <= max_clips:
        raise ValueError(f"Timeline must contain between 1 and {max_clips} clips.")
    try:
        duration = float(source_duration)
    except (TypeError, ValueError) as exc:
        raise ValueError("Source duration must be numeric.") from exc
    if not duration > 0:
        raise ValueError("Source duration must be positive.")

    ranges: list[tuple[float, float]] = []
    total = 0.0
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError("Each timeline clip must be an object.")
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Each clip needs numeric start and end values.") from exc
        if not (0 <= start < end <= duration + 0.05) or end - start < 0.1:
            raise ValueError("Timeline clip range is outside the source or too short.")
        end = min(end, duration)
        ranges.append((start, end))
        total += end - start
    if total > max_total_duration:
        raise ValueError(f"Combined timeline duration cannot exceed {int(max_total_duration // 60)} minutes.")
    return ranges
