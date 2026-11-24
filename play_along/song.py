"""A transcribed song: instrument tracks of notes, plus the colours and layout used to draw them."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

# Bright colours that stay apart from each other on a dark background, in track order.
PALETTE = ["#4cc9f0", "#ff5d8f", "#ffd166", "#06d6a0", "#b388ff", "#ff8c42", "#9ef01a", "#48bfe3",
           "#f15bb5", "#fee440"]
DRUM_COLOR = "#e8e8f0"

# General MIDI drum keys -> the pads drawn in the video and the player.
DRUM_PADS = ["Kick", "Snare", "Hi-hat", "Toms", "Cymbals", "Perc"]
_DRUM_GROUP = {35: 0, 36: 0, 37: 1, 38: 1, 39: 1, 40: 1, 42: 2, 44: 2, 46: 2, 41: 3, 43: 3, 45: 3, 47: 3, 48: 3, 50: 3,
               49: 4, 51: 4, 52: 4, 53: 4, 55: 4, 57: 4, 59: 4}

A0, C8 = 21, 108


def drum_pad(pitch: int) -> int:
    return _DRUM_GROUP.get(int(pitch), 5)


def is_black(pitch: int) -> bool:
    return pitch % 12 in (1, 3, 6, 8, 10)


def hex_to_bgr(h: str):
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def pretty_name(name: str) -> str:
    n = name.replace("_", " ").strip()
    return n[:1].upper() + n[1:]


@dataclass
class Track:
    name: str
    program: int
    is_drum: bool
    color: str
    notes: np.ndarray          # (N, 4) onset s, offset s, MIDI pitch, velocity 1-127, sorted by onset

    def to_json(self) -> dict:
        return {"name": self.name, "program": self.program, "is_drum": self.is_drum, "color": self.color,
                "notes": [[round(float(a), 3), round(float(b), 3), int(p), int(v)] for a, b, p, v in self.notes]}

    @classmethod
    def from_json(cls, d: dict) -> "Track":
        notes = np.asarray(d["notes"], np.float64).reshape(-1, 4)
        return cls(d["name"], int(d.get("program") or 0), bool(d["is_drum"]), d["color"], notes)


@dataclass
class Song:
    title: str
    duration: float
    tracks: List[Track]
    meta: Dict = field(default_factory=dict)

    # ---------- construction ----------
    @classmethod
    def from_transcription(cls, tr, title: str = "", offset: float = 0.0) -> "Song":
        """From a dettato.Transcription. Biggest pitched tracks first, drums last, colours in that order."""
        pitched = sorted([t for t in tr.tracks if not t.is_drum and len(t.notes)], key=lambda t: -len(t.notes))
        drums = [t for t in tr.tracks if t.is_drum and len(t.notes)]
        tracks = []
        for i, t in enumerate(pitched):
            tracks.append(Track(pretty_name(t.name), int(t.program), False, PALETTE[i % len(PALETTE)], _clean(t.notes, offset)))
        for t in drums:
            tracks.append(Track("Drums", 0, True, DRUM_COLOR, _clean(t.notes, offset)))
        return cls(title or Path(str(tr.source)).stem, float(tr.seconds), tracks, {"dettato": dict(tr.info)})

    def to_json(self) -> dict:
        return {"title": self.title, "duration": round(self.duration, 3), "meta": self.meta,
                "range": list(self.key_range()), "tracks": [t.to_json() for t in self.tracks]}

    @classmethod
    def from_json(cls, d: dict) -> "Song":
        return cls(d["title"], float(d["duration"]), [Track.from_json(t) for t in d["tracks"]], d.get("meta", {}))

    def save(self, path: Path):
        Path(path).write_text(json.dumps(self.to_json(), separators=(",", ":")))

    @classmethod
    def load(cls, path: Path) -> "Song":
        return cls.from_json(json.loads(Path(path).read_text()))

    def split_hands(self, split: int = 60) -> bool:
        """If the only pitched instrument is a piano, split it into right hand (middle C and up) and left hand,
        so each hand gets its own colour and can be practised alone. A fixed split: crossings are not tracked.
        Returns True when it split."""
        pitched = self.pitched
        if len(pitched) != 1 or pitched[0].program >= 8 or len(pitched[0].notes) == 0:
            return False
        tr = pitched[0]
        hi = tr.notes[tr.notes[:, 2] >= split]
        lo = tr.notes[tr.notes[:, 2] < split]
        if len(hi) == 0 or len(lo) == 0:
            return False
        others = [t for t in self.tracks if t is not tr]
        self.tracks = [Track(f"{tr.name} · right hand", tr.program, False, PALETTE[0], hi),
                       Track(f"{tr.name} · left hand", tr.program, False, PALETTE[1], lo)] + others
        self.meta["hands_split_at"] = split
        return True

    # ---------- queries ----------
    @property
    def pitched(self) -> List[Track]:
        return [t for t in self.tracks if not t.is_drum]

    @property
    def drums(self) -> Optional[Track]:
        return next((t for t in self.tracks if t.is_drum), None)

    def find(self, name: str) -> Track:
        """Track by (case-insensitive, partial) name: 'piano' finds 'Electric piano'."""
        key = name.lower().strip()
        exact = [t for t in self.tracks if t.name.lower() == key]
        part = [t for t in self.tracks if key in t.name.lower()]
        hits = exact or part
        if not hits:
            raise KeyError(f"no instrument matching {name!r}; this song has: {', '.join(t.name for t in self.tracks)}")
        return hits[0]

    def key_range(self, min_keys: int = 36) -> tuple:
        """Lowest and highest MIDI key to draw: the song's pitch range plus a margin, widened to at least
        `min_keys` keys, starting and ending on white keys, clamped to the 88-key piano."""
        ps = [t.notes[:, 2] for t in self.pitched if len(t.notes)]
        if not ps:
            return 48, 84
        allp = np.concatenate(ps)
        lo, hi = int(np.percentile(allp, 0.5)) - 2, int(np.percentile(allp, 99.5)) + 2
        lo, hi = min(lo, int(allp.min())), max(hi, int(allp.max()))
        while hi - lo + 1 < min_keys:
            lo, hi = lo - 1, hi + 1
        lo, hi = max(A0, lo), min(C8, hi)
        while is_black(lo) and lo > A0:
            lo -= 1
        while is_black(hi) and hi < C8:
            hi += 1
        return lo, hi


def _clean(notes, offset: float = 0.0) -> np.ndarray:
    n = np.asarray(notes, np.float64).reshape(-1, 4).copy()
    if len(n) == 0:
        return n
    n[:, 0:2] += offset
    n[:, 1] = np.maximum(n[:, 1], n[:, 0] + 0.05)
    return n[np.argsort(n[:, 0], kind="stable")]


def keyboard_layout(lo: int, hi: int, width: float, x0: float = 0.0) -> Dict[int, tuple]:
    """Pixel span (x_left, x_right) of every key from lo to hi. White keys share the width equally;
    black keys are 60 % as wide, centred on the line between their two white neighbours."""
    whites = [p for p in range(lo, hi + 1) if not is_black(p)]
    ww = width / len(whites)
    spans, wi = {}, 0
    for p in range(lo, hi + 1):
        if is_black(p):
            c = x0 + wi * ww
            spans[p] = (c - ww * 0.3, c + ww * 0.3)
        else:
            spans[p] = (x0 + wi * ww, x0 + (wi + 1) * ww)
            wi += 1
    return spans


def active_at(notes: np.ndarray, t: float) -> np.ndarray:
    """Boolean mask of notes sounding at time t."""
    if len(notes) == 0:
        return np.zeros(0, bool)
    return (notes[:, 0] <= t) & (notes[:, 1] > t)


def visible(notes: np.ndarray, t0: float, t1: float) -> np.ndarray:
    """Indices of notes that overlap the window [t0, t1]. `notes` must be sorted by onset."""
    if len(notes) == 0:
        return np.zeros(0, int)
    end = int(np.searchsorted(notes[:, 0], t1, side="right"))
    idx = np.arange(end)
    return idx[notes[:end, 1] >= t0]


def merge_tracks(tracks: Sequence[Track]) -> np.ndarray:
    ns = [t.notes for t in tracks if len(t.notes)]
    return np.concatenate(ns) if ns else np.zeros((0, 4))
