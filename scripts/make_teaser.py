#!/usr/bin/env python3
"""Build the demo teaser (demo/teaser.mp4) and README GIF (demo/hero.gif) from finished runs.

    python scripts/make_teaser.py

Shots: title -> full band -> solo one instrument -> solo piano -> half speed -> end card.
Video frames are drawn here; the audio is cut from each song's audio.mp3 with the same timing and joined by ffmpeg."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from play_along.media import _atempo, ffmpeg_exe  # noqa: E402
from play_along.render import Renderer, Style, caption, font  # noqa: E402
from play_along.song import Song  # noqa: E402

W, H, FPS = 1920, 1080, 30


@dataclass
class Shot:
    result: str
    t0: float
    t1: float
    text: str
    solo: Optional[List[str]] = None
    speed: float = 1.0


SHOTS = [
    Shot("results/monkeys_spinning_monkeys", 4.0, 13.0, "Every instrument, its own colour"),
    Shot("results/fluffing_a_duck", 28.6, 36.6, "Solo one part: clarinet", solo=["clarinet"]),
    Shot("results/chopin_nocturne_op9_no2", 0.0, 9.0, "Solo piano? Learn it"),
    Shot("results/sneaky_snitch", 6.0, 10.5, "Slow it down: 0.5×, same pitch", speed=0.5),
]
TITLE_S, END_S, FADE = 3.0, 4.0, 0.25


def card(lines, sub="", accent=""):
    img = Image.new("RGB", (W, H), (13, 15, 28))
    arr = np.array(img).astype(np.float32)
    y = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array([13, 15, 28]) * (1 - y) + np.array([27, 16, 48]) * y)
    img = Image.fromarray(np.repeat(arr, W, axis=1).astype(np.uint8))
    d = ImageDraw.Draw(img)
    cy = H / 2 - 40 * (len(lines) - 1)
    if accent:
        f = font(44)
        tw = d.textlength(accent, font=f)
        x0 = W / 2 - (tw + 46) / 2
        d.polygon([(x0, cy - 140), (x0, cy - 100), (x0 + 32, cy - 120)], fill=(255, 209, 102))
        d.text((x0 + 46, cy - 120), accent, font=f, fill=(255, 209, 102), anchor="lm")
    for i, ln in enumerate(lines):
        d.text((W / 2, cy + i * 92), ln, font=font(78), fill=(255, 255, 255), anchor="mm")
    if sub:
        d.text((W / 2, cy + len(lines) * 92 + 30), sub, font=font(36, bold=False), fill=(190, 186, 210), anchor="mm")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def fade(img, a):
    return (img.astype(np.float32) * a).astype(np.uint8)


def main():
    out = ROOT / "demo" / "teaser.mp4"
    tmp_v = ROOT / "cache" / "teaser_video.mp4"
    tmp_v.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                             f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                             "-pix_fmt", "yuv420p", str(tmp_v)], stdin=subprocess.PIPE)
    write = lambda f: proc.stdin.write(np.ascontiguousarray(f).tobytes())  # noqa: E731

    title = card(["Any song in.", "Every instrument, its own colour."], "audio → notes → play-along, on a laptop",
                 accent="play-along")
    n = int(TITLE_S * FPS)
    for i in range(n):
        write(fade(title, min(1, i / (FPS * FADE), (n - i) / (FPS * FADE))))

    audio_parts = []
    for s in SHOTS:
        song = Song.load(ROOT / s.result / "notes.json")
        rd = Renderer(song, Style(width=W, height=H, fps=FPS), solo=s.solo)
        dur = (s.t1 - s.t0) / s.speed
        n = int(round(dur * FPS))
        cx = rd.kb_w / 2
        for i in range(n):
            t = s.t0 + i / FPS * s.speed
            f = rd.frame(t)
            f = caption(f, s.text, rd.k, cx, rd.top_h + 34 * rd.k, alpha=min(1.0, i / (FPS * 0.3)))
            a = min(1.0, i / (FPS * FADE), (n - i) / (FPS * FADE))
            write(fade(f, a) if a < 1 else f)
        audio_parts.append((ROOT / s.result / "audio.mp3", s.t0, s.t1, s.speed, dur))

    end = card(["github.com/working-codes-demo/play-along"], "Open source · runs on a laptop · try it in your browser",
               accent="play-along")
    n = int(END_S * FPS)
    for i in range(n):
        write(fade(end, min(1, i / (FPS * FADE))))
    proc.stdin.close()
    assert proc.wait() == 0

    # audio: silence for the title, each shot's excerpt (faded), silence for the end card
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(tmp_v)]
    for a, *_ in audio_parts:
        cmd += ["-i", str(a)]
    fl = [f"anullsrc=r=44100:cl=stereo,atrim=0:{TITLE_S}[s0]"]
    labels = ["[s0]"]
    for j, (a, t0, t1, sp, dur) in enumerate(audio_parts, start=1):
        chain = f"[{j}:a]atrim={t0}:{t1},asetpts=PTS-STARTPTS"
        if sp != 1.0:
            chain += "," + _atempo(sp)
        chain += f",aresample=44100,afade=t=in:d={FADE},afade=t=out:st={dur - FADE:.3f}:d={FADE}[a{j}]"
        fl.append(chain)
        labels.append(f"[a{j}]")
    fl.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{END_S}[s1]")
    labels.append("[s1]")
    fl.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[aout]")
    cmd += ["-filter_complex", ";".join(fl), "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    print("wrote", out, f"{out.stat().st_size / 1e6:.1f} MB")

    # README GIF: the full-band shot, 560 px wide, 12 fps
    gif = ROOT / "demo" / "hero.gif"
    s0 = TITLE_S + 0.4
    pal = ROOT / "cache" / "pal.png"
    vf = "fps=12,scale=560:-1:flags=lanczos"
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(s0), "-t", "6", "-i", str(out),
                    "-vf", f"{vf},palettegen=max_colors=96:stats_mode=diff", str(pal)], check=True)
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(s0), "-t", "6", "-i", str(out), "-i", str(pal),
                    "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=sierra2_4a:diff_mode=rectangle", str(gif)], check=True)
    print("wrote", gif, f"{gif.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
