"""Step 4 — cut each enabled highlight, reframe it to vertical 1080x1920, write its caption lines.

Per clip, in work/<id>/clips/NN/:
  assets/clip.mp4   vertical clip, original audio normalised to -14 LUFS (YouTube's level)
  assets/voice.m4a  audio.original = "voice": commentary + crowd split from the source music (Demucs)
  assets/music.m4a  audio.music = true: CC0 music bed from assets/music, cut at its strongest entrance
  assets/*.mp3      sound effects from assets/sfx (timed at render)
  layout.json       where the picture sits, impact times, which sounds were used
  captions.json     {"lines": [{"start","end","text","words":[...]}]} — edit "text" to fix or
                    translate a line (word timing is re-spread when text changes), delete a line
                    to drop it. Kept on re-cut as long as the clip's start/end stay the same.

Reframe modes:
  blur  whole 16:9 picture in the middle, blurred copy fills the frame (safe for wide sports shots)
  crop  fill the frame, keep a 9:16 slice at crop_x (0 = left, 0.5 = centre, 1 = right)
"""

import re

from . import audio, highlights
from .common import log, parse_only, probe, read_json, run, source_path, video_dir, write_json

W, H = 1080, 1920


def cut(vid, cfg, only=None, mode=None):
    d = video_dir(vid)
    clips = read_json(d / "highlights.json")["clips"]
    src = source_path(vid)
    meta = probe(src)
    words = read_json(d / "words.json")
    only = parse_only(only)
    rc, ac = cfg["reframe"], cfg["audio"]
    # audio.original: "none" = drop the source sound, "voice" = keep only commentary/crowd, "full" = as is
    original = ac["original"] if meta["has_audio"] else "none"
    if original == "voice" and not audio.demucs_available():
        log("⚠ Chưa cài Demucs (.venv) — dùng nguyên âm thanh gốc. Xem README.")
        original = "full"

    done = []
    for c in clips:
        if not c["enabled"] or (only and c["n"] not in only):
            continue
        cdir = d / "clips" / f"{c['n']:02d}"
        (cdir / "assets").mkdir(parents=True, exist_ok=True)
        m = mode or c.get("mode") or rc["mode"]
        vf, layout = _reframe(m, meta, c.get("zoom", rc["zoom"]), c.get("crop_x", rc["crop_x"]),
                              c.get("offset_y", rc["offset_y"]))
        dur = round(c["end"] - c["start"], 3)
        log(f"• Clip {c['n']:02d}: {c['start']:.1f}s → {c['end']:.1f}s ({dur:.0f}s, {m})")

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
               "-ss", f"{c['start']:.3f}", "-i", src, "-t", f"{dur:.3f}",
               "-filter_complex", vf, "-map", "[v]",
               "-c:v", "h264_videotoolbox", "-b:v", "16M", "-profile:v", "high", "-pix_fmt", "yuv420p"]
        if meta["has_audio"]:
            cmd += ["-map", "0:a:0", "-af",
                    f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.15,"
                    f"afade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        cmd += ["-movflags", "+faststart", cdir / "assets" / "clip.mp4"]
        run(cmd, echo=False)

        layout.update({"duration": dur, "has_audio": meta["has_audio"], "original": original,
                       "voice": False, "ambience": False, "music": None, "sfx": [],
                       "impacts": _impacts(c, words, cfg)})
        assets = cdir / "assets"
        if original == "voice":
            log("  tách giọng bình luận khỏi nhạc gốc (Demucs)…")
            audio.separate_voice(assets / "clip.mp4", assets / "voice.m4a", cdir / "_sep")
            layout["voice"] = True
        if ac["ambience"] and original != "full":
            audio.ambience_bed(dur, assets / "ambience.m4a", c["n"])
            layout["ambience"] = True
        track = audio.pick_music(c) if ac["music"] else None
        if track:
            offset = audio.music_bed(track, dur, assets / "music.m4a")
            layout["music"] = {**track, "offset": offset}
            log(f"  nhạc: {track['title']} (từ giây {offset:.0f})")
        if ac["sfx"]:
            layout["sfx"] = ["whoosh"] + (["swell", "impact", "crowd"] if layout["impacts"] else [])
            audio.copy_sfx(assets, layout["sfx"])
        write_json(cdir / "layout.json", layout)
        caps = cdir / "captions.json"
        window = [c["start"], c["end"]]
        if caps.exists() and read_json(caps).get("source") == window:
            log("  giữ captions.json đã có (clip không đổi khung thời gian)")
        else:
            write_json(caps, {"source": window,
                              "lines": _lines(words, c["start"], dur, cfg["style"]["caption_max_words"])})
        done.append(c)
    highlights.thumbnails(vid, done)
    log(f"✓ Đã cắt {len(done)} clip dọc → work/{vid}/clips/  (ảnh xem nhanh: work/{vid}/thumbs/)")


def _impacts(c, words, cfg):
    """Clip-local seconds of the key moments (ball in the net). highlights.json "impact" may be one
    source-time number or a list; when empty, guess just before the commentator's first "goal"-type
    shout, else the loudness peak. Moments closer than 2.5s are merged so effects don't pile up."""
    dur = c["end"] - c["start"]
    given = c.get("impact")
    if given is None:
        keys = [k.split() for k in cfg["highlights"]["impact_keywords"]]
        norm = [(w["start"], re.sub(r"[^\w\s]", "", w["text"].lower()).split()) for w in words
                if c["start"] <= w["start"] < c["end"]]
        flat = [(t0, tok) for t0, toks in norm for tok in toks]
        given = c.get("peak")
        for i, (t0, _) in enumerate(flat):
            if any([tok for _, tok in flat[i:i + len(k)]] == k for k in keys):
                given = t0 - 0.7
                break
    times = given if isinstance(given, list) else [given]
    local = sorted(round(t - c["start"], 2) for t in times
                   if t is not None and 0.5 <= t - c["start"] <= dur - 0.5)
    kept = []
    for t in local:
        if not kept or t - kept[-1] >= 2.5:
            kept.append(t)
    return kept


def _reframe(mode, meta, zoom, crop_x, offset_y):
    sw, sh = meta["width"], meta["height"]
    if mode == "crop" or sh >= sw:
        vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H}:(iw-{W})*{crop_x}:(ih-{H})/2,setsar=1[v]")
        return vf, {"mode": "crop", "video_top": 0, "video_bottom": H}
    if mode != "blur":
        raise SystemExit(f"Chế độ reframe không hợp lệ: {mode} (dùng blur hoặc crop)")
    fg_w = _even(W * zoom)
    fg_h = min(_even(fg_w * sh / sw), H)
    top = max(0, min(H - fg_h, (H - fg_h) // 2 + int(offset_y)))
    vf = ("[0:v]split=2[a][b];"
          "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
          f"scale={W}:{H},eq=brightness=-0.12:saturation=1.15[bg];"
          f"[b]scale={fg_w}:{fg_h},crop={min(fg_w, W)}:{fg_h}[fg];"
          f"[bg][fg]overlay=(W-w)/2:{top},setsar=1[v]")
    return vf, {"mode": "blur", "video_top": top, "video_bottom": top + fg_h}


def _lines(words, clip_start, dur, max_words):
    ws = []
    for w in words:
        t0, t1 = w["start"] - clip_start, w["end"] - clip_start
        if t0 < 0 or t0 >= dur - 0.1:
            continue
        text = w["text"].strip().rstrip(".,;:")
        if text:
            ws.append({"text": text, "start": round(t0, 3), "end": round(min(t1, dur), 3),
                       "brk": bool(re.search(r"[.!?,;:]$", w["text"].strip()))})
    lines, cur = [], []
    for i, w in enumerate(ws):
        cur.append(w)
        nxt = ws[i + 1] if i + 1 < len(ws) else None
        chars = sum(len(x["text"]) + 1 for x in cur)
        if (not nxt or w["brk"] or len(cur) >= max_words or chars + len(nxt["text"]) > 20
                or nxt["start"] - w["end"] > 0.5):
            lines.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                          "text": " ".join(x["text"] for x in cur),
                          "words": [{k: x[k] for k in ("text", "start", "end")} for x in cur]})
            cur = []
    return lines


def _even(x):
    return int(round(x / 2)) * 2
