"""Audio -> Song, with dettato (audio to multi-instrument MIDI)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from .song import Song

_MODEL = {}


def load_model(device: Optional[str] = None):
    import dettato
    key = device or "auto"
    if key not in _MODEL:
        _MODEL[key] = dettato.Dettato.from_pretrained(device)
    return _MODEL[key]


def transcribe(wav: Path, title: str = "", device: Optional[str] = None) -> Song:
    model = load_model(device)
    t0 = time.time()
    tr = model.transcribe(str(wav))
    song = Song.from_transcription(tr, title=title)
    song.meta["transcribe_s"] = round(time.time() - t0, 1)
    song.meta["device"] = str(model.device)
    return song
