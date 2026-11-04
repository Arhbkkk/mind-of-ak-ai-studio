"""Container-only smoke test for the real FFmpeg/libass subtitle pipeline."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.subtitles import build_subtitle_filter


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for this integration test")
class FFmpegSubtitleIntegrationTests(unittest.TestCase):
    def test_burns_tamil_subtitles_into_mp4(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subtitle = root / "captions.srt"
            output = root / "rendered.mp4"
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,500\nவணக்கம் Mind of AK\n",
                encoding="utf-8",
            )
            filter_value = build_subtitle_filter(subtitle, 36, "bottom", "yellow")
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2",
                    "-vf", filter_value, "-an", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
                ],
                capture_output=True, text=True, timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 1000)

    def test_tamil_font_is_available(self):
        if not shutil.which("fc-match"):
            self.skipTest("fontconfig is unavailable")
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans Tamil"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), "Noto Sans Tamil font was not resolved")


if __name__ == "__main__":
    unittest.main()
