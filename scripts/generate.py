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
# Discovery artist pool is maintained in data/discovery_artists.json.
# The private 2,515-track favorites CSV is not stored in this public repo.
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
        # Avoid discarding a sentence's ending during page-size capping.
        if len(article) > 3000:
            end = max(article.rfind(mark, 0, 3000) for mark in ("。", "！", "？"))
            article = article[:end + 1] if end >= 500 else article[:3000].rsplit(" ", 1)[0]
        return article
    except Exception as exc:
        print(f'NEWS DIAGNOSTIC article inaccessible: {item["source"]} {type(exc).__name__}: {str(exc)[:110]}', flush=True)
        return ""


# Text that belongs to website navigation, advertising or product promotion,
# not the subject of a news report. Exclude before summarization and reject
# any final script containing these fragments.
NEWS_BOILERPLATE = (
    "地図から選ぶ", "NHK ONE", "どなたでもご利用になれます",
    "受信契約がお済み", "契約をされていない世帯",
    "別途の契約や追加のご負担", "放送法に基づき契約",
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


def feed_entries():
    feeds = [
        ("NHK", "https://news.web.nhk/n-data/conf/na/rss/cat0.xml"),
        ("NHK国際", "https://news.web.nhk/n-data/conf/na/rss/cat6.xml"),
        ("BBC日本語", "https://feeds.bbci.co.uk/japanese/rss.xml"),
        ("Yahoo主要", "https://news.yahoo.co.jp/rss/topics/top-picks.xml"),
        ("Yahoo国内", "https://news.yahoo.co.jp/rss/topics/domestic.xml"),
        ("Yahoo国際", "https://news.yahoo.co.jp/rss/topics/world.xml"),
        ("Yahoo経済", "https://news.yahoo.co.jp/rss/topics/business.xml"),
        ("ITmedia", "https://news.yahoo.co.jp/rss/media/zdn_n/all.xml"),
    ]
    batches = []
    for publisher,url in feeds:
        try:
            root = ET.fromstring(fetch(url))
        except Exception:
            continue
        current = []
        for row in root.findall(".//channel/item")[:22]:
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
    for index in range(22):
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


def topic_fingerprint(title):
    """Character trigrams catch variants of the same event without paid NLP."""
    title = re.sub(r"【[^】]+】|\[[^\]]+\]", " ", title)
    title = re.sub(r"\s+", "", title.lower())
    chunks = re.findall(r"[一-龯ぁ-んァ-ヴーa-z0-9]{3,}", title)
    grams = set()
    for chunk in chunks:
        grams.update(chunk[i:i+3] for i in range(len(chunk)-2))
    # Common ngrams across unrelated stories must not determine a match.
    return {g for g in grams if g not in {
        "につい", "について", "として", "したこ", "してい", "という",
        "明らか", "発表し", "関する", "国内で", "新たな", "ことが",
        "始まる", "行われ", "に向け", "政府は", "による",
    }}


def same_topic(left, right):
    """Conservative grouping: similar unique phrasing, not merely broad area."""
    a = topic_fingerprint(left)
    b = topic_fingerprint(right)
    if not a or not b:
        return False
    shared = a & b
    return len(shared) >= 3 and len(shared) / min(len(a), len(b)) >= 0.27


def topic_groups(items, max_topics=12):
    """Turn article headlines into topics; attach other publishers' coverage."""
    ranked = sorted((item for item in items if editorial_score(item) >= 0),
                    key=lambda x: editorial_score(x), reverse=True)
    groups = []
    def publisher_family(source):
        if source.startswith("Yahoo"): return "Yahoo"
        if source.startswith("NHK"): return "NHK"
        return source
    for item in ranked:
        group = next((g for g in groups if same_topic(g[0]["title"], item["title"])), None)
        if group is None:
            if len(groups) < max_topics:
                groups.append([item])
        elif not any(publisher_family(other["source"]) == publisher_family(item["source"])
                     for other in group):
            group.append(item)
    # A subject with independent reporting is preferred, but not required.
    groups.sort(key=lambda group: (-(1 if len(group)>1 else 0),
                                   -editorial_score(group[0])))
    return groups


def get_news():
    """Select topics, research articles, and let local AI write fresh narration.

    The source article sentences never become the aired script. If the
    independent editor or original-writing checks fail, omit that story.
    """
    try:
        from scripts.editorial import write_original_brief
    except ModuleNotFoundError:
        from editorial import write_original_brief
    items = feed_entries()
    groups = topic_groups(items, max_topics=13)
    # Prefer topics independently reported by more than one publisher.
    ranked = sorted(groups, key=lambda group: (
        -(len({item["source"] for item in group}) >= 2),
        -editorial_score(group[0]),
    ))
    candidates = [item for group in ranked[:9] for item in group[:2]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        articles = list(pool.map(news_article, candidates))
    by_url = {item["url"]: article for item, article in zip(candidates, articles)}
    stories = []
    for group in ranked[:9]:
        evidence = []
        for item in group[:2]:
            body = by_url.get(item["url"], "")
            if len(body) >= 180:
                evidence.append((item["source"], body))
        if not evidence:
            continue
        detail = write_original_brief(group[0], evidence)
        if not detail:
            continue
        story = dict(group[0])
        story["detail"] = detail
        story["source_count"] = len(evidence)
        story["editorial_method"] = "local_ai_original"
        story["verified_article"] = True
        story["checked_sources"] = [
            {"name": item["source"], "url": item["url"]}
            for item in group[:2] if by_url.get(item["url"], "")
        ]
        stories.append(story)
        if len(stories) >= 4:
            break
    print(f"NEWS EDITORIAL: feed={len(items)} topics={len(groups)} "
          f"aired={len(stories)} multireported={sum(x['source_count']>1 for x in stories)}",
          flush=True)
    return stories


def music(today):
    """Select two verified preview tracks from artists absent in favorites."""
    try:
        from scripts.recommend import daily_recommendations
    except ModuleNotFoundError:
        from recommend import daily_recommendations
    return daily_recommendations(today, get_json)

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
    if songs:
        for i,s in enumerate(songs,1):
            sections.append({"title":f"おすすめ音楽 {i}曲目", "text":
              f"ここからは音楽の時間です。{s['artist']}の、{s['title']}。"
              f"{s['reason']}。それでは、試聴してみましょう。",
              "music_break": True, "song_index": i-1})
    else:
        sections.append({"title":"今日の音楽", "text":
          "今日は再生できる公式試聴音源が見つからなかったので、音楽の紹介は見送ります。"})
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
