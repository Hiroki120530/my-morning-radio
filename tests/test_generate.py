import datetime as dt
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from scripts import generate

class RadioTest(unittest.TestCase):
    def test_episode_never_claims_calendar_connected(self):
        now=dt.datetime(2026,11,24,6,40,tzinfo=ZoneInfo("Asia/Tokyo"))
        fake={"川口市":{"low":4,"high":15,"rain_max":5,"hours":[{"hour":h,"temp":10,"rain":5,"weather":"晴れ","wind":5} for h in (7,12,18,21)]}}
        ep=generate.make_episode(now,fake,[],[],[])
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
                "対象となる企業の条件は今後公表する方針としている。"
                "実施時期は2027年を予定しており、担当省庁が申請方法を整備する。")
        self.assertTrue(generate.useful_news(item,detail))
        self.assertFalse(generate.useful_news(item, "【動画】首里城を上空から見た様子です。"))

    def test_editorial_filter_applies_before_news_article_fetch(self):
        bad={"title":"【動画】上空から見た首里城正殿は？","url":"https://example.com/video","source":"test"}
        good={"title":"政府が企業向け支援制度の導入を決定 2027年に実施",
              "url":"https://example.com/story","source":"test"}
        text=("政府は企業向けの新たな支援制度の導入を決定した。"
              "2027年に実施する方針で、対象企業への案内を始める。"
              "詳細な条件は今後公表されるとしている。")
        with patch.object(generate,"feed_entries",return_value=[bad,good]), \
             patch.object(generate,"news_article",return_value=text) as read:
            news=generate.get_news()
        self.assertEqual(read.call_count,1)
        self.assertFalse(any("首里城" in story["title"] for story in news))

    def test_related_headlines_group_across_publishers(self):
        a={"title":"政府が新しい企業支援制度を発表 2027年から開始",
           "source":"NHK","url":"https://example.org/a"}
        b={"title":"企業支援制度を政府が発表、2027年から開始へ",
           "source":"BBC日本語","url":"https://example.org/b"}
        groups=generate.topic_groups([a,b])
        self.assertEqual(len(groups),1)
        self.assertEqual({x["source"] for x in groups[0]}, {"NHK","BBC日本語"})

    def test_multi_source_composition_does_not_invent_claims(self):
        first={"detail":"政府は企業向けの支援制度を発表し、2027年から実施するとした。"
                        "対象は中小企業で、補助金の支給も予定している。"}
        second={"detail":"対象企業の申請方法は後日発表される。"
                         "申請手続きは関係省庁が整備する方針だ。"}
        result=generate.merge_briefs(first,second)
        self.assertIn("政府",result)
        self.assertNotIn("経済効果",result)
        self.assertNotIn("出典",result)

    def test_source_links_not_spoken(self):
        now=dt.datetime(2026,11,24,6,40,tzinfo=ZoneInfo("Asia/Tokyo"))
        item={"title":"政府が企業支援制度の導入を発表",
              "detail":"政府は中小企業向けの支援制度を発表した。2027年から制度の実施を始める。",
              "checked_sources":[{"name":"NHK","url":"https://example.org/a"}]}
        ep=generate.make_episode(now,{},[item],[],[])
        spoken=ep["sections"][2]["text"]
        self.assertNotIn("https://",spoken)
        self.assertNotIn("出典",spoken)

    def test_two_preview_tracks_are_recommended(self):
        def fake(url, params):
            artist=params["term"]
            return {"results":[{
                "artistName":artist,
                "trackName":artist+" の新曲",
                "trackId":123,
                "trackViewUrl":"https://music.apple.com/jp/album/example/123",
                "previewUrl":"https://audio-ssl.itunes.apple.com/example.m4a",
            }]}
        with patch.object(generate,"get_json",side_effect=fake):
            songs=generate.music("2026-11-24")
        self.assertEqual(len(songs),2)
        self.assertTrue(all(x["preview_url"].startswith("https://") for x in songs))
        self.assertEqual(len({x["artist"] for x in songs}),2)

    def test_no_song_when_not_playable(self):
        with patch.object(generate,"get_json",return_value={"results":[]}):
            songs=generate.music("2026-11-24")
        self.assertEqual(songs,[])
        now=dt.datetime(2026,11,24,6,40,tzinfo=ZoneInfo("Asia/Tokyo"))
        ep=generate.make_episode(now,{},[],songs,[])
        self.assertFalse(any(s.get("music_break") for s in ep["sections"]))
        self.assertNotIn("リンクから再生", str(ep["sections"]))

    def test_song_is_introduced_for_in_programme_playback(self):
        songs=[
            {"artist":"the cabs","title":"曲A","reason":"力強いギター",
             "preview_url":"https://example.org/preview.mp4"},
            {"artist":"SHE'S","title":"曲B","reason":"美しいピアノ",
             "preview_url":"https://example.org/preview2.mp4"}
        ]
        now=dt.datetime(2026,11,24,6,40,tzinfo=ZoneInfo("Asia/Tokyo"))
        ep=generate.make_episode(now,{},[],songs,[])
        music_sections=[s for s in ep["sections"] if s.get("music_break")]
        self.assertEqual(len(music_sections),2)
        self.assertIn("試聴してみましょう", music_sections[0]["text"])
        self.assertNotIn("リンク",music_sections[0]["text"])

if __name__=="__main__": unittest.main()
