#!/usr/bin/env python3
"""play-along: turn any song into a falling-notes play-along video and an interactive practice player.

  python play.py --input song.mp3
  python play.py --input "https://www.youtube.com/watch?v=..." --start 30 --end 90
  python play.py --rerender results/song --solo piano --speed 0.75     # new video from an existing run, no model
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

from play_along.media import fetch, is_url, title_of, to_wav, to_web_audio
from play_along.render import Style, render_video
from play_along.song import Song


def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()[:60] or "song"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Any song -> falling-notes play-along video + practice player.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", "-i", help="audio/video file or a link (YouTube, SoundCloud, ...)")
    src.add_argument("--rerender", metavar="DIR", help="reuse notes.json from an earlier run (no transcription)")
    ap.add_argument("--start", type=float, default=0.0, help="start of the part to use, in seconds")
    ap.add_argument("--end", type=float, default=None, help="end of the part to use, in seconds")
    ap.add_argument("--title", default="", help="title shown in the video (default: file name or video title)")
    ap.add_argument("--solo", action="append", help="highlight only this instrument (repeatable, partial names ok)")
    ap.add_argument("--speed", type=float, default=1.0, help="practice speed for the video, e.g. 0.75 (pitch is kept)")
    ap.add_argument("--size", default="1280x720", help="video size, e.g. 1920x1080 or 1080x1080")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--no-video", action="store_true", help="only notes, MIDI and the player")
    ap.add_argument("--no-hand-split", action="store_true", help="keep the piano as one track when it is the only pitched instrument")
    ap.add_argument("--output", "-o", default="results", help="output folder (default: results/)")
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    a = ap.parse_args(argv)

    w, h = (int(x) for x in a.size.lower().split("x"))
    style = Style(width=w, height=h, fps=a.fps)

    if a.rerender:
        out = Path(a.rerender)
        song = Song.load(out / "notes.json")
        wav = out / "audio.mp3"
        if not a.no_hand_split and song.split_hands():
            song.save(out / "notes.json")
            _write_midi(song, out / "song.mid")
            print("[play-along] piano is the only pitched instrument: split into right and left hand at middle C", flush=True)
    else:
        title = a.title or title_of(a.input)
        out = Path(a.output) / slug(title if is_url(a.input) else Path(a.input).stem)
        out.mkdir(parents=True, exist_ok=True)
        print(f"[play-along] {a.input}", flush=True)
        src_file = fetch(a.input, Path("cache") / "downloads")
        wav = to_wav(src_file, out / "audio.wav", a.start, a.end)
        from play_along.transcribe import transcribe
        t0 = time.time()
        song = transcribe(wav, title=title, device=a.device)
        print(f"[play-along] transcribed {song.duration:.0f} s of audio in {time.time() - t0:.0f} s on "
              f"{song.meta.get('device')}", flush=True)
        song.meta["source"] = a.input if is_url(a.input) else Path(a.input).name
        song.meta["start"], song.meta["end"] = a.start, a.end
        if not a.no_hand_split and song.split_hands():
            print("[play-along] piano is the only pitched instrument: split into right and left hand at middle C", flush=True)
        song.save(out / "notes.json")
        _write_midi(song, out / "song.mid")
        to_web_audio(wav, out / "audio.mp3")
        (out / "audio.wav").unlink()
        wav = out / "audio.mp3"
        for tr in song.tracks:
            print(f"    {tr.name:<24} {len(tr.notes):5d} {'hits' if tr.is_drum else 'notes'}")

    video_name = None
    if not a.no_video:
        tag = "".join(f"_{slug(s)}" for s in (a.solo or [])) + (f"_{a.speed:g}x" if a.speed != 1 else "")
        video_name = f"playalong{tag}.mp4"
        t0 = time.time()
        render_video(song, wav, out / video_name, style, solo=a.solo, speed=a.speed,
                     progress=lambda p: print(f"\r[play-along] video {p * 100:4.0f}%", end="", flush=True))
        print(f"\r[play-along] video written in {time.time() - t0:.0f} s -> {out / video_name}", flush=True)

    from play_along.player import write_player
    files = {"audio": "audio.mp3", "midi": "song.mid"}
    if (out / "playalong.mp4").exists():
        files["video"] = "playalong.mp4"
    write_player(song, out, files=files)
    print(f"\n  notes   {out / 'notes.json'}\n  midi    {out / 'song.mid'}\n  player  {out / 'player.html'}  (open in a browser)")
    if video_name:
        print(f"  video   {out / video_name}")


def _write_midi(song: Song, path: Path):
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    for t in song.tracks:
        ins = pretty_midi.Instrument(program=0 if t.is_drum else t.program, is_drum=t.is_drum, name=t.name)
        for on, off, p, v in t.notes:
            ins.notes.append(pretty_midi.Note(velocity=int(v), pitch=int(p), start=float(on), end=float(off)))
        pm.instruments.append(ins)
    pm.write(str(path))


if __name__ == "__main__":
    main()
