import unittest
from pathlib import Path
from app.subtitles import build_subtitle_filter


class SubtitleFilterTests(unittest.TestCase):
    def test_default_style(self):
        value = build_subtitle_filter(Path("/data/captions.srt"))
        self.assertIn("FontSize=36", value)
        self.assertIn("Alignment=2", value)
        self.assertIn("PrimaryColour=&H00FFFFFF", value)

    def test_custom_position_and_color(self):
        value = build_subtitle_filter(Path("/data/captions.srt"), 48, "top", "yellow")
        self.assertIn("FontSize=48", value)
        self.assertIn("Alignment=8", value)
        self.assertIn("PrimaryColour=&H0000FFFF", value)

    def test_rejects_unsafe_values(self):
        with self.assertRaises(ValueError):
            build_subtitle_filter(Path("/tmp/a.srt"), 500)
        with self.assertRaises(ValueError):
            build_subtitle_filter(Path("/tmp/a.srt"), 36, "random", "white")


if __name__ == "__main__":
    unittest.main()
