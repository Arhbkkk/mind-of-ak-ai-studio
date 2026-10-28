"""Reusable, deterministic helpers for the Claude-reference editing workflow.

This module intentionally does not call an AI model or generate synthetic media.
It prepares FFmpeg filters and ASS subtitles from user-supplied assets.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.validation import parse_srt


def audio_filter_chain(volume: float = 1.0, cleanup: bool = False, loudness: bool = False) -> list[str]:
    """Build conservative voice-friendly filters; optional filters are opt-in."""
    filters: list[str] = []
    if cleanup:
        # Conservative denoise + rumble reduction + light compression. This is not
        # a substitute for manual listening, and aggressive denoising is avoided.
        filters.extend(["highpass=f=75", "afftdn=nf=-25", "acompressor=threshold=0.125:ratio=2:attack=15:release=180"])
    filters.append(f"volume={max(0.0, min(2.0, float(volume))):.3f}")
    if loudness:
        # EBU R128 target suitable for common online video delivery.
        filters.append("loudnorm=I=-14:TP=-1.0:LRA=11")
    return filters


def build_ass_subtitles(srt_text: str, duration: float, output_path: Path, style: str = "gold", offset_seconds: float = 0.0, canvas_width: int = 1080, canvas_height: int = 1920) -> dict[str, Any]:
    """Validate supplied SRT and convert it to UTF-8 ASS with safe, readable styling."""
    cues = parse_srt(srt_text)
    adjusted = []
    clip_end = offset_seconds + duration
    for cue in cues:
        # SRT normally follows the source timeline. Shift it to the trimmed clip,
        # dropping cues outside the selection and clipping cues at trim boundaries.
        start = max(0.0, cue["start_seconds"] - offset_seconds)
        end = min(duration, cue["end_seconds"] - offset_seconds)
        if cue["end_seconds"] <= offset_seconds or cue["start_seconds"] >= clip_end:
            continue
        if end > start:
            adjusted.append({**cue, "start_seconds": start, "end_seconds": end})
    cues = adjusted
    if not cues:
        raise ValueError("No SRT captions overlap the selected export range.")
    styles = {
        "gold": ("&H0017ACFC", "&H00FFFFFF"),
        "white": ("&H00FFFFFF", "&H00FFFFFF"),
        "documentary": ("&H00E8E8E8", "&H00FFFFFF"),
    }
    primary, outline = styles.get(style, styles["gold"])
    def stamp(seconds: float) -> str:
        cs = max(0, round(seconds * 100))
        h, rem = divmod(cs, 360000)
        m, rem = divmod(rem, 6000)
        s, centis = divmod(rem, 100)
        return f"{h}:{m:02d}:{s:02d}.{centis:02d}"
    def clean(text: str) -> str:
        # ASS special characters are escaped; line breaks remain intentional.
        return text.replace("\\", r"\\").replace("{", r"\\{").replace("}", r"\\}").replace("\n", r"\\N")
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {canvas_width}\nPlayResY: {canvas_height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: AK,FreeSans,62,{primary},&H000000FF,{outline},&H99000000,-1,0,3,2.5,1,2,70,70,130,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    events = []
    for cue in cues:
        events.append(f"Dialogue: 0,{stamp(cue['start_seconds'])},{stamp(cue['end_seconds'])},AK,,0,0,0,,{clean(cue['text'])}")
    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return {"cue_count": len(cues), "subtitle_style": style, "subtitle_file": str(output_path), "offset_seconds": offset_seconds, "canvas_width": canvas_width, "canvas_height": canvas_height}


def audio_diagnostics(silence_stderr: str, loudness_stderr: str = "") -> dict[str, Any]:
    """Parse FFmpeg silencedetect and ebur128 summaries without overstating certainty."""
    silences = []
    starts = re.findall(r"silence_start:\s*([0-9.]+)", silence_stderr)
    ends = re.findall(r"silence_end:\s*([0-9.]+)", silence_stderr)
    for index, start in enumerate(starts):
        end = float(ends[index]) if index < len(ends) else None
        silences.append({"start": float(start), "end": end, "duration": round(end-float(start), 3) if end is not None else None})
    combined = silence_stderr + "\n" + loudness_stderr
    integrated = re.findall(r"\bI:\s*(-?[0-9.]+)\s*LUFS", combined)
    true_peak = re.findall(r"\bPeak:\s*(-?[0-9.]+)\s*dBFS", combined)
    return {
        "silence_segments": silences,
        "integrated_loudness_lufs": float(integrated[-1]) if integrated else None,
        "true_peak_dbfs": float(true_peak[-1]) if true_peak else None,
        "note": "Silence and loudness are signal measurements, not proof of narration/script alignment.",
    }
