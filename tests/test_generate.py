import datetime as dt
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from scripts import generate

class RadioTest(unittest.TestCase):
    def test_episode_never_claims_calendar_connected(self):
        now=dt.datetime(2026,11,24,6,40,tzinfo=ZoneInfo("Asia/Tokyo"))
        fake={"川口市":{"low":4,"high":15,"rain_max":5,"hours":[{"hour":h,"temp":10,"rain":5,"weather":"晴れ","wind":5} for h in (7,12,18,21)]}}
        ep=generate.make_episode(now,fake,[],generate.music("2026-11-24"),[])
        self.assertEqual(ep["calendar_status"],"not_connected")
        self.assertIn("未確認",ep["sections"][3]["text"])
        self.assertNotIn("予定はありません",ep["sections"][3]["text"])
    def test_no_paid_api_usage_or_credentials(self):
        import inspect
        src=inspect.getsource(generate)
        self.assertNotIn("api.openai.com",src)
        self.assertNotIn("GOOGLE_REFRESH_TOKEN",src)
        self.assertNotIn("RADIO_PASSWORD",src)
    def test_music_urls_are_apple_search(self):
        self.assertEqual(len(generate.music("2026-11-24")),2)
        self.assertTrue(all(x["url"].startswith("https://music.apple.com/jp/search?term=") for x in generate.music("2026-11-24")))

if __name__=="__main__": unittest.main()
