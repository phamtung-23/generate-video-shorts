"""Step 5 — title hook, word-by-word captions, impact effects and the sound mix with HyperFrames.

Each work/<id>/clips/NN/ becomes a small HyperFrames project (index.html from template/).
You can open one in HyperFrames Studio to tweak by hand:  npx hyperframes preview work/<id>/clips/NN
Final files land in output/<id>/NN-<title>.mp4, with upload notes in output/<id>/upload.md.
HyperFrames keeps an undo history of every project (a copy of clip.mp4 per re-cut); it is pointed
at work/<id>/.hf-history so `clean --all` takes it too instead of filling ~/.cache/hyperframes.
"""

import json
import os
import re
import shutil
import time

from . import audio
from .common import (OUTPUT, TEMPLATE, log, parse_only, probe, read_json, run, slugify,
                     video_dir)

H = 1920
CAPTION_WIDTH = 860  # 1080 minus side padding that keeps text clear of the Shorts buttons


def render(vid, cfg, only=None, quality=None, check=False):
    d = video_dir(vid)
    clips = read_json(d / "highlights.json")["clips"]
    info = read_json(d / "info.json")
    only = parse_only(only)
    rc = cfg["render"]
    npx = ["npx", "--yes", f"hyperframes@{rc['hyperframes_version']}"]
    env = {**os.environ, "HYPERFRAMES_HISTORY_ROOT": str(d / ".hf-history")}
    out_dir = OUTPUT / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    pruned = _prune_outputs(out_dir, clips, info, only)

    rendered = 0
    for c in clips:
        if not c["enabled"] or (only and c["n"] not in only):
            continue
        cdir = d / "clips" / f"{c['n']:02d}"
        if not (cdir / "assets" / "clip.mp4").exists():
            log(f"⚠ Clip {c['n']:02d} chưa được cắt — chạy `cut` trước.")
            continue
        layout = read_json(cdir / "layout.json")
        build_project(cdir, c, layout, read_json(cdir / "captions.json"), cfg)
        if check:
            run(npx + ["check", cdir], env=env)

        out = out_dir / _output_name(c, info)
        log(f"• Render clip {c['n']:02d} → {out.relative_to(OUTPUT.parent)}")
        t0 = time.time()
        run(npx + ["render", cdir, "--output", out, "--fps", rc["fps"],
                   "--quality", quality or rc["quality"], "--quiet"],
            echo=False, log_file=cdir / "render.log", env=env)
        if probe(out)["has_audio"]:
            # effects-only files sit lower: the trending song added in the app should lead
            full_mix = layout.get("music") or layout.get("voice") or layout.get("original") == "full"
            _master(out, -14 if full_mix else -18)
        meta = probe(out)
        ok = (meta["width"], meta["height"]) == (1080, 1920) and abs(meta["duration"] - layout["duration"]) < 0.3
        log(f"  {'✓' if ok else '⚠'} {meta['width']}x{meta['height']}, {meta['duration']:.1f}s, "
            f"render {time.time() - t0:.0f}s")
        rendered += 1

    # notes cover every short already in output/, not just the ones rendered this run
    done = []
    for c in clips:
        name = _output_name(c, info)
        layout_path = d / "clips" / f"{c['n']:02d}" / "layout.json"
        if c["enabled"] and (out_dir / name).exists() and layout_path.exists():
            layout = read_json(layout_path)
            done.append((c, name, audio.credits(layout), layout))
    if rendered or pruned:
        _upload_notes(out_dir, info, done, cfg)
    if rendered:
        log(f"✓ Xong {rendered} short → {out_dir}/  (gợi ý tiêu đề/mô tả: upload.md)")


def _output_name(clip, info):
    return f"{clip['n']:02d}-{slugify(clip.get('title') or info['title'], 40)}.mp4"


def _prune_outputs(out_dir, clips, info, only):
    """Keep output/ in step with highlights.json: drop shorts of disabled or removed clips, and the
    old file of a clip about to be re-rendered under a new title."""
    by_n, pruned = {c["n"]: c for c in clips}, 0
    for f in sorted(out_dir.glob("[0-9][0-9]-*.mp4")):
        c = by_n.get(int(f.name[:2]))
        renaming = c and c["enabled"] and (not only or c["n"] in only) and f.name != _output_name(c, info)
        if not c or not c["enabled"] or renaming:
            f.unlink()
            pruned += 1
            log(f"  xoá bản cũ: {f.name}")
    return pruned


def build_project(cdir, clip, layout, captions, cfg):
    style, fx = cfg["style"], cfg["effects"]
    title = (clip.get("title") or "").strip()
    dur = layout["duration"]
    lines = []
    if style.get("captions", True):
        for line in captions.get("lines", []):
            if line.get("text", "").strip() and line["start"] < dur:
                words = _final_words(line)
                chars = max(len(line["text"]), 6)
                lines.append({"start": line["start"], "end": min(line["end"], dur), "words": words,
                              "size": max(54, min(96, int(CAPTION_WIDTH * 1.25 / chars)))})

    data = {
        "duration": dur,
        "title": title,
        "titleSize": max(52, min(96, int(2 * CAPTION_WIDTH / (0.74 * max(len(title), 1))))),
        "handle": style.get("channel_handle", ""),
        "layout": _overlay_layout(layout),
        "impacts": _impacts(layout),
        "effects": {"punch": fx["impact_punch"], "flash": fx["impact_flash"]},
        "style": {"accent": style["accent"], "titleBg": style["title_bg"],
                  "titleColor": style["title_color"], "captionColor": style["caption_color"],
                  "uppercase": style["caption_uppercase"]},
        "lines": lines,
    }
    html = (TEMPLATE / "index.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html, n = re.subn(r"/\*__DATA__\*/.*?\n      \};", lambda _: payload + ";", html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("template/index.html thiếu khối DATA — đừng xoá dòng /*__DATA__*/.")
    html = html.replace("__DURATION__", f"{dur:.3f}")
    own_sound = layout.get("has_audio") and layout.get("original", "full") == "full" and not layout.get("voice")
    html = html.replace("__VIDEO_AUDIO__", 'data-has-audio="true"' if own_sound else "muted")
    html = html.replace("<!--__AUDIO__-->", "\n      ".join(_audio_tags(layout, captions.get("lines", []), cfg)))
    (cdir / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(TEMPLATE / "hyperframes.json", cdir / "hyperframes.json")


def _overlay_layout(layout):
    """Title above the picture and captions below it in blur mode; fixed spots in crop mode."""
    if layout["mode"] == "blur":
        top, bottom = layout["video_top"], layout["video_bottom"]
        title = {"titleTop": None, "titleBottom": top - 36} if top >= 420 else {"titleTop": 210, "titleBottom": None}
        # captions just under the picture while one line (~120px) still clears the Shorts UI
        cap = bottom + 32 if bottom + 32 + 120 <= 1600 else 1200
        return {**title, "captionTop": cap, "focusY": (top + bottom) // 2}
    return {"titleTop": 230, "titleBottom": None, "captionTop": 1200, "focusY": H // 2}


def _audio_tags(layout, lines, cfg):
    """<audio> clips for the mix. Times are clip-local seconds; SFX are placed by their own "hit"
    (the transient inside the file) so the hit lands exactly on the impact."""
    ac, dur, imps = cfg["audio"], layout["duration"], _impacts(layout)
    speech = layout.get("voice") or layout.get("original") == "full"
    tags = []

    def tag(id_, src, start, track, vol, media_start=0.0, length=None, lane=None):
        length = min(length if length is not None else dur, dur - start)
        if length <= 0.05:
            return
        attrs = [f'id="{id_}"', f'src="{src}"', f'data-start="{start:.3f}"', f'data-duration="{length:.3f}"',
                 f'data-track-index="{track}"', f'data-volume="{vol}"']
        if media_start > 0:
            attrs.append(f'data-media-start="{media_start:.3f}"')
        if lane:
            attrs.append("data-automation='" + json.dumps(lane) + "'")
        tags.append("<audio " + " ".join(attrs) + "></audio>")

    if layout.get("voice"):
        tag("voice", "assets/voice.m4a", 0, 1, 1)
    if layout.get("ambience", layout.get("voice")):
        tag("ambience", "assets/ambience.m4a", 0, 3, ac["ambience_volume"])
    if layout.get("music"):
        tag("bgm", "assets/music.m4a", 0, 2, 1, lane=_music_lane(dur, lines if speech else [], imps, ac))

    sfx, v = audio.sfx_library(), ac["sfx_volume"]
    cues = [("whoosh", 0.1, 0.6)]
    for k, t in enumerate(imps):  # every goal gets the swell + bass hit; the crowd roars once
        cues += [("swell", t, 0.5), ("impact", t, 1.0)] + ([("crowd", t + 0.3, 0.7)] if k == 0 else [])
    cues = [cue for cue in cues if cue[0] in layout.get("sfx", [])]
    for track, (key, at, gain) in enumerate(cues, start=4):
        item = sfx[key]
        start = at - item["hit"]
        media_start = max(0.0, -start)
        length = min(item["duration"] - media_start, dur - max(0.0, start))
        fade = None
        if key == "crowd":  # let the roar ring, then fade with the short
            fade = {"version": 1, "lanes": [{"target": "volume", "points": [
                {"t": 0, "v": 1}, {"t": round(max(0.1, length - 1.5), 3), "v": 1}, {"t": round(length, 3), "v": 0}]}]}
        tag(f"sfx-{track}-{key}", f"assets/{item['file']}", max(0.0, start), track, round(v * gain, 2),
            media_start, length, fade)
    return tags


def _impacts(layout):
    """Clip-local impact times; older layouts stored a single "impact"."""
    if "impacts" in layout:
        return layout["impacts"]
    return [layout["impact"]] if layout.get("impact") is not None else []


def _music_lane(dur, lines, impacts, ac):
    """Music at full bed level, ducked under every caption line (= commentary), dropped to silence
    for a beat on the impact so the hit and crowd roar punch through."""
    bed, duck, step = ac["music_volume"], ac["music_duck_volume"], 0.05
    n = int(dur / step) + 1
    vals = []
    for i in range(n):
        t = i * step
        v = duck if any(l["start"] - 0.25 <= t <= l["end"] + 0.35 for l in lines) else bed
        if ac["music_drop_at_impact"] and any(i - 0.05 <= t <= i + 0.6 for i in impacts):
            v = 0.0
        vals.append(v)
    smooth = [sum(vals[max(0, i - 2):i + 3]) / len(vals[max(0, i - 2):i + 3]) for i in range(n)]
    points = [{"t": round(i * step, 3), "v": round(smooth[i], 3)} for i in range(n)
              if i in (0, n - 1) or abs((smooth[i] - smooth[i - 1]) - (smooth[i + 1] - smooth[i])) > 1e-4]
    return {"version": 1, "lanes": [{"target": "volume", "points": points}]}


def _master(out, lufs):
    """Gentle compression to even out quiet commentary vs loud crowd, then the target loudness
    (-14 LUFS = YouTube's level). Picture is copied untouched."""
    tmp = out.with_suffix(".master.mp4")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", out, "-c:v", "copy",
         "-af", "acompressor=threshold=-22dB:ratio=3:attack=15:release=250:makeup=2,"
         f"loudnorm=I={lufs}:TP=-1.5:LRA=9", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", tmp], echo=False)
    tmp.replace(out)


def _final_words(line):
    """Keep whisper's word timing; if the line text was edited, spread the new words over the line."""
    tokens = line["text"].split()
    if tokens == [w["text"] for w in line.get("words", [])]:
        return line["words"]
    span = max(0.2, line["end"] - line["start"])
    total = sum(len(t) for t in tokens) or 1
    out, t = [], line["start"]
    for tok in tokens:
        step = span * len(tok) / total
        out.append({"text": tok, "start": round(t, 3), "end": round(t + step, 3)})
        t += step
    return out


def _upload_notes(out_dir, info, rendered, cfg):
    lic = info.get("license") or ""
    source = "" if lic == "local" else f"Source: {info.get('uploader') or 'original video'} — {info.get('url', '')}\n"
    up = cfg["upload"]
    parts = [f"# Ghi chú đăng tải — {info.get('title', '')}\n",
             f"Giấy phép video gốc: {lic or 'không rõ'}\n"]
    if not cfg["audio"]["music"]:
        parts.append("\n## Âm thanh thịnh hành — thêm trong app YouTube\n\n"
                     "File chỉ có hiệu ứng (whoosh, bass hit, khán giả). Đăng từ điện thoại: YouTube → **+** → "
                     "**Tạo Short** → tải video lên → **Thêm âm thanh** → chọn bài trong mục *Thịnh hành*, "
                     "kéo chọn đoạn sao cho **drop** của bài rơi đúng mốc ghi bàn ghi bên dưới; chỉnh "
                     "*Âm thanh gốc* ~40–60% để vẫn nghe tiếng khán giả. Thêm trong app thì YouTube tự lo bản quyền "
                     "và video được gắn vào trang của âm thanh đó; ghép sẵn bài có bản quyền vào file thì bị "
                     "Content ID claim/chặn.\n\nGợi ý (danh sách tham khảo, nên xem mục Thịnh hành trong app):\n\n"
                     + "".join(f"- {t}\n" for t in up["sound_suggestions"]))
    for c, name, credits, layout in rendered:
        title = c.get("title") or "(chưa đặt tiêu đề — sửa trong highlights.json)"
        sounds = "".join(line + "\n" for line in credits)
        imps = _impacts(layout)
        cue = ("- Mốc ghi bàn (canh drop của nhạc): " + ", ".join(f"**0:{t:04.1f}**" for t in imps) + "\n"
               if imps else "")
        parts.append(f"\n## {name}\n\n- Tiêu đề: {title} #shorts\n{cue}- Mô tả:\n\n"
                     f"```\n{title}\n\n{source}{sounds}\n{up['hashtags']}\n```\n")
    (out_dir / "upload.md").write_text("".join(parts), encoding="utf-8")
