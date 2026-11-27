import unittest
from scripts import editorial


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.source=(
            "政府は27日、中小企業向けの新しい支援制度を発表した。"
            "制度の開始は2027年を予定しており、対象となる企業については今後説明する。"
            "担当省庁では申請方法の詳細をまとめ、受付に向けた準備を進めている。"
            "対象企業には事前に必要な書類の案内を行うことになっている。"
        )
        self.original=(
            "中小企業を対象にした支援の仕組みが新しく設けられることになりました。"
            "政府が示した予定では、制度が始まるのは2027年です。"
            "企業が実際に手続きを進めるための条件や申請方法は、今後の公表を待つ必要があります。"
        )

    def test_contract_notice_removed_from_evidence(self):
        content=(
            "受信契約がお済みの世帯の方は、別途の契約や追加のご負担なく利用できます。"
            "契約をされていない世帯の方が利用した場合は、放送法に基づき契約が必要です。"
            +self.source
        )
        result=editorial.clean_evidence(content)
        self.assertNotIn("受信契約",result)
        self.assertNotIn("放送法",result)
        self.assertIn("支援制度",result)

    def test_rejects_copy_paste_nhk_site_notice(self):
        notice=("受信契約がお済みの世帯の方は、別途の契約や追加のご負担なく利用できます。"
                "契約をされていない世帯の方が利用した場合は、放送法に基づき契約が必要です。")
        self.assertIn("website_or_contract_copy",
                      editorial.review_script(notice,[self.source]))

    def test_rejects_headline_fragments_and_unverified_interpretation(self):
        bad=("英皇太子夫妻の別邸に不法侵入の疑い、2人逮捕。"
             "ノーフォークのサンドリンガムに位置する別荘で、不審な動きが発覚。"
             "警察は捜索犬とドローンを使って2人を逮捕。"
             "皇太子夫妻は常時住んでいないため、今回の事件は意外と発覚した。")
        errors=editorial.review_script(bad,[self.source])
        self.assertIn("unnatural_sentence_end",errors)
        self.assertIn("unsupported_speculation_or_editorializing",errors)

    def test_rejects_long_verbatim_article_sentence(self):
        self.assertTrue(editorial.shared_passage(
            "重要です。"+self.source+"特に注目です。",self.source))
        copy=self.source
        self.assertIn("copied_source_wording",
                      editorial.review_script(copy,[self.source]))

    def test_original_script_different_from_evidence_passes(self):
        errors=editorial.review_script(self.original,[self.source])
        self.assertEqual(errors,[],errors)

    def test_rejects_unsupported_claims(self):
        altered=self.original.replace("2027年", "2029年")
        self.assertIn("unsupported_number",
                      editorial.review_script(altered,[self.source]))

    def test_rejects_bad_editor_output_and_never_falls_back_to_excerpts(self):
        def ai(payload):
            return {"message":{"content":
                    '{"summary":"'+self.source+'","basis":"支援制度の発表"}'}}
        output=editorial.write_original_brief(
            {"title":"政府は支援制度を発表"},[("NHK",self.source)],model_call=ai)
        self.assertEqual(output,"")

    def test_short_draft_gets_rewritten_not_published(self):
        calls=[]
        def ai(payload):
            calls.append(payload)
            if len(calls)==1:
                text="政府は新制度を決定しました。"
            else:
                text=self.original
            return {"message":{"content":
                     __import__("json").dumps({"summary":text,"basis":"支援制度"},ensure_ascii=False)}}
        result=editorial.write_original_brief(
            {"title":"政府の企業支援制度"},[("NHK",self.source)],model_call=ai)
        self.assertEqual(result,self.original)
        self.assertEqual(len(calls),2)

    def test_accepts_original_ai_draft(self):
        def ai(payload):
            self.assertIn("独自原稿",payload["messages"][-1]["content"])
            return {"message":{"content":
                    __import__("json").dumps({"summary":self.original,"basis":"制度創設"},ensure_ascii=False)}}
        result=editorial.write_original_brief(
            {"title":"政府は支援制度を発表"},[("NHK",self.source)],model_call=ai)
        self.assertEqual(result,self.original)


if __name__=="__main__":
    unittest.main()
