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
    raw = re.sub(r"\\s+", " ", raw)
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


def article_brief(text):
    """Conservative extractive digest: never invent rationale or implications.

    Limit source reuse and keep relevant factual sentences. When the article
    lacks enough substance, do not treat the headline as researched news.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[。！？])", text) if s.strip()]
    sentences = [s for s in sentences if 18 <= len(s) <= 210 and
                 not re.search(r"^(この記事|詳しくは|写真|提供|Copyright|\u00a9|関連|広告|続きを読む)", s)]
    if len(sentences) < 3:
        return ""
    # First factual lead + two later distinct sentences including enough context.
    chosen = []
    for sentence in sentences:
        normalized = re.sub(r"\\W", "", sentence)
        if any(normalized[:22] == re.sub(r"\\W", "", other)[:22] for other in chosen):
            continue
        chosen.append(sentence)
        if len(chosen) >= 4:
            break
    if len(chosen) < 3: return ""
    # Limit reproduction per source: factual extracts only, not full article.
    # Later this should be replaced by a properly licensed local summarizer.
    return " ".join(chosen)[:340].rstrip("、。") + "。"


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


def get_news():
    items = feed_entries()
    print(f'NEWS DIAGNOSTIC feeds={len(items)} first_sources={[x["source"] for x in items[:5]]}', flush=True)
    seen = set()
    candidates = []
    for x in items:
        key = re.sub(r"[^一-龯ぁ-んァ-ヶa-z0-9]", "", x["title"].lower())[:32]
        if key in seen: continue
        seen.add(key)
        candidates.append(x)
    # Full articles are required. Keep this bounded for free GitHub Actions.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        articles = list(pool.map(news_article, candidates[:16]))
    print(f'NEWS DIAGNOSTIC article_lengths={[len(x) for x in articles]} feed_summary_lengths={[len(x["feed_summary"]) for x in candidates[:16]]}', flush=True)
    detailed = []
    for item, article in zip(candidates, articles):
        detail = article_brief(article)
        if len(detail) < 110:
            # Feed snippets aren't enough to pretend to offer full explanation.
            continue
        item["detail"] = detail
        item["verified_article"] = True
        detailed.append(item)
        if len(detailed) >= 4:
            break
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
        intro = "続いてニュースです。今日は、記事本文で内容を確認できたニュースを取り上げます。"
        for idx,item in enumerate(news,1):
            intro += (f"まず{idx}件目。{item['title']}。"
                      f"具体的な内容を見ていきましょう。{item['detail']} "
                      "ここまでが、公開記事から確認できた内容です。")
    else:
        intro = ("続いてニュースですが、現時点では記事本文を十分に確認できませんでした。"
                 "見出しだけで中身を推測することはせず、ニュースの解説は今回はお休みします。")
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
