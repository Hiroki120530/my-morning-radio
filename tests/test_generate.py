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
    def test_no_extractive_summarizer_remains(self):
        import inspect
        code=inspect.getsource(generate.get_news)
        self.assertNotIn("article_brief(",code)
        self.assertNotIn("merge_briefs(",code)
        self.assertIn("write_original_brief(",code)

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
        self.assertGreaterEqual(generate.editorial_score({"title":title}),0)

    def test_original_model_editor_used_instead_of_excerpts(self):
        bad={"title":"【動画】上空から見た首里城正殿は？",
             "url":"https://example.com/video","source":"test"}
        good={"title":"政府が企業向け支援制度の導入を決定 2027年に実施",
              "url":"https://example.com/story","source":"test"}
        body=("政府は企業向けの新たな支援制度の導入を決定した。"
              "2027年に実施する方針で、対象企業への案内を始める。"
              "詳細な条件は今後公表されるとしている。")*3
        fresh=("中小企業を支えるための新しい制度が、政府によって決まりました。"
               "実施は2027年の予定で、対象者への案内も始まります。"
               "具体的な条件については今後の公表を待つ必要があります。")
        with patch.object(generate,"feed_entries",return_value=[bad,good]), \
             patch.object(generate,"news_article",return_value=body) as read, \
             patch("scripts.editorial.write_original_brief",return_value=fresh) as writer:
            news=generate.get_news()
        self.assertEqual(read.call_count,1)
        self.assertEqual(writer.call_count,1)
        self.assertEqual(news[0]["detail"],fresh)
        self.assertEqual(news[0]["editorial_method"],"local_ai_original")

    def test_related_headlines_group_across_publishers(self):
        a={"title":"政府が新しい企業支援制度を発表 2027年から開始",
           "source":"NHK","url":"https://example.org/a"}
        b={"title":"企業支援制度を政府が発表、2027年から開始へ",
           "source":"BBC日本語","url":"https://example.org/b"}
        groups=generate.topic_groups([a,b])
        self.assertEqual(len(groups),1)
        self.assertEqual({x["source"] for x in groups[0]}, {"NHK","BBC日本語"})

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
