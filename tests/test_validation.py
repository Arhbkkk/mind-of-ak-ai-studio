from app.validation import compare_script_to_transcript, parse_srt, validate_subtitles


def test_parse_valid_srt():
    cues = parse_srt("1\n00:00:00,000 --> 00:00:02,000\nHello world")
    assert len(cues) == 1
    assert cues[0]["end_seconds"] == 2.0


def test_srt_past_duration_fails():
    report = validate_subtitles("1\n00:00:01,000 --> 00:00:06,000\nHello", 5)
    assert report["status"] == "FAIL"
    assert any(item["name"] == "timeline_bounds" and item["status"] == "FAIL" for item in report["checks"])


def test_missing_transcript_is_not_verified():
    report = compare_script_to_transcript("Hello there", None)
    assert report["status"] == "NOT_VERIFIED"


def test_text_comparison_flags_mismatch():
    report = compare_script_to_transcript("hello world", "hello there")
    assert report["status"] == "WARNING"
    assert report["missing_or_changed_words"]
