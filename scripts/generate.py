#!/usr/bin/env python3
"""Produce a public, facts-only morning briefing. No credentials, paid APIs, or user data."""
import datetime as dt
import html
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
    req = urllib.request.Request(url, headers={"User-Agent": "MY-MORNING-RADIO/1.0"})
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

def get_news():
    url = "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"
    root = ET.fromstring(fetch(url))
    items = []
    for item in root.findall(".//channel/item")[:25]:
        raw = html.unescape(item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not raw or not link.startswith("https://"): continue
        publisher = item.findtext("source") or "配信元未確認"
        published = item.findtext("pubDate") or ""
        items.append({"title": re.sub(r"\s+", " ", raw)[:160],
                      "source": publisher[:80], "published": published, "url": link})
    return items[:5]

def music(today):
    n = dt.date.fromisoformat(today).toordinal()
    choices = [SONGS[(2*n+i)%len(SONGS)] for i in range(2)]
    return [{"artist": a, "title": t, "reason": reason,
             "url": "https://music.apple.com/jp/search?term=" + urllib.parse.quote(a+" "+t)}
            for a,t,reason in choices]

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
        intro = "続いてニュースです。注目の話題をお届けします。詳しい内容は画面のニュース欄から確認できます。"
        for idx,item in enumerate(news,1):
            intro+=f"{idx}件目。{item['title']}。"
    else: intro="今日のニュースは情報を取得できなかったため、未確認の見出しを補って紹介することはしません。"
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
