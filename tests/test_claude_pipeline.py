from pathlib import Path

from app.claude_pipeline import audio_filter_chain, build_ass_subtitles


SRT = """1
00:00:01,000 --> 00:00:02,000
Vanakkam Tamil!

2
00:00:04,000 --> 00:00:05,000
Second caption
"""


def test_audio_filter_chain_defaults_to_volume_only():
    assert audio_filter_chain(1.0) == ["volume=1.000"]


def test_audio_filter_chain_adds_cleanup_and_loudness():
    filters = audio_filter_chain(1.2, cleanup=True, loudness=True)
    assert "highpass=f=75" in filters
    assert any(item.startswith("afftdn=") for item in filters)
    assert any(item.startswith("acompressor=") for item in filters)
    assert "volume=1.200" in filters
    assert any(item.startswith("loudnorm=I=-14") for item in filters)


def test_ass_subtitles_shift_to_trimmed_source_timeline(tmp_path: Path):
    output = tmp_path / "captions.ass"
    result = build_ass_subtitles(SRT, duration=2.0, output_path=output, style="gold", offset_seconds=3.0)
    text = output.read_text(encoding="utf-8")
    assert result["cue_count"] == 1
    assert "Second caption" in text
    assert "Vanakkam Tamil!" not in text
    assert "Style: AK,FreeSans" in text
    assert "Dialogue: 0,0:00:01.00,0:00:02.00" in text


def test_ass_subtitles_reject_when_no_caption_overlaps_clip(tmp_path: Path):
    output = tmp_path / "captions.ass"
    try:
        build_ass_subtitles(SRT, duration=1.0, output_path=output, style="white", offset_seconds=10.0)
    except ValueError as exc:
        assert "No SRT captions overlap" in str(exc)
    else:
        raise AssertionError("Expected out-of-range captions to be rejected")
