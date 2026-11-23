import copy
import unittest
from scripts.proofread import tidy_typography, defects, validate_and_polish_episode, naturalize_parentheses

class JapaneseProofreadingTests(unittest.TestCase):
    def test_typographic_cleanup(self):
        self.assertEqual(tidy_typography("政府は  制度を発表した。。  "), "政府は 制度を発表した。")

    def test_rejects_cut_off_japanese_and_missing_okurigana(self):
        for broken in (
            "政府が新たな制度を発表",
            "政府が新しい制度を発表。",
            "今回の改革について。",
            "担当者が今回の対応を決。",
            "同じ内容を再度確認するため、",
        ):
            self.assertTrue(defects(broken, news=True), broken)

    def test_keeps_complete_spoken_japanese(self):
        text=("政府は新しい支援制度を発表した。"
              "申請方法は2027年に公表される予定だ。"
              "対象企業の詳細は後日明らかになる。")
        self.assertEqual(defects(text, news=True), [])

    def test_removes_bad_story_before_audio_without_fabrication(self):
        original = {
            "sections":[
                {"title":"オープニング","text":"おはようございます。"},
                {"title":"今日のニュース","text":"古いニュース原稿。"},
                {"title":"エンディング","text":"また明日。"}
            ],
            "news":[
                {"title":"ダメな記事","detail":"政府は企業向けの支援制度を発表"},
                {"title":"使える記事","detail":"政府は新しい制度を発表した。申請方法は来年公表される予定だ。"}
            ]
        }
        result,report=validate_and_polish_episode(copy.deepcopy(original))
        self.assertEqual(len(result["news"]),1)
        self.assertEqual(len(report["rejected_news"]),1)
        self.assertNotIn("ダメな記事", result["sections"][1]["text"])
        self.assertNotIn("発表。", result["sections"][1]["text"])
        self.assertIn("来年公表される予定だ。",result["sections"][1]["text"])
        self.assertEqual(result["proofreading"]["status"],"passed")

    def test_parentheses_rewritten_for_listening(self):
        self.assertEqual(naturalize_parentheses("AI（人工知能）が話題です。"),
                         "人工知能が話題です。")
        self.assertEqual(naturalize_parentheses("人工知能（AI）が話題です。"),
                         "人工知能が話題です。")
        self.assertEqual(naturalize_parentheses("防災（ぼうさい）の対策です。"),
                         "防災の対策です。")
        self.assertEqual(naturalize_parentheses("AI(人工知能)が話題です。"),
                         "人工知能が話題です。")

    def test_ambiguous_parentheses_rejected_not_deleted(self):
        with self.assertRaises(ValueError):
            naturalize_parentheses("政府は制度（来年度から開始）を発表した。")
        self.assertIn("round_parentheses_in_narration",
                      defects("今日は制度（来年度開始）を説明します。"))

    def test_parenthesized_news_excluded_from_broadcast(self):
        episode={"sections":[
             {"title":"オープニング","text":"おはようございます。"},
             {"title":"今日のニュース","text":"政府は制度（来年度から開始）を発表した。"},
             {"title":"エンディング","text":"また明日。"}],
             "news":[
              {"title":"曖昧","detail":"政府は制度（来年度から開始）を発表した。"},
              {"title":"正常","detail":"政府は新たな支援制度を発表した。申請方法は来年公表される。"}]}
        result,report=validate_and_polish_episode(copy.deepcopy(episode))
        self.assertEqual(len(result["news"]),1)
        self.assertEqual(len(report["rejected_news"]),1)
        self.assertNotIn("（",result["sections"][1]["text"])
        self.assertNotIn("(",result["sections"][1]["text"])

    def test_raises_for_broken_core_narration(self):
        ep={"sections":[{"title":"オープニング","text":"おはようございます"}]}
        with self.assertRaises(ValueError):
            validate_and_polish_episode(ep)

if __name__ == "__main__":
    unittest.main()
