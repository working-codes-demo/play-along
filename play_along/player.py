"""Write the interactive practice player: one self-contained HTML file next to the song's audio."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .song import Song

TEMPLATE = Path(__file__).with_name("player.html")


def write_player(song: Song, out_dir: Path, files: Optional[dict] = None, credit: Optional[dict] = None,
                 name: str = "player.html") -> Path:
    """`files`: paths relative to out_dir for audio / midi / video. `credit`: {"text", "url", "license"} for the music."""
    data = song.to_json()
    data["files"] = files or {"audio": "audio.mp3", "midi": "song.mid", "video": "playalong.mp4"}
    if credit:
        data["credit"] = credit
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", blob, 1)
    out = Path(out_dir) / name
    out.write_text(html)
    return out
