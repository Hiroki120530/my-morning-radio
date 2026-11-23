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
        self.assertIn("確認できていない",ep["sections"][3]["text"])
        self.assertNotIn("予定はありません",ep["sections"][3]["text"])
    def test_no_paid_api_usage_or_credentials(self):
        import inspect
        src=inspect.getsource(generate)
        self.assertNotIn("api.openai.com",src)
        self.assertNotIn("GOOGLE_REFRESH_TOKEN",src)
        self.assertNotIn("RADIO_PASSWORD",src)
    def test_no_site_navigation_or_robotic_tail_in_news(self):
        body = (
            "地図から選ぶ NHK ONEはどなたでもご利用になれます。"
            "政府は23日、国内の企業向けに新たな支援策を発表した。"
            "支援策には中小企業向けの補助金が含まれており、2027年から実施するとしている。"
            "経済産業省は今後、具体的な申請手続きを公表する方針だ。"
            "詳しい内容は画面のニュース欄から確認できます。"
        )
        digest=generate.article_brief(body, "政府が国内企業向けの支援策を発表")
        self.assertTrue(digest, "Should retain factual article sentences")
        for unwanted in ("地図から選ぶ","NHK ONE","どなたでもご利用になれます",
                         "ここまでが、公開記事から確認できた内容です"):
            self.assertNotIn(unwanted,digest)
        now=dt.datetime(2026,11,24,6,40,tzinfo=ZoneInfo("Asia/Tokyo"))
        news=[{"title":"政府が国内企業向けの支援策を発表", "detail":digest}]
        ep=generate.make_episode(now,{},news,[],[])
        narration=ep["sections"][2]["text"]
        self.assertIn("支援策",narration)
        self.assertNotIn("政府が国内企業向けの支援策を発表。",narration)
        self.assertNotIn("まず1件目",narration)
        self.assertNotIn("ここまでが",narration)

    def test_discard_navigation_only_article(self):
        body = "地図から選ぶ。NHK ONEはどなたでもご利用になれます。カテゴリから選ぶ。"
        self.assertEqual(generate.article_brief(body, "ニュース"), "")

    def test_visual_teasers_rejected_before_fetch(self):
        for title in (
            "【動画】上空から見た首里城正殿は？",
            "【写真】上空から見た首里城の様子を紹介",
            "写真で見る 首里城の現在の姿は？",
            "【映像】現場で何が起きた？",
        ):
            self.assertEqual(generate.editorial_score({"title":title}),-1,title)

    def test_substantive_news_passes_editorial_gate(self):
        title="政府が新たな補助金制度の導入を決定 2027年から実施"
        item={"title":title}
        self.assertGreaterEqual(generate.editorial_score(item),0)
        detail=("政府は中小企業向けの新たな補助金制度の導入を決定した。"
                "対象となる企業の条件は今後公表する方針としている。")
        self.assertTrue(generate.useful_news(item,detail))
        self.assertFalse(generate.useful_news(item, "【動画】首里城を上空から見た様子です。"))

    def test_editorial_filter_applies_before_news_article_fetch(self):
        bad={"title":"【動画】上空から見た首里城正殿は？","url":"https://example.com/video","source":"test"}
        good={"title":"政府が企業向け支援制度の導入を決定 2027年に実施",
              "url":"https://example.com/story","source":"test"}
        text=("政府は企業向けの新たな支援制度の導入を決定した。"
              "2027年に実施する方針で、対象企業への案内を始める。"
              "詳細な条件は今後公表されるとしている。")
        with patch.object(generate,"feed_entries",return_value=[bad,good]), \\
             patch.object(generate,"news_article",return_value=text) as read:
            news=generate.get_news()
        self.assertEqual(read.call_count,1)
        self.assertFalse(any("首里城" in story["title"] for story in news))

    def test_music_urls_are_apple_search(self):
        self.assertEqual(len(generate.music("2026-11-24")),2)
        self.assertTrue(all(x["url"].startswith("https://music.apple.com/jp/search?term=") for x in generate.music("2026-11-24")))

if __name__=="__main__": unittest.main()
