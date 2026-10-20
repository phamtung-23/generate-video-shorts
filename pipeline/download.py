"""Step 1 — get the long video into work/<id>/source.* (YouTube/any yt-dlp URL, or a local file)."""

import json
import re
from pathlib import Path

from .common import log, probe, read_json, run, slugify, video_dir, write_json

CC_HINTS = ("creative commons", "cc by", "cc-by")


def download(src, cfg):
    path = Path(src).expanduser()
    if path.exists():
        return _ingest_local(path)

    log("• Đọc thông tin video…")
    meta = json.loads(run(["yt-dlp", "--dump-single-json", "--no-playlist", "--no-warnings", src],
                          capture=True))
    vid = re.sub(r"[^A-Za-z0-9_-]", "-", meta["id"])[:40]  # keep case: YouTube ids are case-sensitive
    d = video_dir(vid)
    d.mkdir(parents=True, exist_ok=True)
    info = {
        "id": vid,
        "title": meta.get("title", ""),
        "uploader": meta.get("uploader") or meta.get("channel") or "",
        "url": meta.get("webpage_url", src),
        "duration": meta.get("duration") or 0,
        "license": meta.get("license") or "",
    }
    write_json(d / "info.json", info)

    if any(d.glob("source.mp4")):
        log(f"• Đã có video nguồn: {d / 'source.mp4'} (bỏ qua tải)")
    else:
        h = cfg["download"]["max_height"]
        log(f"• Tải video (tối đa {h}p)…")
        run(["yt-dlp", "--no-playlist", "--no-warnings", "--retries", "10", "--fragment-retries", "10",
             "-f", f"bv*[height<={h}]+ba/b[height<={h}]/b",
             "-S", f"res:{h},vcodec:h264,acodec:m4a",
             "--merge-output-format", "mp4",
             "-o", str(d / "source.%(ext)s"), src])

    _license_note(info)
    return vid


def _ingest_local(path):
    vid = slugify(path.stem)
    d = video_dir(vid)
    d.mkdir(parents=True, exist_ok=True)
    link = d / f"source{path.suffix.lower()}"
    if not link.exists():
        link.symlink_to(path.resolve())
    meta = probe(path)
    info = {"id": vid, "title": path.stem, "uploader": "", "url": str(path.resolve()),
            "duration": meta["duration"], "license": "local"}
    write_json(d / "info.json", info)
    log(f"• Dùng file có sẵn: {path} → work/{vid}/")
    return vid


def _license_note(info):
    lic = (info.get("license") or "").lower()
    if any(h in lic for h in CC_HINTS):
        log(f"• Giấy phép: {info['license']} — được phép tái sử dụng, nhớ ghi nguồn.")
    else:
        log("⚠ Video này KHÔNG có giấy phép Creative Commons. Cắt lại cảnh quay thi đấu có bản quyền "
            "dễ bị Content ID claim/chặn. Chỉ đăng khi bạn có quyền dùng nguồn này.")


def info(vid):
    return read_json(video_dir(vid) / "info.json")
