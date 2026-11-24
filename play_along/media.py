"""Audio in (file or URL), video out."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def is_url(s: str) -> bool:
    return "://" in s


def fetch(url_or_path: str, workdir: Path) -> Path:
    """A local file passes through; a URL (YouTube, SoundCloud, Bandcamp, ...) is downloaded as audio with yt-dlp."""
    if not is_url(url_or_path):
        p = Path(url_or_path)
        if not p.exists():
            raise FileNotFoundError(p)
        return p
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("pip install yt-dlp to use links") from e
    workdir.mkdir(parents=True, exist_ok=True)
    opts = {"format": "bestaudio/best", "outtmpl": str(workdir / "%(id)s.%(ext)s"), "quiet": True, "noprogress": True,
            "noplaylist": True, "ffmpeg_location": ffmpeg_exe(),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url_or_path, download=True)
        return Path(ydl.prepare_filename(info)).with_suffix(".wav")


def title_of(url_or_path: str) -> str:
    if not is_url(url_or_path):
        return Path(url_or_path).stem.replace("_", " ")
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
            return ydl.extract_info(url_or_path, download=False).get("title") or "song"
    except Exception:  # noqa: BLE001
        return "song"


def to_wav(src: Path, dst: Path, start: float = 0.0, end: Optional[float] = None, rate: int = 44100) -> Path:
    """Decode (and optionally cut) any audio or video file to a stereo 44.1 kHz WAV.
    44.1 kHz matters: dettato's drum model only runs on sources recorded at >= 40 kHz."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end is not None and end > start:
        cmd += ["-t", f"{end - start:.3f}"]
    cmd += ["-vn", "-ac", "2", "-ar", str(rate), "-c:a", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True)
    return dst


def to_web_audio(src: Path, dst: Path, kbps: int = 128) -> Path:
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "2", "-c:a", "libmp3lame",
                    "-b:a", f"{kbps}k", str(dst)], check=True)
    return dst


def duration_of(path: Path) -> float:
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / info.samplerate


class VideoWriter:
    """Raw BGR frames in, H.264 MP4 out, with the song muxed in (delayed by `lead` s, slowed by `speed`)."""

    def __init__(self, path: Path, w: int, h: int, fps: float, audio: Optional[Path] = None, lead: float = 0.0,
                 speed: float = 1.0, audio_start: float = 0.0, crf: int = 20):
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
               "-r", f"{fps:.3f}", "-i", "-"]
        if audio is not None:
            if audio_start > 0:
                cmd += ["-ss", f"{audio_start:.3f}"]
            cmd += ["-i", str(audio)]
            filters = []
            if speed != 1.0:
                filters.append(_atempo(speed))
            if lead > 0:
                ms = int(round(lead * 1000))
                filters.append(f"adelay={ms}|{ms}")
            if filters:
                cmd += ["-filter:a", ",".join(filters)]
            cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        self.path = path

    def write(self, frame: np.ndarray):
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {self.path}")


def _atempo(speed: float) -> str:
    """ffmpeg's atempo takes 0.5-2.0 per stage; chain stages for anything outside."""
    parts, s = [], speed
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)
