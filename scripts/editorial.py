#!/usr/bin/env python3
"""Free local AI news editor. It writes NEW Japanese narration, never excerpts.

Runs on the GitHub Actions machine with a CPU-only local language model.
No external generative API, personal data, or credentials.

Contract: news article material is ONLY evidence. Never reproduce it as the
podcast script. If original writing or evidence checks fail, OMIT the item.
"""
import json
import os
import re
import urllib.error
import urllib.request
from difflib import SequenceMatcher

MODEL = os.getenv("RADIO_EDITOR_MODEL", "qwen3.5:2b")
OLLAMA_URL = os.getenv("RADIO_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")

# Navigation, broadcaster service instructions and clickbait must never be
# mistaken for news. This includes the actual NHK contract notice that leaked.
NON_NEWS = (
    "受信契約がお済み", "契約をされていない世帯", "別途の契約",
    "追加のご負担", "放送法に基づき契約", "NHK ONE",
    "地図から選ぶ", "新規会員登録", "サイトマップ", "関連記事",
    "会員登録", "ログイン", "プライバシーポリシー",
    "クッキーを利用", "アクセスランキング", "記事をシェア",
    "この記事をシェア", "詳しくはこちら", "もっと見る",
    "見逃し配信", "サイトをご利用", "番組表", "ご利用いただけます",
    "サービスをご利用", "アプリをダウンロード",
)
JUNK_SENTENCE = re.compile(
    r"(?:利用規約|受信契約|新規会員|ログイン|シェア|クッキー|"
    r"ご利用|サービスの利用|アプリから|サイトから|会員登録|"
    r"関連記事|こちらをクリック|閲覧いただけ|個人情報)"
)
SENSATIONAL_AND_SPECULATIVE = (
    "意外と", "実は", "驚きの", "話題を集めて", "注目を集めて",
    "今後が注目", "といえるでしょう", "かもしれません", "考えられます",
    "可能性があります", "大きな影響を与えるでしょう",
)
BAD_HEADLINE_END = re.compile(
    r"(?:[一-龯]$|疑い$|可能性$|見通し$|予定$|とのこと$|発表へ$)"
)
BAD_END = re.compile(r"(?:[はがをにへでと]|について|として|により|ため|など|"
                     r"発表|決定|予定|見込み|可能性|対策|対応)$")

SYSTEM = """あなたは日本語の朝のニュース番組の編集者です。
与えられた複数の報道記事を読み、何が起きたか、確実に分かる背景、社会への関係を理解した上で、完全に自分の文章で新しいニュース原稿を書いてください。

厳守:
- 記事の文章を抜き出さない。元記事の文章の語順・表現を真似しない。引用・コピペ禁止。
- 読者ではなく耳で聞くリスナー向け。自然な日本語で3〜5文、約130〜240字。
- 初めに何が起きたか。次に確認された詳細。重要性は報道の事実から説明できる場合だけ。感想や憶測を加えない。
- 「2人逮捕。」「発表。」「被害拡大。」などの見出し調の文を絶対に使わない。すべて「逮捕されました。」「発表しました。」など述語で完結させる。
- 「意外と」「実は」「注目されます」「考えられます」など主観、根拠のない解釈、抽象的な結びを加えない。
- 少なくとも報道された発表・決定・事件等を具体的に伝える。曖昧な一般論は不要。
- 指定の資料に書かれていない日付、数字、原因、影響は絶対に作らない。
- サイトのナビゲーション、NHKの受信契約案内や会員登録など放送サービスの宣伝はニュースではない。原稿に入れない。
- 記事に元々ない結論を補わず、裏付けのない話は原稿にしない。
- 見出し読み上げのみ、動画紹介、直接のサイト誘導は禁止。
- 括弧を一切使わない。日本語の送り仮名を正しく書き、文章を途中で切らない。
- JSONのみ: {"summary":"日本語で新しく執筆した原稿","basis":"中心となる確認済みの事実を短く1文"}
- 資料が不足している場合は summary を空文字にする。
"""


def clean_evidence(article, limit=1800):
    """Strip obvious page furniture before feeding facts to the model."""
    text = re.sub(r"\s+", " ", str(article or "")).strip()
    chunks = re.split(r"(?<=[。！？!?])\s*", text)
    kept = []
    total = 0
    for chunk in chunks:
        sentence = chunk.strip()
        if len(sentence) < 18 or len(sentence) > 290:
            continue
        if any(term in sentence for term in NON_NEWS) or JUNK_SENTENCE.search(sentence):
            continue
        if re.search(r"(Copyright|All Rights Reserved|©|https?://|Cookies)", sentence, re.I):
            continue
        if total+len(sentence)>limit:
            break
        kept.append(sentence)
        total += len(sentence)
    return " ".join(kept)


def shared_passage(text, source, min_chars=32):
    """Detect near-verbatim passage reuse, including with extra spaces."""
    norm = re.sub(r"\s+", "", text)
    src = re.sub(r"\s+", "", source)
    if len(norm) < min_chars or len(src) < min_chars:
        return False
    match = SequenceMatcher(None, norm, src, autojunk=False).find_longest_match(
        0, len(norm), 0, len(src))
    return match.size >= min_chars


def review_script(script, evidence, title=""):
    """Objective checks only: not a substitute for full human fact checking."""
    if not isinstance(script, str):
        return ["not_text"]
    script = re.sub(r"\s+", "", script)
    errors = []
    if not 90 <= len(script) <= 310:
        errors.append("incorrect_length")
    if any(term in script for term in NON_NEWS) or JUNK_SENTENCE.search(script):
        errors.append("website_or_contract_copy")
    if any(mark in script for mark in "()（）【】"):
        errors.append("non_audio_brackets")
    if not script.endswith(("。", "！", "？")):
        errors.append("unfinished")
    for sentence in re.split(r"(?<=[。！？])", script):
        if not sentence.strip():
            continue
        stem = sentence.strip().rstrip("。！？")
        if BAD_END.search(stem) or BAD_HEADLINE_END.search(stem):
            errors.append("unnatural_sentence_end")
            break
    if any(word in script for word in SENSATIONAL_AND_SPECULATIVE):
        errors.append("unsupported_speculation_or_editorializing")
    if len(re.findall(r"[。！？]", script)) < 3:
        errors.append("insufficient_explanation")
    if re.search(r"(詳しくは|リンク先|記事によると|続きをご覧)", script):
        errors.append("link_or_article_reference")
    if not evidence:
        errors.append("no_evidence")
    if any(shared_passage(script, excerpt) for excerpt in evidence):
        errors.append("copied_source_wording")
    # Numbers in narration must have appeared in one source. Skip word-based
    # dates ("来年") because they cannot be verified mechanically.
    quoted_numbers = set(re.findall(r"[0-9０-９]+(?:[.,．][0-9０-９]+)?", script))
    source_numbers = set(re.findall(
        r"[0-9０-９]+(?:[.,．][0-9０-９]+)?", " ".join(evidence)))
    if quoted_numbers - source_numbers:
        errors.append("unsupported_number")
    return sorted(set(errors))


def ollama_write(headline, articles, call=None, feedback=''):
    """Generate a first-draft JSON response from the locally running model."""
    if call is None:
        def call(payload):
            req = urllib.request.Request(
                OLLAMA_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=170) as response:
                return json.load(response)
    bundle = "\n".join(
        f"報道資料{i+1} / {name}\n{body}"
        for i,(name,body) in enumerate(articles)
    )
    payload = {
        "model":MODEL, "stream":False, "think":False, "format":"json",
        "options":{"temperature":0.3,"num_ctx":4096,"num_predict":470},
        "messages":[
            {"role":"system","content":SYSTEM},
            {"role":"user","content":"注目する話題: "+headline+"\n\n"+bundle+
             "\n\nこの資料から確認できる事実だけで、原文と異なる自然な日本語の独自原稿を書いてください。"
             "省略しすぎず、出来事、裏付けとなる詳細、意味が分かる順番で3〜5つの完結した文にしてください。"
             + ("\n前稿が不合格でした。"+feedback+" 同じ文章を出さず一から書き直してください。" if feedback else "")}
        ]
    }
    result = call(payload)
    response = result.get("message",{}).get("content","")
    return json.loads(response).get("summary","")


def write_original_brief(item, articles, model_call=None):
    """Require strong evidence and an original script or skip the story."""
    evidence=[]
    for source, body in articles:
        cleaned=clean_evidence(body)
        if len(cleaned)>=125:
            evidence.append((source,cleaned))
    if not evidence:
        return ""
    last_errors=[]
    for attempt in range(2):
        try:
            script=ollama_write(
                item.get("title",""),evidence,call=model_call,
                feedback="不自然、原文と近すぎる、または説明が短すぎます。別の言い回しで3〜5文、約150〜230字にしてください。"
                if attempt else ""
            ).strip()
        except (ValueError,KeyError,TypeError,urllib.error.URLError,TimeoutError) as exc:
            print("NEWS EDITOR: local model unavailable:",type(exc).__name__,flush=True)
            return ""
        last_errors=review_script(script,[x[1] for x in evidence],item.get("title",""))
        if not last_errors:
            return script
    print("NEWS EDITOR: story rejected",last_errors,item.get("title","")[:60],flush=True)
    return ""
