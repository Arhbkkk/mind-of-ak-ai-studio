import pytest

from app.validation import validate_timeline_segments


def test_timeline_preserves_user_order():
    assert validate_timeline_segments(
        [{"start": 5, "end": 8}, {"start": 1, "end": 2}], 10
    ) == [(5.0, 8.0), (1.0, 2.0)]


@pytest.mark.parametrize("segments", [[], [{"start": 0, "end": 1}] * 13, None])
def test_timeline_rejects_invalid_clip_count(segments):
    with pytest.raises(ValueError):
        validate_timeline_segments(segments, 20)


@pytest.mark.parametrize("segment", [
    {"start": -1, "end": 2},
    {"start": 2, "end": 2},
    {"start": 0, "end": 0.05},
    {"start": 0, "end": 21},
    {"start": "bad", "end": 2},
    {"start": 0},
    "not-an-object",
])
def test_timeline_rejects_invalid_ranges(segment):
    with pytest.raises(ValueError):
        validate_timeline_segments([segment], 20)


def test_timeline_rejects_total_over_ten_minutes():
    with pytest.raises(ValueError, match="10 minutes"):
        validate_timeline_segments([{"start": 0, "end": 601}], 700)
