"""Contact sheets for checking clips by eye: frames in a grid, read left→right, top→bottom.

  source window   work/<id>/sheets/src-<start>-<end>@<fps>fps-NN.jpg   times in source seconds
  rendered short  work/<id>/sheets/out-NN@<fps>fps-NN.jpg              times in the short

This ffmpeg has no drawtext, so cells carry no timestamps; the command prints when each row
starts instead (cell time = row start + column / fps).
"""

import math

from .common import OUTPUT, ROOT, log, probe, run, source_path, video_dir


def sheet(vid, start=None, end=None, fps=None, output=None, cols=None, rows=None):
    if output is not None:
        hits = sorted((OUTPUT / vid).glob(f"{output:02d}-*.mp4"))
        if not hits:
            raise SystemExit(f"Chưa có short {output:02d} trong output/{vid}/ — chạy `render` trước.")
        src = hits[0]
        start, end = 0.0, probe(src)["duration"]
        fps, cols, rows, cell = fps or 1.0, cols or 10, rows or 4, "scale=180:-2"
        name = f"out-{output:02d}"
    else:
        if start is None or end is None:
            raise SystemExit("Cần <start> <end> (giây trong video gốc), hoặc --output N.")
        src = source_path(vid)
        start, end = max(0.0, start), min(probe(src)["duration"], end)
        fps, cols, rows, cell = fps or 2.0, cols or 6, rows or 8, "scale=320:-2"
        name = f"src-{start:.1f}-{end:.1f}"
    if end <= start:
        raise SystemExit("Khoảng thời gian rỗng.")

    sdir = video_dir(vid) / "sheets"
    sdir.mkdir(parents=True, exist_ok=True)
    stem = f"{name}@{fps:g}fps"
    for old in sdir.glob(f"{stem}-*.jpg"):
        old.unlink()
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-hwaccel", "videotoolbox",
         "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src, "-an",
         "-vf", f"fps={fps},{cell},tile={cols}x{rows}:padding=4:color=white",
         "-q:v", "4", sdir / f"{stem}-%02d.jpg"], echo=False)

    per_page, row_s = cols * rows, cols / fps
    pages = sorted(sdir.glob(f"{stem}-*.jpg"))
    cells = math.ceil((end - start) * fps)
    log(f"✓ {len(pages)} trang, ~{cells} ô, {cols} ô/hàng, mỗi ô cách {1 / fps:g}s "
        f"({'giây trong short' if output is not None else 'giây trong video gốc'})")
    for p, path in enumerate(pages):
        first = start + p * per_page / fps
        starts = [first + r * row_s for r in range(rows) if first + r * row_s < end]
        log(f"  {path.relative_to(ROOT)}\n    hàng bắt đầu lúc: " + "  ".join(f"{t:.2f}" for t in starts))
