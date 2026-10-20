"""Step 3 — score every 0.5s of the match and pick the best non-overlapping highlight windows.

Signals (all relative to the video itself, so it works across sports and broadcasters):
  audio     crowd roar / excited commentary: loudness above a rolling 60s baseline, in sigmas
  keywords  commentary words like "goal", "what a", "vào", "siêu phẩm" (from whisper)
  scene     a burst of cuts right after the moment (broadcast replays)

Writes work/<id>/highlights.json — edit it (title, start/end, enabled) before `cut`/`render`.
"""

import math
import re
import statistics

from .common import fmt_time, log, probe, read_json, run, source_path, video_dir, write_json

SMOOTH_S = 3.0     # loudness smoothing window
BASELINE_S = 60.0  # rolling baseline window
KW_SPREAD_S = 3.0  # how far a keyword hit spreads its score
REPLAY_S = 20.0    # look-ahead for replay cuts


def detect(vid, cfg, count=None, target=None, force=False):
    d = video_dir(vid)
    out = d / "highlights.json"
    if out.exists() and not force:
        log(f"• Đã có {out.name} (có thể bạn đã sửa tay). Dùng --force để dò lại.")
        print_table(vid)
        return

    hc = cfg["highlights"]
    count = count or hc["count"]
    target = target or hc["target_seconds"]
    loud = read_json(d / "loudness.json")
    db, step = loud["db"], loud["step"]
    scenes = read_json(d / "scenes.json")
    words = read_json(d / "words.json")
    duration = probe(source_path(vid))["duration"] or len(db) * step
    n = len(db)
    if n == 0:
        raise SystemExit("Không có dữ liệu âm lượng — chạy lại `analyze`.")

    audio = _audio_score(db, step)
    kw, kw_hits = _keyword_score(words, hc["keywords"], n, step)
    sc = _scene_score(scenes, n, step)
    w = hc["weights"]
    score = [w["audio"] * a + w["keywords"] * k + w["scene"] * s for a, k, s in zip(audio, kw, sc)]

    lo, hi = hc["skip_start_seconds"], duration - hc["skip_end_seconds"]
    picks = []
    for i in sorted(range(n), key=lambda i: -score[i]):
        if len(picks) >= count or score[i] < hc["min_score"]:
            break
        peak = i * step
        if not lo <= peak <= hi:
            continue
        start = max(lo, peak - hc["pre_roll_ratio"] * target)
        end = min(hi, start + target)
        start = max(lo, end - target)
        if any(start < p["end"] + hc["min_gap_seconds"] and end > p["start"] - hc["min_gap_seconds"]
               for p in picks):
            continue
        start, end = _snap(start, end, peak, scenes, words, hc, lo, hi)
        hits = sorted({h for t, h in kw_hits if start <= t <= end})
        cuts_after = sum(1 for t in scenes if peak < t <= peak + REPLAY_S)
        reasons = []
        loudest = max(audio[max(0, i - 6):i + 7])
        if loudest > 0:
            reasons.append(f"âm lượng cao (+{loudest + 1:.1f}σ)")
        if hits:
            reasons.append("từ khoá: " + ", ".join(hits[:5]))
        if cuts_after:
            reasons.append(f"{cuts_after} lần cắt cảnh sau đó")
        picks.append({
            "enabled": True,
            "start": round(start, 2),
            "end": round(end, 2),
            "peak": round(peak, 2),
            "score": round(score[i], 2),
            "reasons": reasons,
            "title": "",
            "impact": None,
            "music": "",
            "excerpt": _excerpt(words, start, end),
        })

    clips = [{"n": rank, **p} for rank, p in enumerate(picks, 1)]
    write_json(out, {"video_id": vid, "clips": clips})
    thumbnails(vid, clips)
    log(f"✓ Tìm được {len(clips)} highlight → {out}")
    print_table(vid)


def print_table(vid):
    data = read_json(video_dir(vid) / "highlights.json")
    log(f"\n  #  bật  bắt đầu   kết thúc  dài   điểm  lý do")
    for c in data["clips"]:
        dur = c["end"] - c["start"]
        log(f" {c['n']:>2}  {'✓' if c['enabled'] else '✗'}   {fmt_time(c['start']):>8}  {fmt_time(c['end']):>8}"
            f"  {dur:4.0f}s  {c['score']:4.1f}  {'; '.join(c['reasons'])}")
        if c.get("title"):
            log(f"         tiêu đề: {c['title']}")
        if c.get("excerpt"):
            log(f"         “{c['excerpt'][:110]}”")
    log(f"\n  Ảnh xem nhanh (đầu | đỉnh | cuối): work/{vid}/thumbs/NN.jpg\n")


def _audio_score(db, step):
    win = max(1, int(SMOOTH_S / step))
    smooth = _moving_avg(db, win)
    base = _rolling_median(smooth, int(BASELINE_S / step), stride=max(1, int(5 / step)))
    dev = [s - b for s, b in zip(smooth, base)]
    med = statistics.median(dev)
    sigma = max(1.5, 1.4826 * statistics.median(abs(x - med) for x in dev))
    # Subtract 1σ so normal ups and downs of a broadcast score nothing; cap outliers.
    return [min(5.0, max(0.0, x / sigma - 1.0)) for x in dev]


def _keyword_score(words, keywords, n, step):
    tokens = [(w["start"], _norm(w["text"])) for w in words]
    tokens = [(t, x) for t, x in tokens if x]
    seqs = [(k, _norm(k).split()) for k in keywords]
    hits = []
    for i in range(len(tokens)):
        for k, seq in seqs:
            if seq and [x for _, x in tokens[i:i + len(seq)]] == seq:
                hits.append((tokens[i][0], k))
    series = [0.0] * n
    reach = int(2 * KW_SPREAD_S / step)
    for t, _ in hits:
        c = int(t / step)
        for j in range(max(0, c - reach), min(n, c + reach + 1)):
            series[j] += math.exp(-((j - c) * step / KW_SPREAD_S) ** 2)
    return [min(4.0, s) for s in series], hits


def _scene_score(scenes, n, step):
    per_bin = [0] * n
    for t in scenes:
        if 0 <= int(t / step) < n:
            per_bin[int(t / step)] += 1
    prefix = [0]
    for c in per_bin:
        prefix.append(prefix[-1] + c)
    ahead = int(REPLAY_S / step)
    counts = [prefix[min(n, i + ahead + 1)] - prefix[i + 1] for i in range(n)]
    med = statistics.median(counts) if counts else 0
    return [min(2.0, max(0.0, (c - med) / max(1.0, med))) for c in counts]


def _snap(start, end, peak, scenes, words, hc, lo, hi):
    """Start/end on a camera cut when one is close, and never stop mid-word."""
    near = [t for t in scenes if start - 4 <= t <= start + 2 and t <= peak - 3]
    if near:
        start = min(near, key=lambda t: abs(t - start)) + 0.05
    near = [t for t in scenes if end - 4 <= t <= end + 4 and t >= peak + 3]
    if near:
        end = min(near, key=lambda t: abs(t - end)) - 0.05
    for w in words:
        if w["start"] < end < w["end"]:
            end = w["end"] + 0.25
            break
    end = min(hi, max(end, start + hc["min_seconds"]), start + hc["max_seconds"])
    return max(lo, start), end


def _excerpt(words, start, end, limit=220):
    text = " ".join(w["text"] for w in words if start <= w["start"] < end)
    return text[:limit]


def thumbnails(vid, picks):
    """thumbs/NN.jpg = start | key moment | end. The key moment is the hand-set impact when there
    is one (detect's peak goes stale once start/end are edited)."""
    src = source_path(vid)
    tdir = video_dir(vid) / "thumbs"
    tdir.mkdir(exist_ok=True)
    for p in picks:
        key = p.get("impact")
        key = key[0] if isinstance(key, list) and key else key
        key = p["peak"] if key is None or isinstance(key, list) else key
        ts = [p["start"] + 0.5, min(max(key, p["start"] + 0.5), p["end"] - 0.5), p["end"] - 0.5]
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for t in ts:
            cmd += ["-ss", f"{t:.2f}", "-i", src]
        cmd += ["-filter_complex", "[0:v]scale=480:-2[a];[1:v]scale=480:-2[b];[2:v]scale=480:-2[c];"
                "[a][b][c]hstack=3", "-frames:v", "1", "-q:v", "4", tdir / f"{p['n']:02d}.jpg"]
        run(cmd, echo=False)


def _norm(text):
    return re.sub(r"[^\w\s]", " ", text.lower()).strip()


def _moving_avg(xs, win):
    half = win // 2
    prefix = [0.0]
    for x in xs:
        prefix.append(prefix[-1] + x)
    out = []
    for i in range(len(xs)):
        a, b = max(0, i - half), min(len(xs), i + half + 1)
        out.append((prefix[b] - prefix[a]) / (b - a))
    return out


def _rolling_median(xs, win, stride):
    half = win // 2
    n = len(xs)
    anchors = list(range(0, n, stride))
    vals = [statistics.median(xs[max(0, i - half):min(n, i + half + 1)]) for i in anchors]
    out = []
    for i in range(n):
        k = min(i // stride, len(anchors) - 1)
        if k + 1 < len(anchors):
            f = (i - anchors[k]) / stride
            out.append(vals[k] * (1 - f) + vals[k + 1] * f)
        else:
            out.append(vals[k])
    return out
