#!/usr/bin/env python3
"""Create the free daily radio MP3, with original generated intro and quiet BGM.

No commercial songs or copyrighted sound recordings are embedded.
The synthesized music in this file is an original, deterministic motif.
Uses ffmpeg from the GitHub Actions runner and free unofficial edge-tts.
"""
import asyncio
import json
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
EPISODE = ROOT / "site" / "episode.json"
AUDIO = ROOT / "site" / "broadcast.mp3"
RATE = 22050
BPM = 104
BEAT = 60 / BPM
CHORDS = (
    (196.00, 246.94, 293.66, 392.00), # Gmaj
    (164.81, 196.00, 261.63, 329.63), # Cmaj7
    (146.83, 220.00, 293.66, 369.99), # Dsus / B
    (164.81, 220.00, 261.63, 329.63), # Am
)


def generate_original_bgm(path: Path):
    """Create original four-chord plucked instrumental loop (publicly redistributable)."""
    duration = BEAT * 4 * len(CHORDS)
    samples = int(RATE * duration)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        buf = bytearray()
        for n in range(samples):
            t = n / RATE
            bar = int(t / (BEAT * 4)) % len(CHORDS)
            within = t % (BEAT * 4)
            chord = CHORDS[bar]
            # Soft evolving pads create a consistent bed underneath narration.
            pad = sum(
                math.sin(2 * math.pi * f * t + math.sin(t * 0.17) * 0.03)
                for f in (chord[0] / 2, chord[1], chord[2], chord[3])
            ) / 4
            pad *= (0.23 + 0.035 * math.sin(2 * math.pi * t / duration))
            # Round plucky melody, original non-copyrighted note sequence.
            step = int(within / (BEAT / 2))
            note = (0, 2, 1, 3, 2, 1, 3, 2)[step % 8]
            note_time = within % (BEAT / 2)
            env = min(1, note_time / 0.015) * math.exp(-note_time * 7.2)
            f = chord[note] * (2 if step in (3, 7) else 1)
            pluck = env * (math.sin(2 * math.pi * f * t) + 0.18 * math.sin(4 * math.pi * f * t)) * 0.18
            bass = math.sin(2 * math.pi * (chord[0] / 4) * t) * 0.065
            value = math.tanh((pad + pluck + bass) * 1.2)
            # Tiny fade at loop edge reduces audible pops when repeated.
            fade = min(1.0, t / 0.015, (duration - t) / 0.015)
            value *= max(0, fade)
            buf.extend(struct.pack("<h", max(-32767, min(32767, int(value * 32767)))))
        out.writeframes(buf)


def probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(p.stdout.strip())


async def main():
    episode = json.loads(EPISODE.read_text(encoding="utf-8"))
    parts = [section.get("text", "").strip() for section in episode.get("sections", [])]
    text = "\n\n".join(part for part in parts if part)
    if not text:
        raise RuntimeError("No radio script available")
    with tempfile.TemporaryDirectory(prefix="morning-radio-") as temporary:
        scratch = Path(temporary)
        speech_file = scratch / "speech.mp3"
        bgm_file = scratch / "original-morning-theme.wav"
        # Create sections independently so the narrator takes real breathing
        # pauses, rather than one long monotonous paragraph.
        sections = [s for s in episode.get("sections", []) if s.get("text", "").strip()]
        voice = "ja-JP-NanamiNeural"
        section_files = []
        for idx, section in enumerate(sections):
            segment = scratch / f"voice-{idx:02d}.mp3"
            title = section.get("title", "")
            pace = "-3%" if "ニュース" in title else "+1%"
            pitch = "-2Hz" if "ニュース" in title else "+0Hz"
            # A conversational delivery benefits from sentence punctuation;
            # the exact voices offered depend on the free TTS service.
            spoken = section["text"].replace("。", "。 ").replace("、", "、 ")
            await edge_tts.Communicate(spoken, voice, rate=pace, pitch=pitch).save(str(segment))
            if segment.stat().st_size < 1300:
                raise RuntimeError(f"Empty section audio: {idx}")
            section_files.append(segment)

        # Insert a natural 650ms gap between topics. This is a real gap in
        # the MP3, unlike newlines supplied to the TTS engine.
        silence = scratch / "gap.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", "0.65", "-codec:a", "libmp3lame", "-q:a", "4",
                        str(silence)], check=True, timeout=25)
        concat = scratch / "segments.txt"
        sequence = []
        for idx, filename in enumerate(section_files):
            if idx: sequence.append(f"file '{silence.name}'")
            sequence.append(f"file '{filename.name}'")
        concat.write_text("\n".join(sequence)+"\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-ar", "24000", "-ac", "1", "-codec:a", "libmp3lame",
                        "-q:a", "4", str(speech_file)],
                       cwd=scratch, check=True, timeout=120)
        if speech_file.stat().st_size < 8192:
            raise RuntimeError("Failed to generate meaningful speech")
        generate_original_bgm(bgm_file)
        speech_duration = probe_duration(speech_file)
        total_duration = speech_duration + 7.0
        ending = total_duration - 2.4
        # Full intro (~4.5s), ducked BGM behind dialogue, outro swell.
        # All music is made locally and is not a copy of a commercial track.
        filter_complex = (
            "[0:a]volume='if(lt(t,4.3),0.52,"
            f"if(gt(t,{ending:.3f}),0.34,0.095))':eval=frame,"
            f"atrim=duration={total_duration:.3f},"
            "afade=t=in:st=0:d=0.6[music];"
            "[1:a]adelay=4600|4600,volume=1.22[voice];"
            "[music][voice]amix=inputs=2:duration=longest:dropout_transition=0,"
            "alimiter=limit=0.92[out]"
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-stream_loop", "-1", "-i", str(bgm_file),
             "-i", str(speech_file),
             "-filter_complex", filter_complex, "-map", "[out]",
             "-t", f"{total_duration:.3f}",
             "-ar", "44100", "-ac", "2", "-codec:a", "libmp3lame", "-q:a", "4",
             str(AUDIO)], check=True, timeout=150)
        # Create original-narration chapters from the *mixed* MP3. These
        # keep the approved BGM, while allowing the web player to interleave
        # an external, streamed iTunes promotional sample immediately after
        # the song introduction. Commercial previews are NEVER downloaded,
        # cached in our build, or inserted into a downloadable audio file.
        segments_dir = ROOT / "site" / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)
        for stale in segments_dir.glob("section-*.mp3"):
            stale.unlink()
        lengths = [probe_duration(path) for path in section_files]
        playlist = []
        elapsed = 4.6
        for idx, section in enumerate(sections):
            # The first section includes the original opening instrumental.
            begin = 0 if idx == 0 else elapsed
            length = lengths[idx] + (4.6 if idx == 0 else 0)
            if idx < len(sections) - 1:
                length += 0.65
            else:
                length += 2.4
            path = segments_dir / f"section-{idx:02d}.mp3"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{begin:.3f}", "-i", str(AUDIO),
                "-t", f"{length:.3f}", "-ac", "2", "-ar", "44100",
                "-codec:a", "libmp3lame", "-q:a", "5", str(path),
            ], check=True, timeout=45)
            if path.stat().st_size < 800:
                raise RuntimeError(f"Missing chapter audio {idx}")
            playlist.append({"type":"narration", "section_index":idx,
                             "url":f"segments/section-{idx:02d}.mp3"})
            elapsed += lengths[idx] + (0.65 if idx < len(sections) - 1 else 0)
            if section.get("music_break"):
                song_i = section.get("song_index")
                if isinstance(song_i,int) and 0<=song_i<len(episode.get("songs",[])):
                    song = episode["songs"][song_i]
                    if str(song.get("preview_url","")).startswith("https://"):
                        playlist.append({"type":"official_preview", "song_index":song_i,
                                         "url":song["preview_url"]})
        episode["playlist"] = playlist
        episode["playback_mode"] = "in_page_radio_with_promotional_previews"
        print(f"Prepared {len(sections)} narrated chapters and {sum(x['type']=='official_preview' for x in playlist)} official song previews")
    if AUDIO.stat().st_size < 16384:
        raise RuntimeError("Final MP3 is unexpectedly small")
    episode.update(
        audio_url="broadcast.mp3",
        audio_bytes=AUDIO.stat().st_size,
        audio_voice="ja-JP-NanamiNeural",
        original_music="Original synthesized morning theme, generated by this project's code",
        audio_format="mp3",
    )
    EPISODE.write_text(json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created broadcast with original intro/BGM: {AUDIO.stat().st_size} bytes")


if __name__ == "__main__":
    asyncio.run(main())
