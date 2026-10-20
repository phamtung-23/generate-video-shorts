#!/usr/bin/env python3
"""Sports Shorts pipeline: long video → highlights → vertical 9:16 clips with title + captions.

  python3 shorts.py run <link|file>          all steps in one go
  python3 shorts.py download <link|file>     1. fetch the video          → work/<id>/
  python3 shorts.py analyze <id>             2. loudness, cuts, transcript
  python3 shorts.py detect <id>              3. pick highlights          → work/<id>/highlights.json
  python3 shorts.py cut <id>                 4. vertical clips + captions → work/<id>/clips/NN/
  python3 shorts.py render <id>              5. title/captions, final MP4 → output/<id>/
  python3 shorts.py list <id>                show the highlight table
  python3 shorts.py sheet <id> <start> <end> contact sheet of the source (or --output N: a short)
  python3 shorts.py clean <id>               delete the big source/audio files to free disk
  python3 shorts.py clean <id> --all         delete everything but output/<id>

Between steps you can edit work/<id>/highlights.json (title, start/end, enabled, mode)
and work/<id>/clips/NN/captions.json (caption text), then re-run cut/render.
"""

import argparse
import re
import shutil
from pathlib import Path

from pipeline import analyze, cut, download, highlights, render, review
from pipeline.common import OUTPUT, dir_size, load_config, log, video_dir

HF_HISTORY = Path.home() / ".cache" / "hyperframes" / "history"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="chạy toàn bộ pipeline")
    p.add_argument("source", help="link YouTube/… hoặc đường dẫn file video")
    _detect_args(p)
    _cut_args(p)
    _render_args(p)
    p.add_argument("--lang", help="ngôn ngữ bình luận cho whisper: auto, vi, en, …")

    p = sub.add_parser("download", help="tải video hoặc nhận file có sẵn")
    p.add_argument("source")

    p = sub.add_parser("analyze", help="đo âm lượng, chuyển cảnh, nhận dạng lời")
    p.add_argument("id")
    p.add_argument("--lang")
    p.add_argument("--force", action="store_true", help="phân tích lại từ đầu")

    p = sub.add_parser("detect", help="chọn các khoảnh khắc highlight")
    p.add_argument("id")
    _detect_args(p)
    p.add_argument("--force", action="store_true", help="ghi đè highlights.json đã sửa tay")

    p = sub.add_parser("cut", help="cắt và chuyển sang khung dọc 9:16")
    p.add_argument("id")
    _cut_args(p)
    p.add_argument("--only", help="chỉ các clip này, vd 1,3-4")

    p = sub.add_parser("render", help="thêm tiêu đề + phụ đề, xuất MP4")
    p.add_argument("id")
    _render_args(p)
    p.add_argument("--only", help="chỉ các clip này, vd 1,3-4")
    p.add_argument("--check", action="store_true", help="chạy hyperframes check trước khi render")

    p = sub.add_parser("list", help="xem bảng highlight")
    p.add_argument("id")

    p = sub.add_parser("sheet", help="ảnh lưới nhiều khung hình để duyệt bằng mắt")
    p.add_argument("id")
    p.add_argument("start", type=float, nargs="?", help="giây bắt đầu trong video gốc")
    p.add_argument("end", type=float, nargs="?", help="giây kết thúc trong video gốc")
    p.add_argument("--fps", type=float, help="số khung mỗi giây (mặc định 2; --output: 1)")
    p.add_argument("--output", type=int, metavar="N", help="xem short NN đã render thay vì video gốc")

    p = sub.add_parser("clean", help="xoá source/audio để giải phóng ổ đĩa")
    p.add_argument("id")
    p.add_argument("--all", action="store_true", help="xoá cả thư mục work/<id> + lịch sử HyperFrames (giữ output)")

    a = ap.parse_args()
    cfg = load_config()
    if getattr(a, "lang", None):
        cfg["transcribe"]["language"] = a.lang

    if a.cmd == "run":
        vid = download.download(a.source, cfg)
        analyze.analyze(vid, cfg)
        highlights.detect(vid, cfg, count=a.count, target=a.target)
        cut.cut(vid, cfg, mode=a.mode)
        render.render(vid, cfg, quality=a.quality)
    elif a.cmd == "download":
        vid = download.download(a.source, cfg)
        log(f"\nID video: {vid}   → tiếp: python3 shorts.py analyze {vid}")
    elif a.cmd == "analyze":
        analyze.analyze(a.id, cfg, force=a.force)
    elif a.cmd == "detect":
        highlights.detect(a.id, cfg, count=a.count, target=a.target, force=a.force)
    elif a.cmd == "cut":
        cut.cut(a.id, cfg, only=a.only, mode=a.mode)
    elif a.cmd == "render":
        render.render(a.id, cfg, only=a.only, quality=a.quality, check=a.check)
    elif a.cmd == "list":
        highlights.print_table(a.id)
    elif a.cmd == "sheet":
        review.sheet(a.id, a.start, a.end, fps=a.fps, output=a.output)
    elif a.cmd == "clean":
        _clean(a.id, a.all)


def _detect_args(p):
    p.add_argument("--count", type=int, help="số short muốn tạo (mặc định theo config.json)")
    p.add_argument("--target", type=float, help="độ dài mỗi short, giây (mặc định 30)")


def _cut_args(p):
    p.add_argument("--mode", choices=["blur", "crop"], help="blur: giữ cả khung hình + nền mờ; crop: cắt đầy màn hình")


def _render_args(p):
    p.add_argument("--quality", choices=["draft", "looks", "delivery"], help="draft để xem nhanh")


def _clean(vid, everything):
    d = video_dir(vid)
    if not d.exists():
        log(f"• Không có work/{vid} — không còn gì để xoá.")
        return
    if everything:
        # renders before .hf-history (or a manual `hyperframes preview`) kept their history here
        old = [HF_HISTORY / i for i in _history_ids(d) if (HF_HISTORY / i).is_dir()]
        freed = dir_size(d) + sum(dir_size(h) for h in old)
        shutil.rmtree(d)
        for h in old:
            shutil.rmtree(h)
        log(f"✓ Giải phóng {freed / 1e9:.2f} GB: xoá work/{vid}"
            + (f" và {len(old)} lịch sử HyperFrames" if old else "") + f". {OUTPUT.name}/{vid} vẫn giữ.")
        return
    freed = 0
    for f in [*d.glob("source.*"), d / "audio.wav"]:
        if f.exists() or f.is_symlink():
            freed += dir_size(f)
            f.unlink()
    log(f"✓ Giải phóng {freed / 1e9:.2f} GB. Clip đã cắt và {OUTPUT.name}/{vid} vẫn giữ.")


def _history_ids(d):
    ids = set()
    for f in d.glob("clips/*/.hyperframes/history-id"):
        hid = f.read_text().strip()
        if re.fullmatch(r"[0-9a-f-]{36}", hid):
            ids.add(hid)
    return sorted(ids)


if __name__ == "__main__":
    main()
