import unittest
from app.validation import parse_srt, validate_subtitles


class SubtitleTests(unittest.TestCase):
    def test_parses_tamil_and_english_cues(self):
        source = "1\n00:00:00,000 --> 00:00:02,000\nVanakkam! வணக்கம்\n\n2\n00:00:02,000 --> 00:00:04,000\nMind of AK"
        cues = parse_srt(source)
        self.assertEqual(len(cues), 2)
        self.assertIn("வணக்கம்", cues[0]["text"])

    def test_rejects_bad_timestamps(self):
        with self.assertRaises(ValueError):
            parse_srt("1\n00:00:00,000 --> invalid\nCaption")

    def test_rejects_subtitles_outside_clip(self):
        source = "1\n00:00:00,000 --> 00:00:08,000\nCaption"
        self.assertEqual(validate_subtitles(source, 5)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
