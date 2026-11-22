#!/usr/bin/env python3
"""Generate a listenable MP3 with no paid API. Service is an unofficial external TTS endpoint."""
import asyncio
import json
from pathlib import Path
import edge_tts

ROOT=Path(__file__).resolve().parents[1]
EPISODE=ROOT/"site"/"episode.json"
AUDIO=ROOT/"site"/"broadcast.mp3"

async def main():
    episode=json.loads(EPISODE.read_text(encoding="utf-8"))
    parts=[]
    for section in episode.get("sections",[]):
        text=section.get("text","").strip()
        if text:parts.append(text)
    if not parts:raise RuntimeError("No speech text; refusing empty MP3")
    # A single file enables reliable native <audio> playback on iPhone,
    # including play/pause, scrubbing and playing with the display locked.
    text="\n\n".join(parts)
    voice="ja-JP-KeitaNeural"
    await edge_tts.Communicate(text,voice,rate="-4%").save(str(AUDIO))
    if AUDIO.stat().st_size<8192:
        raise RuntimeError("Audio too small, likely failed voice generation")
    episode["audio_url"]="broadcast.mp3"
    episode["audio_bytes"]=AUDIO.stat().st_size
    episode["audio_voice"]=voice
    EPISODE.write_text(json.dumps(episode,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Generated podcast MP3: {AUDIO.stat().st_size} bytes")

if __name__=="__main__":asyncio.run(main())
