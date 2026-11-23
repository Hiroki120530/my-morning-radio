#!/usr/bin/env python3
"""Free, offline Japanese editorial pass between script generation and audio.

This is a conservative *mechanical* proofreader, not an LLM or certified
Japanese grammar checker. It repairs typography and drops dubious news copy.
It never attempts to invent an ending or fill in omitted facts.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE = ROOT / "site" / "episode.json"
END_PUNCT = ("。", "！", "？")
NOISE = (
    "地図から選ぶ", "NHK ONE", "どなたでもご利用になれます",
    "ここまでが、公開記事から確認できた内容です",
    "詳しくはリンク先", "詳しい内容は画面",
    "【動画】", "【写真】", "写真で見る", "上空から見た",
    "サイトマップ", "プライバシーポリシー",
)
# These patterns unambiguously represent an unfinished utterance.
BROKEN_END = re.compile(
    r"(?:[はがをにへでもと]|\b(?:and|or|the)|について|に関して|により|として|"
    r"から|まで|など|という|ため|こと|もの|場合|一方|一部|"
    r"発表|決定|方針|予定|見通し|可能性|理由|影響|対象|制度|"
    r"計画|進展|検討|実施|取り組み|対応|結果|状況|課題|"
    r"報告|説明|公表|確認|開始|終了|改正|修正|変更|情報|"
    r"については)$"
)
TRAILING_MARKS = re.compile(r"[、,，:：／/・\-−—…]+$")
MISSING_KANA_AFTER_VERB_STEM = re.compile(
    r"(?:続|行|受|進|決|取|動|始|終|増|減|見|聞|使|書|読|思|考|作|変|届|呼)$"
)
BRACKETS = {"（":"）","「":"」","『":"』","【":"】","(" : ")"}


ROUND_BRACKETS = re.compile(r"[（(]([^（）()]*)[）)]")
# These annotations can safely be integrated without changing the claim.
SHORT_FORMS = re.compile(r"^[A-Za-z][A-Za-z0-9.-]{1,12}$")
READING_HINT = re.compile(r"^[ぁ-んァ-ヶー・]{2,24}$")
MEANING_HINT = re.compile(r"^[一-龯ぁ-んァ-ヶー・]{2,24}$")
PARENTHETICAL_NOTES = ("以下", "注", "写真", "動画", "出典", "関連", "詳しくは")


def naturalize_parentheses(text):
    """Rewrite limited safe parentheticals; reject anything ambiguous.

    E.g. 'AI（人工知能）' -> '人工知能', '防災（ぼうさい）' -> '防災'.
    Information-heavy parentheticals are sent back to editorial selection,
    not clumsily read with brackets or silently deleted.
    """
    text = str(text or "")
    if not any(symbol in text for symbol in "()（）"):
        return text
    if any(text.count(op) != text.count(cl) for op,cl in (("（","）"),("(",")"))):
        raise ValueError("unbalanced_round_parentheses")
    def replace(match):
        content = match.group(1).strip()
        before = text[:match.start()]
        head = re.search(r"([A-Za-z][A-Za-z0-9.-]{1,15}|[一-龯ぁ-んァ-ヶー]{2,16})$", before)
        if not head or not content or any(x in content for x in PARENTHETICAL_NOTES):
            raise ValueError("ambiguous_parenthetical")
        prefix = head.group(1)
        # Remove simple reading guides, preserving the written noun.
        if READING_HINT.fullmatch(content) and re.search(r"[一-龯]",prefix):
            return ""
        # '人工知能（AI）' -> '人工知能'; the acronym is redundant for listening.
        if SHORT_FORMS.fullmatch(content) and re.search(r"[一-龯]",prefix):
            return ""
        # 'AI（人工知能）' -> '人工知能', easier to follow by ear.
        if SHORT_FORMS.fullmatch(prefix) and MEANING_HINT.fullmatch(content):
            return content
        raise ValueError("ambiguous_parenthetical")
    # For acronym-to-full-name replacement the prefix must also be removed.
    # Deal with this first using a dedicated expression.
    text = re.sub(r"\b[A-Za-z][A-Za-z0-9.-]{1,15}[（(]([一-龯ぁ-んァ-ヶー・]{2,24})[）)]",
                  lambda m: m.group(1),text)
    text = ROUND_BRACKETS.sub(replace,text)
    if any(x in text for x in "()（）"):
        raise ValueError("remaining_round_parentheses")
    return text


def tidy_typography(text):
    """Whitespace and punctuation only: no speculative grammatical edits."""
    text = str(text or "").replace("\u3000", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([。！？])\1+", r"\1", text)
    text = re.sub(r"、{2,}", "、", text)
    text = re.sub(r"\s+([。！？，、])", r"\1", text)
    return text


def defects(text, *, news=False):
    issues = []
    if not text:
        return ["empty"]
    if any(x in text for x in "()（）"):
        issues.append("round_parentheses_in_narration")
    for marker in NOISE:
        if marker in text:
            issues.append("website_furniture:" + marker)
    for op, cl in BRACKETS.items():
        if text.count(op) != text.count(cl):
            issues.append("unbalanced:" + op)
    if not text.endswith(END_PUNCT):
        issues.append("unfinished_line")
    if news:
        for sentence in re.split(r"(?<=[。！？])", text):
            sentence = sentence.strip()
            if not sentence:
                continue
            if not sentence.endswith(END_PUNCT):
                issues.append("unfinished_sentence")
                continue
            stem = sentence[:-1].rstrip()
            if not stem or TRAILING_MARKS.search(stem):
                issues.append("broken_punctuation")
            if BROKEN_END.search(stem):
                issues.append("suspicious_sentence_end:" + stem[-16:])
            if MISSING_KANA_AFTER_VERB_STEM.search(stem):
                issues.append("possible_missing_okurigana:" + stem[-12:])
            if len(sentence) > 200:
                issues.append("sentence_too_long")
    return issues


def validate_and_polish_episode(episode):
    """Return a validated episode and report, before it is turned into MP3.

    Never fix facts by guessing. Reject suspect news stories, keeping a brief
    truthful fallback when necessary. Fail the build if core narration is broken.
    """
    if not episode.get("sections"):
        raise ValueError("Missing audio sections")
    report = {"phase":"japanese_proofreading", "corrected":0,
              "rejected_news":[], "warnings":[]}
    for section in episode["sections"]:
        old = section.get("text","")
        try:
            new = tidy_typography(naturalize_parentheses(old))
        except ValueError:
            # News narration is rebuilt from verified stories below.
            if section.get("title") == "今日のニュース":
                new = ""
            else:
                raise ValueError(f"Ambiguous parentheses in core section: {section.get('title')}")
        if new != old:
            report["corrected"] += 1
        section["text"] = new

    checked_news = []
    for item in episode.get("news",[]):
        old = item.get("detail","")
        try:
            new = tidy_typography(naturalize_parentheses(old))
            errors = defects(new, news=True)
        except ValueError:
            errors = ["ambiguous_parenthetical"]
            new = old
        if errors:
            report["rejected_news"].append({"title":item.get("title",""),"issues":errors})
            continue
        item["detail"] = new
        checked_news.append(item)
    episode["news"] = checked_news
    news_section = next((s for s in episode["sections"] if s.get("title")=="今日のニュース"), None)
    if news_section is None:
        raise ValueError("Missing news section")
    if checked_news:
        news_section["text"] = "続いて、今日のニュースです。 " + " 続いては、 ".join(
            x["detail"] for x in checked_news)
    else:
        news_section["text"] = ("続いてニュースです。今日は十分に確認できたニュース原稿がないため、"
                                "不確かな内容の読み上げは控えます。")
    for section in episode["sections"]:
        errors = defects(section.get("text",""))
        if errors:
            raise ValueError(f"Japanese proofreading failed: {section.get('title')}: {errors}")
    episode["proofreading"] = {"status":"passed", "rejected_news":len(report["rejected_news"]),
                               "typographic_corrections":report["corrected"]}
    return episode, report


def main():
    episode = json.loads(EPISODE.read_text(encoding="utf-8"))
    clean, report = validate_and_polish_episode(episode)
    EPISODE.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"JAPANESE QA PASSED: kept_news={len(clean.get('news',[]))} "
          f"rejected_news={len(report['rejected_news'])} corrected={report['corrected']}")
    if report["rejected_news"]:
        print("JAPANESE QA rejected:", json.dumps(report["rejected_news"],ensure_ascii=False)[:1800])


if __name__=="__main__":
    main()
