#!/usr/bin/env python3
"""Produce a public, facts-only morning briefing. No credentials, paid APIs, or user data."""
import datetime as dt
import html
import concurrent.futures
import email.utils
import textwrap
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
CITIES = {"川口市": (35.807, 139.724), "品川区": (35.610, 139.730)}
WEATHER_CODE = {0: "快晴", 1: "晴れ", 2: "晴れ時々くもり", 3: "くもり", 45: "霧", 48: "霧"}
SONGS = [
    ("plenty", "白い光", "静かな情感とギターの余韻が魅力の曲"),
    ("andymori", "革命", "まっすぐな疾走感とメロディーが印象的な曲"),
    ("LAMP IN TERREN", "緑閃光", "熱量のあるギターロックが好きな人へ"),
    ("People In The Box", "聖者たち", "独特な音の構成を楽しみたい朝に"),
    ("GOOD ON THE REEL", "素晴らしき今日の始まり", "言葉とメロディーが響く一曲"),
    ("Czecho No Republic", "Amazing Parade", "軽快なリズムを楽しめるポップロック"),
    ("cinema staff", "西南西の虹", "鋭いギターとドラマチックな展開"),
    ("mol-74", "ヘルツ", "透明感のある歌声と浮遊感"),
]
# Previously recommended: deliberately never draw from this set.
# Selection rotates rather than pretending to know the full 2,500+ track CSV.
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MYMorningRadio/1.0; +https://github.com/Hiroki120530/my-morning-radio)", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=18) as res:
        return res.read()

def get_json(url, params):
    return json.loads(fetch(url + "?" + urllib.parse.urlencode(params)).decode("utf-8"))

def weather_name(code):
    if code in WEATHER_CODE: return WEATHER_CODE[code]
    if code in (51,53,55,56,57): return "霧雨"
    if code in (61,63,65,66,67,80,81,82): return "雨"
    if code in (71,73,75,77,85,86): return "雪"
    if code in (95,96,99): return "雷雨"
    return "変わりやすい天気"

def forecast(city, lat, lon, today):
    j = get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "Asia/Tokyo",
        "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "start_date": today, "end_date": today,
    })
    h = j["hourly"]
    samples = []
    for i, iso in enumerate(h["time"]):
        hour = int(iso[11:13])
        if hour in (7,12,18,21):
            samples.append({"hour": hour, "temp": round(h["temperature_2m"][i]),
              "rain": round(h["precipitation_probability"][i]), "weather": weather_name(h["weather_code"][i]),
              "wind": round(h["wind_speed_10m"][i])})
    daily = j["daily"]
    if len(samples) != 4: raise ValueError("Weather hourly data incomplete")
    return {"city": city, "hours": samples, "low": round(daily["temperature_2m_min"][0]),
      "high": round(daily["temperature_2m_max"][0]),
      "rain_max": round(daily["precipitation_probability_max"][0])}

def clean_news_text(raw):
    """Normalize editorial text without injecting unverified context."""
    raw = html.unescape(re.sub(r"<[^>]+>", " ", str(raw or "")))
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def news_article(item):
    """Extract factual body from a publisher article, not an RSS headline."""
    url = item["url"]
    try:
        response = fetch(url)
        if len(response) > 2_400_000:
            return ""
        article = ""
        try:
            import trafilatura
            article = trafilatura.extract(response, include_comments=False, include_tables=False,
                                         favor_precision=False, deduplicate=True, url=url)
            article = clean_news_text(article)
        except Exception as parse_error:
            print(f'NEWS DIAGNOSTIC extractor issue: {type(parse_error).__name__}: {parse_error}', flush=True)
        if len(article) < 250:
            # Many modern news sites hydrate pages with JSON-LD, or have
            # article paragraphs that generic extractors fail to recognize.
            from bs4 import BeautifulSoup
            import json as jsonlib
            doc = BeautifulSoup(response, "html.parser")
            for node in doc.select('script[type="application/ld+json"]'):
                try:
                    payload = jsonlib.loads(node.string or node.get_text())
                    blocks = payload if isinstance(payload, list) else [payload]
                    for block in blocks:
                        if isinstance(block,dict) and isinstance(block.get("articleBody"),str):
                            article = max(article,clean_news_text(block["articleBody"]),key=len)
                except (ValueError,TypeError):
                    continue
            p_text = " ".join(p.get_text(" ",strip=True) for p in
                       doc.select("article p, main p, [itemprop=articleBody] p")[:24])
            article = max(article,clean_news_text(p_text),key=len)
        article = re.sub(r"(関連記事|関連ニュース|シェアする|記事をシェア).*", "", article)
        return article[:3000]
    except Exception as exc:
        print(f'NEWS DIAGNOSTIC article inaccessible: {item["source"]} {type(exc).__name__}: {str(exc)[:110]}', flush=True)
        return ""


# Text that belongs to website navigation, advertising or product promotion,
# not the subject of a news report. Exclude before summarization and reject
# any final script containing these fragments.
NEWS_BOILERPLATE = (
    "地図から選ぶ", "NHK ONE", "どなたでもご利用になれます",
    "エリアから選ぶ", "カテゴリから選ぶ", "地域から選ぶ",
    "新規会員登録", "ログイン", "マイページ", "アクセスランキング",
    "この記事をシェア", "この記事に関する", "ご利用いただけます",
    "プライバシーポリシー", "利用規約", "サイトマップ",
    "Cookie", "クッキーを使用", "アプリで読む", "関連記事",
    "掲載記事", "もっと見る", "動画を見る", "広告を表示",
    "すべてのニュース", "ニュースを検索", "番組表",
)
META_SENTENCES = (
    "ここまでが、公開記事から確認できた内容です。",
    "詳しい内容は画面のニュース欄から確認できます。",
    "記事本文を検証した解説ではないので",
)


def _words(text):
    """Meaningful title terms, weighted to avoid unrelated page furniture."""
    return set(re.findall(r"[一-龯]{2,}|[ァ-ヴー]{3,}|[a-zA-Z]{4,}|[0-9]{2,}", text))


def article_brief(article, title=""):
    """Create a short *conservative* audio brief from actual article facts.

    This is a free deterministic summarizer, not an LLM. It removes page
    furniture, ranks factual sentences, and makes a short original connective
    narrative without inventing causes or consequences. Keep source excerpts
    brief to avoid merely reading the publisher's entire article.
    """
    title_terms = _words(title)
    text = html.unescape(article or "")
    # Some sites return page furniture without newlines or full stops. Cut
    # paragraphs before promoting candidate sentences.
    for garbage in META_SENTENCES:
        text = text.replace(garbage, " ")
    sentences = re.split(r"(?<=[。！？!?])\s*|[\r\n]+", text)
    candidates = []
    for index, raw in enumerate(sentences):
        s = re.sub(r"\\s+", " ", raw).strip(" ・-　")
        if not (27 <= len(s) <= 185):
            continue
        if any(term.casefold() in s.casefold() for term in NEWS_BOILERPLATE) or VISUAL_TEASER.search(s):
            continue
        if re.search(r"(Copyright|All Rights Reserved|©|シェア|提供しています|ブラウザー|ログイン|アプリをダウンロード)", s, re.I):
            continue
        # Article text often has fragments without context. Only keep
        # reasonably complete prose sentences ending with Japanese punctuation.
        if not s.endswith(("。", "！", "？")):
            continue
        if re.search(r"(こちら|以下|上記|下記|このページ|ここをクリック)", s):
            continue
        tokens = _words(s)
        shared = len(title_terms & tokens)
        if title_terms and shared == 0 and index > 4:
            continue
        facts = len(re.findall(r"[0-9０-９]+(?:年|月|日|人|件|円|％|%|回|社|倍|度)", s))
        score = shared * 4 + facts * 1.5 + (2 if index < 3 else 0) - index * 0.18
        candidates.append((score, index, s))
    if not candidates:
        return ""
    candidates.sort(key=lambda row: (-row[0], row[1]))
    chosen = []
    for _, index, s in candidates:
        if any(s[:28] == existing[1][:28] or len(_words(s) & _words(existing[1])) >= max(5, len(_words(s)) * 0.75)
               for existing in chosen):
            continue
        chosen.append((index, s))
        if len(chosen) == 3:
            break
    if len(chosen) < 2:
        return ""
    chosen.sort()
    # Brief enough to summarize, not to perform full-article reading.
    # Prefix is original and provides a seamless narration. Editors should
    # later replace this heuristic with an actual local Japanese summarizer.
    snippet = " ".join(s for _,s in chosen)[:235].rstrip("、。 ")
    if len(snippet) < 85:
        return ""
    brief = snippet + "。"
    if any(word.casefold() in brief.casefold() for word in NEWS_BOILERPLATE + META_SENTENCES):
        return ""
    return brief


def feed_entries():
    feeds = [
        ("NHK", "https://news.web.nhk/n-data/conf/na/rss/cat0.xml"),
        ("NHK国際", "https://news.web.nhk/n-data/conf/na/rss/cat6.xml"),
        ("BBC日本語", "https://feeds.bbci.co.uk/japanese/rss.xml"),
        ("Yahoo主要", "https://news.yahoo.co.jp/rss/topics/top-picks.xml"),
        ("ITmedia", "https://news.yahoo.co.jp/rss/media/zdn_n/all.xml"),
    ]
    batches = []
    for publisher,url in feeds:
        try:
            root = ET.fromstring(fetch(url))
        except Exception:
            continue
        current = []
        for row in root.findall(".//channel/item")[:12]:
            title = clean_news_text(row.findtext("title"))[:160]
            link = clean_news_text(row.findtext("link"))
            description = clean_news_text(row.findtext("description"))[:700]
            if not title or not link.startswith("https://"):
                continue
            current.append({"title":title,"url":link,"source":publisher,
                            "published":clean_news_text(row.findtext("pubDate")),
                            "feed_summary":description})
        if current: batches.append(current)
    # Interleave sources: don't let a single broadcaster use all 16 slots.
    result = []
    for index in range(12):
        for batch in batches:
            if index < len(batch): result.append(batch[index])
    return result


# Audio-first editorial gate. A visual teaser is not an audio news story.
# Require a concrete development with a subject and a real-world consequence.
VISUAL_TEASER = re.compile(
    r"(?:【|\[)\s*(?:動画|映像|写真|画像|フォト|ライブ配信|写真特集|動画あり)"
    r"|上空から見た|写真で見る|画像で見る|映像で見る|動画で見る"
    r"|どんな姿|どんな様子|どんな景色|どんな光景"
    r"|(?:見て|ご覧)ください|フォトギャラリー|ビジュアル|総集編",
    re.I,
)
LOW_VALUE_TITLE = re.compile(
    r"(?:とは[？?]?$|は[？?]?$|どうなる[？?]?$|何が[？?]?$|まとめてみた"
    r"|ランキング|トップ[0-9０-９]+|話題の[0-9０-９]+選"
    r"|お楽しみください|クイズ|チェックして|オフショット)",
    re.I,
)
# Reject purely illustrative, speculative, or promotional headlines.
NEWS_ACTIONS = re.compile(
    r"発表|決定|可決|成立|施行|実施|開始|導入|改正|変更|停止"
    r"|中止|再開|逮捕|起訴|判決|捜査|事故|火災|地震|津波|台風"
    r"|被害|発生|増加|減少|上昇|下落|値上げ|値下げ|引き上げ"
    r"|引き下げ|合意|締結|協議|辞任|就任|選出|勝利|敗北"
    r"|公開|発売|提供|撤退|買収|資金調達|調査|判明|確認|完成"
    r"|開通|通行止め|運休|制限|対象|拡大|縮小|更新|警告"
)
SOCIETAL_IMPACT = re.compile(
    r"政府|国会|省庁|自治体|法律|税|経済|企業|市場|物価"
    r"|金利|賃金|給与|保険|医療|教育|交通|鉄道|電車|航空"
    r"|電力|電気|通信|サイバー|情報漏えい|AI|人工知能"
    r"|感染|災害|死者|負傷|選挙|首相|大統領|外交|戦争"
    r"|研究|科学|気象|地震|速報|世界|国内|全国|関東"
)
PROMO_ONLY = re.compile(r"ご覧|紹介|見どころ|見せる|披露|特集|探訪|散歩|写真|映像|中継")

def editorial_score(item):
    """Hard rejection before fetch + transparent, conservative topic scoring."""
    title = clean_news_text(item.get("title", ""))
    if len(title) < 15 or VISUAL_TEASER.search(title) or LOW_VALUE_TITLE.search(title):
        return -1
    if PROMO_ONLY.search(title) and not NEWS_ACTIONS.search(title):
        return -1
    action = bool(NEWS_ACTIONS.search(title))
    impact = bool(SOCIETAL_IMPACT.search(title))
    if not action:
        return -1
    # Topic importance before source position: don't pick the first four items.
    return (4 if impact else 0) + (3 if action else 0) + (2 if re.search(r"[0-9０-９]", title) else 0)


def useful_news(item, detail):
    """Never air a story solely because an HTML page produced text."""
    if editorial_score(item) < 0 or len(detail) < 80:
        return False
    if VISUAL_TEASER.search(detail) or any(x in detail for x in NEWS_BOILERPLATE):
        return False
    # Require enough development in the digest itself; visual captions
    # and circular reports do not qualify.
    return bool(NEWS_ACTIONS.search(detail))

def get_news():
    items = feed_entries()
    unique = {}
    for item in items:
        score = editorial_score(item)
        if score < 0:
            continue
        key = re.sub(r"[^一-龯ぁ-んァ-ヶa-z0-9]", "", item["title"].lower())[:32]
        if key not in unique or score > unique[key][0]:
            unique[key] = (score, item)
    # Prefer material developments, not arbitrary order from RSS. Verify
    # full article text for each candidate before reading any of it aloud.
    ranked = sorted(unique.values(), key=lambda x: -x[0])
    candidates = [item for score, item in ranked[:24]]
    if not candidates:
        print("NEWS EDITORIAL: no worthy headline candidates", flush=True)
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        articles = list(pool.map(news_article, candidates))
    detailed = []
    for item, article in zip(candidates, articles):
        detail = article_brief(article, item["title"])
        if not useful_news(item, detail):
            continue
        item["detail"] = detail
        item["verified_article"] = True
        detailed.append(item)
        if len(detailed) >= 4:
            break
    print(f"NEWS EDITORIAL: feed={len(items)} worthy={len(candidates)} aired={len(detailed)}", flush=True)
    return detailed

def apple_preview(artist, title):
    """Read Apple's optional promotional stream URL without downloading the clip."""
    try:
        response = get_json("https://itunes.apple.com/search", {
            "term": artist + " " + title,
            "entity": "song", "media": "music", "country": "JP", "limit": 15,
        })
        def clean(s):
            return re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龯]", "", str(s).casefold())
        for item in response.get("results", []):
            a, t = item.get("artistName", ""), item.get("trackName", "")
            if (clean(artist) in clean(a) or clean(a) in clean(artist)) and (
                clean(title) == clean(t) or clean(title) in clean(t)
            ):
                p, u = item.get("previewUrl"), item.get("trackViewUrl")
                if isinstance(p, str) and p.startswith("https://"):
                    result = {"preview_url": p}
                    if isinstance(u, str) and u.startswith("https://"):
                        result["store_url"] = u
                    return result
    except Exception:
        pass
    return {}


def music(today):
    n = dt.date.fromisoformat(today).toordinal()
    choices = [SONGS[(2*n+i)%len(SONGS)] for i in range(2)]
    results = []
    for a,t,reason in choices:
        song = {"artist":a, "title":t, "reason":reason,
                "url":"https://music.apple.com/jp/search?term="+urllib.parse.quote(a+" "+t)}
        song.update(apple_preview(a,t))
        results.append(song)
    return results

def make_episode(now, weathers, news, songs, warnings):
    day = now.date().isoformat()
    jpday = "月火水木金土日"[now.weekday()]
    spoken = f"{now.year}年{now.month}月{now.day}日、{jpday}曜日"
    sections = [{"title": "オープニング", "text":
      f"おはようございます。{spoken}。マイ・モーニング・ラジオのお時間です。川口と品川のお天気、注目ニュース、今日の予定、そしておすすめ音楽をお届けします。"}]
    texts=[]
    for city in ("川口市", "品川区"):
        w=weathers.get(city)
        if w is None:
            texts.append(f"{city}の天気はデータを取得できませんでした。")
            continue
        seg=f"{city}です。最低気温は{w['low']}度、最高気温は{w['high']}度。"
        for h in w["hours"]:
            seg += f"{h['hour']}時は{h['weather']}。気温{h['temp']}度。降水確率{h['rain']}パーセント。"
        seg += ("折りたたみ傘があると安心です。" if w["rain_max"]>=40 else
                "雨の可能性は比較的小さそうです。")
        texts.append(seg)
    sections.append({"title": "川口・品川の天気", "text": "".join(texts) +
     "朝晩の寒暖差や風に合わせて服装を調整してください。気象警報・注意報は取得していないため、必要な場合は気象庁をご確認ください。"})
    if news:
        # No headline roundup and no templated tail sentence. Each item must
        # be understood through one compact spoken factual digest.
        stories = [item["detail"].strip() for item in news if item.get("detail")]
        intro = "続いて、今日のニュースです。 " + " 続いては、 ".join(stories)
    else:
        intro = ("続いてニュースです。今日は記事本文の確認ができなかったため、"
                 "不確かな内容を読み上げることは控えます。")
    sections.append({"title": "今日のニュース", "text": intro})
    sections.append({"title":"今日の予定とタスク", "text":
      "現在、Googleカレンダーやタスクアプリの自動連携は設定されていません。今日の予定や締切は確認できていないため、予定がないとは断定できません。カレンダーとタスク一覧を確認してください。"})
    for i,s in enumerate(songs,1):
        sections.append({"title":f"おすすめ音楽 {i}曲目", "text":
          f"続いて今日のおすすめ音楽です。{s['artist']}の、{s['title']}。{s['reason']}。"
          "気に入ったら、画面のApple Musicのリンクから再生し、お気に入りへ追加してみてください。ここで一曲、聴いてみましょう。"
          "楽曲は番組の画面から聴いてください。",
          "music_break": True, "song_index": i-1})
    sections.append({"title":"エンディング","text":
      "今日の放送はここまで。天気とニュースは更新されることがあります。最新の情報も確認して、今日もよい一日を。また明日のマイ・モーニング・ラジオでお会いしましょう。"})
    return {"date":day,"generated_at":now.isoformat(), "sections":sections,
      "songs":songs,"weather":weathers,"news":news,"warnings":warnings,
      "sources":[{"name":"Open-Meteo","url":"https://open-meteo.com/"},
                 {"name":"Google News RSS","url":"https://news.google.com/"}],
      "calendar_status":"not_connected"}

def main():
    now=dt.datetime.now(JST); day=now.date().isoformat()
    warnings=[]; weathers={}
    for city,(lat,lon) in CITIES.items():
        try: weathers[city]=forecast(city,lat,lon,day)
        except Exception as exc: warnings.append(f"{city}の天気を取得できませんでした: {type(exc).__name__}")
    try: headlines=get_news()
    except Exception as exc:
        headlines=[]; warnings.append(f"ニュースを取得できませんでした: {type(exc).__name__}")
    if not weathers and not headlines:
        raise RuntimeError("No weather or news retrieved; refusing to publish an empty episode")
    episode=make_episode(now,weathers,headlines,music(day),warnings)
    out=ROOT/"site"/"episode.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(episode,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Generated {day}: {len(weathers)} cities, {len(headlines)} headlines, {len(episode['songs'])} songs")

if __name__=="__main__": main()
