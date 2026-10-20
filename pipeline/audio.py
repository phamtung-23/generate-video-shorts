"""Sound for each short: commentary pulled out of the source mix, a CC0 music bed, stadium
ambience and hit effects. Every file and its licence is listed in assets/{music,sfx}/library.json.

Why separate first: compilation uploads usually lay their own (often copyrighted) music under the
commentary. Demucs keeps the voices (commentary + fans singing) and drops that bed, so our own music
can go on top without two songs fighting.
"""

import platform
import re
import shutil
import subprocess

from .common import ROOT, probe, read_json, run

VENV_PY = ROOT / ".venv" / "bin" / "python"
MUSIC_DIR = ROOT / "assets" / "music"
SFX_DIR = ROOT / "assets" / "sfx"


def demucs_available():
    return VENV_PY.exists() and subprocess.run([VENV_PY, "-c", "import demucs"],
                                               capture_output=True).returncode == 0


def separate_voice(clip, out, tmp):
    """clip.mp4 → out (.m4a): commentary/crowd voices only, normalised to -14 LUFS so the
    commentary sits on top of the music bed (-16 LUFS × bed volume)."""
    tmp.mkdir(parents=True, exist_ok=True)
    mix = tmp / "mix.wav"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", clip, "-vn", "-ac", "2",
         "-ar", "44100", mix], echo=False)
    device = "mps" if platform.machine() == "arm64" and platform.system() == "Darwin" else "cpu"
    run([VENV_PY, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-d", device,
         "-o", tmp, mix], echo=False, log_file=tmp.parent / "demucs.log")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", tmp / "htdemucs" / "mix" / "vocals.wav",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out],
        echo=False)
    shutil.rmtree(tmp)


def pick_music(clip):
    """highlights.json "music": a file/title from the library, "none", or empty to rotate by clip #."""
    lib = read_json(MUSIC_DIR / "library.json")
    want = (clip.get("music") or "").strip().lower()
    if want == "none" or not lib:
        return None
    if want:
        for t in lib:
            if want in t["file"].lower() or want in t["title"].lower():
                return t
        raise SystemExit(f"Không có nhạc '{clip['music']}' trong assets/music/library.json")
    return lib[(clip["n"] - 1) % len(lib)]


def music_bed(track, dur, out):
    """Cut the track to the short's length, starting at its strongest entrance; loop if too short."""
    path = MUSIC_DIR / track["file"]
    length = probe(path)["duration"]
    offset = track.get("offset", _strongest_entrance(path, dur, length))
    loop = ["-stream_loop", "-1"] if length - offset < dur else []
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *loop, "-ss", f"{offset:.2f}", "-i", path,
         "-t", f"{dur:.3f}", "-af",
         f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.3,afade=t=out:st={max(0, dur - 1.5):.2f}:d=1.5",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out], echo=False)
    return offset


def ambience_bed(dur, out, seed):
    amb = sfx_library()["ambience"]
    path = SFX_DIR / amb["file"]
    length = probe(path)["duration"]
    offset = (seed * 13.7) % max(1.0, length - dur)
    loop = ["-stream_loop", "-1"] if length - offset < dur else []
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *loop, "-ss", f"{offset:.2f}", "-i", path,
         "-t", f"{dur:.3f}", "-af",
         f"loudnorm=I=-20:TP=-2,afade=t=in:d=0.5,afade=t=out:st={max(0, dur - 1.0):.2f}:d=1.0",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", out], echo=False)


def sfx_library():
    lib = read_json(SFX_DIR / "library.json")
    for item in lib.values():
        item["duration"] = probe(SFX_DIR / item["file"])["duration"]
    return lib


def copy_sfx(assets_dir, keys):
    lib = sfx_library()
    for key in keys:
        shutil.copy(SFX_DIR / lib[key]["file"], assets_dir / lib[key]["file"])


def credits(layout):
    """Lines for the YouTube description: every third-party sound used in this short."""
    out = []
    if layout.get("music"):
        m = layout["music"]
        out.append(f'Music: "{m["title"]}" by {m["creator"]} ({m["license"]}) {m["source"]}')
    used = list(layout.get("sfx", [])) + (["ambience"] if layout.get("ambience", layout.get("voice")) else [])
    if used:
        for key, item in sfx_library().items():
            if key in used and item.get("creator"):
                out.append(f'Sound: "{item["title"]}" by {item["creator"]} ({item["license"]}) {item["source"]}')
    return out


def _strongest_entrance(path, dur, length, window=5):
    if length <= dur:
        return 0.0
    rms = _rms(path, 1.0)
    last = int(length - dur)
    scores = [sum(rms[o:o + window]) / len(rms[o:o + window]) for o in range(0, last + 1)]
    return float(max(range(len(scores)), key=lambda o: (scores[o], -o)))


def _rms(path, step):
    n = int(16000 * step)
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                          f"aresample=16000,asetnsamples=n={n}:p=0,astats=metadata=1:reset=1:"
                          "measure_perchannel=none:measure_overall=RMS_level,"
                          "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    return [max(-90.0, float(v)) if v not in ("-inf", "inf", "nan") else -90.0
            for v in re.findall(r"RMS_level=(\S+)", out)]
