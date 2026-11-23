import pathlib
import re
import shutil
import subprocess
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class PlayerIntegrationTests(unittest.TestCase):
    def test_javascript_syntax(self):
        page=(ROOT/"site"/"index.html").read_text(encoding="utf-8")
        scripts=re.findall(r"<script>([\s\S]*?)</script>",page)
        self.assertEqual(len(scripts),1)
        if shutil.which("node") is None:
            self.skipTest("Node.js unavailable")
        result=subprocess.run(["node","--check","-"],input=scripts[0],
                              text=True,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_in_programme_preview_sequence_and_song_cards(self):
        page=(ROOT/"site"/"index.html").read_text(encoding="utf-8")
        self.assertIn("official_preview",page)
        self.assertIn("void advance()",page)
        self.assertIn("nativeSong.controls=true",page)
        self.assertIn("nativeSong.src=song.preview_url",page)
        self.assertIn("provided courtesy of iTunes",page)
        self.assertIn("Apple Musicで曲を確認",page)
        self.assertIn("この曲を試聴",page)
        self.assertIn("startTrack(cursor+1)",page)
        self.assertNotIn("ニュース・天気の出典",page)
