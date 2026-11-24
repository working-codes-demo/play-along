"""Fast tests, no model weights needed. Run: python -m pytest -q"""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from play_along.media import _atempo  # noqa: E402
from play_along.player import write_player  # noqa: E402
from play_along.render import Renderer, Style  # noqa: E402
from play_along.song import (Song, Track, drum_pad, is_black, keyboard_layout, visible, active_at)  # noqa: E402


def make_song():
    piano = np.array([[0.0, 1.0, 60, 100], [0.5, 0.7, 64, 90], [2.0, 3.0, 67, 80]], float)
    bass = np.array([[0.0, 2.0, 36, 100]], float)
    drums = np.array([[0.0, 0.1, 36, 100], [0.5, 0.6, 38, 90], [0.75, 0.8, 42, 70], [1.0, 1.1, 99, 60]], float)
    return Song("Test song", 3.5, [Track("Acoustic grand piano", 0, False, "#4cc9f0", piano),
                                   Track("Electric bass", 33, False, "#ff5d8f", bass),
                                   Track("Drums", 0, True, "#e8e8f0", drums)])


def test_is_black():
    assert [is_black(p) for p in range(60, 72)] == [False, True, False, True, False, False, True, False, True, False,
                                                    True, False]


def test_keyboard_layout_whites_fill_width_and_blacks_sit_between():
    spans = keyboard_layout(48, 72, 700.0)
    whites = [p for p in spans if not is_black(p)]
    assert len(whites) == 15
    assert spans[48][0] == pytest.approx(0) and spans[72][1] == pytest.approx(700)
    a, b = spans[49]                      # C#3 straddles the C3 | D3 line
    assert a < spans[48][1] < b


def test_key_range_starts_and_ends_on_white_keys_and_covers_notes():
    s = make_song()
    lo, hi = s.key_range()
    assert not is_black(lo) and not is_black(hi)
    assert lo <= 36 and hi >= 67 and hi - lo + 1 >= 36
    assert 21 <= lo and hi <= 108


def test_visible_and_active():
    n = make_song().tracks[0].notes
    assert list(visible(n, 0.8, 1.9)) == [0]               # the long first note is still on screen
    assert list(visible(n, 1.9, 2.5)) == [2]
    assert list(active_at(n, 0.6)) == [True, True, False]


def test_drum_pads():
    assert [drum_pad(p) for p in (36, 38, 42, 45, 49, 99)] == [0, 1, 2, 3, 4, 5]


def test_find_partial_and_missing():
    s = make_song()
    assert s.find("piano").name == "Acoustic grand piano"
    assert s.find("BASS").name == "Electric bass"
    with pytest.raises(KeyError):
        s.find("violin")


def test_json_roundtrip(tmp_path):
    s = make_song()
    s.save(tmp_path / "n.json")
    r = Song.load(tmp_path / "n.json")
    assert r.title == s.title and len(r.tracks) == 3
    assert np.allclose(r.tracks[0].notes, s.tracks[0].notes)
    assert r.drums is not None and r.drums.is_drum


def test_atempo_chains_outside_half_to_double():
    assert _atempo(0.75) == "atempo=0.7500"
    assert _atempo(0.25) == "atempo=0.5,atempo=0.5000"


def test_render_frame_shapes_and_solo():
    s = make_song()
    f = Renderer(s, Style(width=640, height=360)).frame(0.6)
    assert f.shape == (360, 640, 3) and f.dtype == np.uint8
    r = Renderer(s, Style(width=640, height=360), solo=["bass"])
    assert r.solo == {"Electric bass"}
    assert r.frame(0.6).shape == (360, 640, 3)


def test_player_injects_data_safely(tmp_path):
    s = make_song()
    s.title = "Evil </script><script>alert(1)</script>"
    p = write_player(s, tmp_path, credit={"text": "Me", "url": "https://example.com", "license": "CC0"})
    html = p.read_text()
    assert "/*__DATA__*/null" not in html
    assert html.count("</script>") == 1                  # only the real closing tag
    start = html.index("const DATA = ") + len("const DATA = ")
    blob = html[start:html.index(";\nconst PADS")]
    d = json.loads(blob.replace("<\\/", "</"))
    assert d["credit"]["license"] == "CC0" and len(d["tracks"]) == 3


def test_split_hands_only_for_solo_piano():
    piano = np.array([[0, 1, 48, 90], [0, 1, 64, 90], [1, 2, 72, 90]], float)
    s = Song("p", 2, [Track("Piano", 0, False, "#4cc9f0", piano)])
    assert s.split_hands()
    assert [t.name for t in s.tracks] == ["Piano · right hand", "Piano · left hand"]
    assert len(s.tracks[0].notes) == 2 and len(s.tracks[1].notes) == 1
    band = make_song()
    assert not band.split_hands()                    # two pitched instruments: leave alone
    flute = Song("f", 2, [Track("Flute", 73, False, "#4cc9f0", piano)])
    assert not flute.split_hands()                   # not a piano
