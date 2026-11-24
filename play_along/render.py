"""Falling-notes play-along video: every instrument in its own colour, drums on their own pads."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .media import VideoWriter
from .song import (DRUM_PADS, Song, Track, active_at, drum_pad, hex_to_bgr, is_black, keyboard_layout, visible)

FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]
FONTS_REG = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "C:/Windows/Fonts/arial.ttf"]
BG_TOP, BG_BOT = (28, 15, 13), (48, 16, 27)          # BGR: deep navy -> plum
WHITE_KEY, BLACK_KEY = (236, 236, 240), (34, 30, 30)


def font(size: int, bold: bool = True):
    for f in (FONTS if bold else FONTS_REG):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size=size)


def fmt_t(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{int(t % 60):02d}"


def mix(c, d, a: float):
    """a=0 -> c, a=1 -> d."""
    return tuple(int(round(x * (1 - a) + y * a)) for x, y in zip(c, d))


@dataclass
class Style:
    width: int = 1280
    height: int = 720
    fps: float = 30.0
    lookahead: float = 2.6        # seconds a note takes to fall from the top to the keys
    lead: float = 2.0             # seconds of title before the song starts
    brand: str = "github.com/working-codes-demo/play-along"


class Renderer:
    def __init__(self, song: Song, style: Style = Style(), solo: Optional[Sequence[str]] = None, title: str = ""):
        self.song, self.st = song, style
        W, H = style.width, style.height
        self.k = k = W / 1280.0
        self.title = title or song.title
        self.solo = {song.find(s).name for s in solo} if solo else None
        self.top_h = int(64 * k)
        self.kb_h = int(118 * k)
        self.kb_y = H - self.kb_h
        drums = song.drums
        self.pad_w = int(150 * k) if drums is not None and len(drums.notes) else 0
        self.kb_w = W - self.pad_w
        self.lo, self.hi = song.key_range()
        self.spans = keyboard_layout(self.lo, self.hi, self.kb_w)
        self.pps = (self.kb_y - self.top_h) / style.lookahead
        self.colors = {t.name: hex_to_bgr(t.color) for t in song.tracks}
        self._build_static()

    # ---------- static layers ----------
    def _build_static(self):
        W, H, k = self.st.width, self.st.height, self.k
        y = np.linspace(0, 1, H)[:, None, None]
        bg = (np.array(BG_TOP) * (1 - y) + np.array(BG_BOT) * y).astype(np.float32)
        self.bg = np.repeat(bg, W, axis=1).astype(np.uint8)
        # faint guide line at every C, so octaves are easy to read
        for p in range(self.lo, self.hi + 1):
            if p % 12 == 0:
                x = int(self.spans[p][0])
                cv2.line(self.bg, (x, self.top_h), (x, self.kb_y), (70, 48, 52), 1, cv2.LINE_AA)
        # keyboard: white keys, then black keys with a mask so pressed white keys can be recoloured underneath
        kb = np.zeros((self.kb_h, self.kb_w, 3), np.uint8)
        kb[:] = (20, 18, 18)
        for p, (a, b) in self.spans.items():
            if not is_black(p):
                cv2.rectangle(kb, (int(a) + 1, 0), (int(b) - 1, self.kb_h - 1), WHITE_KEY, -1)
        self.kb_white = kb
        self.black_mask = np.zeros((self.kb_h, self.kb_w), bool)
        bh = int(self.kb_h * 0.62)
        for p, (a, b) in self.spans.items():
            if is_black(p):
                self.black_mask[0:bh, int(a):int(b)] = True
        self.black_h = bh
        # labels on every C
        img = Image.fromarray(cv2.cvtColor(self.kb_white, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(img)
        f = font(max(9, int(11 * k)), bold=False)
        for p, (a, b) in self.spans.items():
            if p % 12 == 0:
                d.text(((a + b) / 2, self.kb_h - 6 * k), f"C{p // 12 - 1}", font=f, fill=(150, 150, 160), anchor="mb")
        self.kb_white = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        # top bar: title + legend (static part)
        self.f_title, self.f_small, self.f_legend = font(int(22 * k)), font(int(13 * k), bold=False), font(int(14 * k))
        self.pad_centers = []
        if self.pad_w:
            n = len(DRUM_PADS)
            gap = (self.kb_y - self.top_h) / n
            for i in range(n):
                self.pad_centers.append((int(self.kb_w + self.pad_w / 2), int(self.top_h + gap * (i + 0.5))))

    # ---------- per frame ----------
    def frame(self, t: float, progress: Optional[float] = None) -> np.ndarray:
        st, k = self.st, self.k
        img = self.bg.copy()
        glow = np.zeros((st.height // 4, st.width // 4, 3), np.float32)
        t0, t1 = t - 0.05, t + st.lookahead
        r = max(2, int(4 * k))
        pressed = {}
        # draw dimmed (non-solo) tracks first, then the highlighted ones on top
        order = sorted(self.song.pitched, key=lambda tr: self._lit(tr))
        for tr in order:
            col = self.colors[tr.name]
            lit = self._lit(tr)
            idx = visible(tr.notes, t0, t1)
            if len(idx) == 0:
                continue
            n = tr.notes[idx]
            on = active_at(n, t)
            body = col if lit else mix(col, BG_TOP, 0.78)
            for (a, b, p, v), sounding in zip(n, on):
                p = int(p)
                if p not in self.spans:
                    continue
                xa, xb = self.spans[p]
                y_bot = self.kb_y - (a - t) * self.pps
                y_top = self.kb_y - (b - t) * self.pps
                y_bot, y_top = min(y_bot, self.kb_y), max(y_top, self.top_h)
                if y_bot - y_top < 2:
                    continue
                c = mix(body, (255, 255, 255), 0.35) if (sounding and lit) else body
                _round_rect(img, int(xa) + 1, int(y_top), int(xb) - 1, int(y_bot), r, mix(c, (0, 0, 0), 0.45))
                _round_rect(img, int(xa) + 2, int(y_top) + 1, int(xb) - 2, int(y_bot) - 1, max(1, r - 1), c)
                if sounding and lit:
                    pressed[p] = col
                    cx = (xa + xb) / 2 / 4
                    cv2.circle(glow, (int(cx), int(self.kb_y / 4)), int(7 * k), [x / 255 for x in col], -1)
        # keyboard
        kb = self.kb_white.copy()
        for p, col in pressed.items():
            if not is_black(p):
                a, b = self.spans[p]
                cv2.rectangle(kb, (int(a) + 1, 0), (int(b) - 1, self.kb_h - 1), mix(col, (255, 255, 255), 0.25), -1)
        kb[self.black_mask] = BLACK_KEY
        for p, col in pressed.items():
            if is_black(p):
                a, b = self.spans[p]
                cv2.rectangle(kb, (int(a), 0), (int(b) - 1, self.black_h - 1), col, -1)
        img[self.kb_y:, :self.kb_w] = kb
        cv2.line(img, (0, self.kb_y), (self.kb_w, self.kb_y), (90, 80, 200), max(1, int(2 * k)), cv2.LINE_AA)
        # drum pads
        if self.pad_w:
            self._drums(img, glow, t)
        # glow
        g = cv2.GaussianBlur(glow, (0, 0), 3 * k + 1)
        g = cv2.resize(g, (st.width, st.height), interpolation=cv2.INTER_LINEAR)
        img = np.clip(img.astype(np.float32) + g * 255 * 1.6, 0, 255).astype(np.uint8)
        self._top_bar(img, t, progress)
        return img

    def _lit(self, tr: Track) -> bool:
        return self.solo is None or tr.name in self.solo

    def _drums(self, img, glow, t):
        k = self.k
        dr = self.song.drums
        lit = self._lit(dr)
        x0 = self.kb_w
        cv2.rectangle(img, (x0, self.top_h), (self.st.width, self.st.height), (30, 16, 18), -1)
        cv2.line(img, (x0, self.top_h), (x0, self.st.height), (70, 48, 52), 1)
        # time since the last hit on each pad (within 0.4 s)
        idx = visible(dr.notes, t - 0.4, t)
        last = {}
        for a, b, p, v in dr.notes[idx]:
            if a <= t:
                g = drum_pad(p)
                last[g] = max(last.get(g, -1), a)
        R = int(min(self.pad_w * 0.30, (self.kb_y - self.top_h) / len(DRUM_PADS) * 0.36))
        col = hex_to_bgr(self.song.drums.color)
        for i, (cx, cy) in enumerate(self.pad_centers):
            age = t - last[i] if i in last else 9
            hit = max(0.0, 1 - age / 0.35) if lit else 0.0
            ring = mix((80, 62, 66), col, 0.25 + 0.75 * hit)
            cv2.circle(img, (cx, cy), R, mix((40, 24, 28), col, 0.55 * hit), -1, cv2.LINE_AA)
            cv2.circle(img, (cx, cy), R, ring, max(1, int(2 * k)), cv2.LINE_AA)
            if hit > 0:
                cv2.circle(img, (cx, cy), int(R * (1 + 0.5 * (1 - hit))), ring, 1, cv2.LINE_AA)
                cv2.circle(glow, (cx // 4, cy // 4), int(R / 4 + 2), [0.3 * hit] * 3, -1)
        # pad labels (PIL for nicer text), drawn once per frame on the small panel
        panel = Image.fromarray(cv2.cvtColor(img[:, x0:], cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(panel)
        for i, (cx, cy) in enumerate(self.pad_centers):
            dark = lit and i in last and t - last[i] < 0.2
            d.text((cx - x0, cy), DRUM_PADS[i], font=self.f_small, fill=(30, 24, 40) if dark else (225, 225, 235),
                   anchor="mm")
        img[:, x0:] = cv2.cvtColor(np.array(panel), cv2.COLOR_RGB2BGR)

    def _top_bar(self, img, t, progress):
        st, k = self.st, self.k
        bar = Image.new("RGB", (st.width, self.top_h), (16, 12, 24))
        d = ImageDraw.Draw(bar)
        x = int(18 * k)
        d.text((x, self.top_h / 2), self.title, font=self.f_title, fill=(255, 255, 255), anchor="lm")
        x += d.textlength(self.title, font=self.f_title) + 26 * k
        for tr in self.song.tracks:
            lit = self._lit(tr)
            rgb = tuple(int(tr.color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            if not lit:
                rgb = tuple(int(c * 0.35 + 30) for c in rgb)
            cy = self.top_h / 2
            d.rounded_rectangle([x, cy - 6 * k, x + 12 * k, cy + 6 * k], radius=int(3 * k), fill=rgb)
            x += 17 * k
            d.text((x, cy), tr.name, font=self.f_legend, fill=(235, 235, 240) if lit else (110, 110, 120), anchor="lm")
            x += d.textlength(tr.name, font=self.f_legend) + 16 * k
            if x > st.width - 330 * k:
                break
        right = f"{fmt_t(t)} / {fmt_t(self.song.duration)}"
        d.text((st.width - 18 * k, self.top_h / 2 - 8 * k), right, font=self.f_legend, fill=(235, 235, 240), anchor="rm")
        d.text((st.width - 18 * k, self.top_h / 2 + 10 * k), self.st.brand, font=self.f_small, fill=(150, 150, 170),
               anchor="rm")
        arr = cv2.cvtColor(np.array(bar), cv2.COLOR_RGB2BGR)
        img[:self.top_h] = arr
        if progress is None:
            progress = t / max(self.song.duration, 1e-6)
        pw = int(st.width * float(np.clip(progress, 0, 1)))
        cv2.rectangle(img, (0, self.top_h - max(2, int(3 * k))), (pw, self.top_h), (102, 209, 255), -1)

    def title_card(self, img, alpha: float, subtitle: str = ""):
        """Fade a centred title over the field (used during the lead-in)."""
        if alpha <= 0:
            return img
        st, k = self.st, self.k
        over = Image.new("RGBA", (st.width, st.height), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        cy = (self.top_h + self.kb_y) / 2
        a = int(255 * alpha)
        d.text((st.width / 2 - self.pad_w / 2, cy - 18 * k), self.title, font=font(int(46 * k)), fill=(255, 255, 255, a),
               anchor="mm")
        if subtitle:
            d.text((st.width / 2 - self.pad_w / 2, cy + 30 * k), subtitle, font=font(int(20 * k), bold=False),
                   fill=(255, 209, 102, a), anchor="mm")
        base = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")
        base.alpha_composite(over)
        return cv2.cvtColor(np.array(base.convert("RGB")), cv2.COLOR_RGB2BGR)


def caption(img, text: str, k: float, field_center_x: float, y: float, alpha: float = 1.0):
    """An amber pill with dark text, e.g. 'Solo: clarinet', drawn over the note field."""
    if alpha <= 0 or not text:
        return img
    f = font(int(30 * k))
    base = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    over = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    tw = d.textlength(text, font=f)
    pad_x, h = 26 * k, 58 * k
    x0, x1 = field_center_x - tw / 2 - pad_x, field_center_x + tw / 2 + pad_x
    a = int(255 * alpha)
    d.rounded_rectangle([x0, y, x1, y + h], radius=int(h / 2), fill=(255, 209, 102, int(240 * alpha)))
    d.text((field_center_x, y + h / 2), text, font=f, fill=(27, 21, 48, a), anchor="mm")
    base.alpha_composite(over)
    return cv2.cvtColor(np.array(base.convert("RGB")), cv2.COLOR_RGB2BGR)


def _round_rect(img, x0, y0, x1, y1, r, color):
    if x1 - x0 < 2 * r or y1 - y0 < 2 * r:
        cv2.rectangle(img, (x0, y0), (x1, y1), color, -1)
        return
    cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), color, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), color, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA)


def render_video(song: Song, audio: Optional[Path], out: Path, style: Style = Style(), solo=None, speed: float = 1.0,
                 subtitle: str = "", t_start: float = 0.0, t_end: Optional[float] = None,
                 progress: Optional[Callable[[float], None]] = None) -> Path:
    """Write the play-along MP4. `speed` < 1 slows notes and audio together (pitch kept) for practice.
    t_start / t_end render only part of the song (the audio is cut to match)."""
    rd = Renderer(song, style, solo=solo)
    t_end = song.duration if t_end is None else min(t_end, song.duration)
    lead = style.lead if t_start <= 0 else 0.0
    span = (t_end - t_start) / speed + lead
    n = int(round(span * style.fps))
    wr = VideoWriter(out, style.width, style.height, style.fps, audio=audio, lead=lead, speed=speed, audio_start=t_start)
    if not subtitle and rd.solo:
        subtitle = "Solo: " + ", ".join(sorted(rd.solo))
    if not subtitle and speed != 1.0:
        subtitle = f"Practice speed {speed:g}x"
    try:
        for i in range(n):
            tv = i / style.fps
            t = t_start + (tv - lead) * speed
            fr = rd.frame(t)
            if tv < lead + 0.6 and t_start <= 0:
                a = min(1.0, tv / 0.4) * min(1.0, max(0.0, (lead + 0.6 - tv) / 0.8))
                fr = rd.title_card(fr, a, subtitle or "every instrument, its own colour")
            wr.write(fr)
            if progress and i % max(1, n // 10) == 0:
                progress(i / n)
    finally:
        wr.close()
    return out
