#!/usr/bin/env python3
"""Build the GitHub Pages demo in docs/ from finished runs listed in demo/songs.json.

    python scripts/build_pages.py

Each song gets docs/<slug>/ (player as index.html + audio.mp3 + song.mid) and a card on docs/index.html."""
from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from play_along.player import write_player  # noqa: E402
from play_along.render import Renderer, Style  # noqa: E402
from play_along.song import Song  # noqa: E402


def busiest_time(song: Song, lookahead: float = 2.6) -> float:
    """A moment with plenty of notes on screen from several instruments, for the thumbnail."""
    best, best_t = -1.0, 1.0
    for t in np.arange(3.0, max(3.5, song.duration - 3), 0.5):
        score = 0.0
        for tr in song.pitched:
            n = tr.notes
            k = int(((n[:, 0] < t + lookahead) & (n[:, 1] > t)).sum()) if len(n) else 0
            score += min(k, 12) + (3 if k else 0)
        if score > best:
            best, best_t = score, float(t)
    return best_t


def main():
    spec = json.loads((ROOT / "demo" / "songs.json").read_text())
    docs = ROOT / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    docs.mkdir()
    (docs / ".nojekyll").write_text("")
    cards = []
    for s in spec:
        src = ROOT / s["result"]
        song = Song.load(src / "notes.json")
        out = docs / s["slug"]
        out.mkdir()
        shutil.copy(src / "audio.mp3", out / "audio.mp3")
        shutil.copy(src / "song.mid", out / "song.mid")
        credit = {"text": s["credit"], "url": s.get("url"), "license": s.get("license")}
        write_player(song, out, files={"audio": "audio.mp3", "midi": "song.mid"}, credit=credit, name="index.html")
        t = busiest_time(song)
        frame = Renderer(song, Style(width=960, height=540)).frame(t)
        cv2.imwrite(str(out / "thumb.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        chips = "".join(f'<span class="c"><i style="background:{tr.color}"></i>{html.escape(tr.name)}</span>'
                        for tr in song.tracks)
        cards.append(f'''<a class="card" href="{s["slug"]}/">
  <img src="{s["slug"]}/thumb.jpg" alt="{html.escape(song.title)} falling notes" loading="lazy">
  <div class="body"><h3>{html.escape(song.title)}</h3><div class="chips">{chips}</div>
  <div class="meta">{html.escape(s.get("blurb", ""))}</div>
  <div class="credit">{html.escape(s["credit"])} · {html.escape(s.get("license") or "")}</div></div></a>''')
        print("built", s["slug"], f"thumb at {t:.1f}s")
    page = (ROOT / "scripts" / "index_template.html").read_text().replace("<!--CARDS-->", "\n".join(cards))
    (docs / "index.html").write_text(page)
    hero = ROOT / "demo" / "hero.gif"
    if hero.exists():
        shutil.copy(hero, docs / "hero.gif")
    size = sum(f.stat().st_size for f in docs.rglob("*") if f.is_file())
    print(f"docs/ written: {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
