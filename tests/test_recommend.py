import datetime as dt
import json
import unittest
from scripts import recommend


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.pool=json.loads(recommend.POOL.read_text(encoding="utf-8"))["artists"]
        self.known_favorite_artists={
            "BUMP OF CHICKEN","SUPER BEAVER","Age Factory",
            "ASIAN KUNG-FU GENERATION","サカナクション","米津玄師",
            "RADWIMPS","[Alexandros]","Aqua Timez","Perfume",
            "ELLEGARDEN","KANA-BOON","WOMCADOLE","Vaundy",
            "UNISON SQUARE GARDEN","go!go!vanillas",
        }

    @staticmethod
    def catalog(url,params):
        artist=params["term"]
        return {"results":[
            {"artistName":artist,"trackName":f"{artist} 曲 {i}",
             "trackId":i,
             "previewUrl":f"https://audio-ssl.itunes.apple.com/test-{i}.m4a",
             "trackViewUrl":f"https://music.apple.com/jp/album/{i}"}
             for i in range(1,11)
        ]}

    def test_artist_pool_discloses_no_favorites(self):
        pool={recommend.normalize(x["name"]) for x in self.pool}
        self.assertTrue(pool)
        self.assertTrue(pool.isdisjoint({
            recommend.normalize(x) for x in self.known_favorite_artists
        }))

    def test_two_different_new_artist_groups_each_morning(self):
        for date in ("2026-11-23","2026-11-24","2026-12-14","2027-03-23"):
            songs=recommend.daily_recommendations(date,self.catalog)
            self.assertEqual(len(songs),2)
            self.assertEqual({x["discovery_group"] for x in songs},{"rock","explore"})
            self.assertEqual(len({recommend.normalize(x["artist"]) for x in songs}),2)
            self.assertTrue(all(x["preview_url"].startswith("https://") for x in songs))

    def test_no_repeat_next_day_or_artist_on_first_two_days(self):
        today=recommend.daily_recommendations("2026-11-23",self.catalog)
        tomorrow=recommend.daily_recommendations("2026-11-24",self.catalog)
        self.assertTrue(set(x["artist"] for x in today).isdisjoint(
            x["artist"] for x in tomorrow
        ))

    def test_same_artist_new_recording_next_rotation(self):
        group=[a for a in self.pool if a["group"]=="explore"]
        day1=recommend.daily_recommendations("2026-11-23",self.catalog)
        day2=recommend.daily_recommendations(
            (dt.date(2026,11,23)+dt.timedelta(days=len(group))).isoformat(),
            self.catalog
        )
        self.assertEqual(day1[1]["artist"],day2[1]["artist"])
        self.assertNotEqual(day1[1]["title"],day2[1]["title"])

    def test_filters_other_artists_and_missing_previews(self):
        def polluted(url,params):
            return {"results":[
                {"artistName":"BUMP OF CHICKEN","trackName":"ダメ","trackId":1,
                 "previewUrl":"https://a.example/a.m4a","trackViewUrl":"https://a.example/t"},
                {"artistName":params["term"],"trackName":"プレビューなし","trackId":2,
                 "trackViewUrl":"https://a.example/t"},
                {"artistName":params["term"],"trackName":"聴ける曲","trackId":3,
                 "previewUrl":"https://a.example/a.m4a",
                 "trackViewUrl":"https://music.apple.com/jp/album/3"},
            ]}
        songs=recommend.daily_recommendations("2026-11-23",polluted)
        self.assertEqual(len(songs),2)
        self.assertTrue(all(x["title"]=="聴ける曲" for x in songs))

    def test_no_fake_music_when_catalog_unavailable(self):
        songs=recommend.daily_recommendations("2026-11-23",lambda url,p:{"results":[]})
        self.assertEqual(songs,[])


if __name__=="__main__":
    unittest.main()
