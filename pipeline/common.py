"""Shared helpers: project paths, config, running external tools, small utils."""

import json
import re
import shlex
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
TEMPLATE = ROOT / "template"


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def log(msg):
    print(msg, flush=True)


def run(cmd, capture=False, echo=True, log_file=None, env=None):
    """Run an external command; stop the pipeline with a readable error if it fails.
    log_file: send the tool's chatter there and only show its tail on failure."""
    cmd = [str(c) for c in cmd]
    if echo:
        log("  $ " + " ".join(shlex.quote(c) for c in cmd))
    if log_file:
        with open(log_file, "w") as fh:
            res = subprocess.run(cmd, text=True, stdout=fh, stderr=subprocess.STDOUT, env=env)
        if res.returncode != 0:
            sys.stderr.write("\n".join(Path(log_file).read_text(errors="replace").splitlines()[-40:]) + "\n")
    else:
        res = subprocess.run(cmd, text=True, capture_output=capture, env=env)
        if res.returncode != 0 and capture:
            sys.stderr.write((res.stderr or "")[-4000:])
    if res.returncode != 0:
        raise SystemExit(f"Lệnh thất bại (mã {res.returncode}): {cmd[0]}")
    return res.stdout if capture else ""


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def video_dir(vid):
    return WORK / vid


def source_path(vid):
    d = video_dir(vid)
    hits = sorted(p for p in d.glob("source.*") if p.suffix not in (".part", ".ytdl"))
    if not hits:
        raise SystemExit(f"Chưa có video nguồn cho '{vid}'. Chạy: python3 shorts.py download <link>")
    return hits[0]


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
              capture=True, echo=False)
    data = json.loads(out)
    v = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    return {
        "duration": float(data["format"].get("duration", 0)),
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"]),
    }


def dir_size(path):
    """Bytes under path (files only, symlinks not followed)."""
    path = Path(path)
    if path.is_symlink() or path.is_file():
        return 0 if path.is_symlink() else path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def slugify(text, max_len=48):
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "video"


def fmt_time(sec):
    m, s = divmod(max(0.0, sec), 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"


def parse_only(only):
    """'1,3-5' -> {1, 3, 4, 5}; None -> None (all)."""
    if not only:
        return None
    picked = set()
    for part in str(only).split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            picked.update(range(int(a), int(b) + 1))
        elif part.strip():
            picked.add(int(part))
    return picked
