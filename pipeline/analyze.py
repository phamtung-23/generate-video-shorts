"""Step 2 — measure the long video: loudness every 0.5s, scene cuts, word-level transcript.

Outputs in work/<id>/:
  audio.wav        16 kHz mono (whisper input; delete with `clean`)
  loudness.json    {"step": 0.5, "db": [...]}  RMS level per 0.5s window
  scenes.json      [t, t, ...]                 scene-cut times in seconds
  words.json       [{"start","end","text","p"}] transcript words (empty if disabled)
"""

import re
from pathlib import Path

from .common import log, read_json, run, source_path, video_dir, write_json

STEP = 0.5  # seconds per loudness window (8000 samples @ 16 kHz)


def analyze(vid, cfg, force=False):
    d = video_dir(vid)
    src = source_path(vid)
    audio = d / "audio.wav"

    if force or not audio.exists():
        log("• Tách âm thanh 16 kHz…")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", src,
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", audio])

    if force or not (d / "loudness.json").exists():
        log("• Đo âm lượng (tiếng hò reo, bình luận viên)…")
        write_json(d / "loudness.json", {"step": STEP, "db": _loudness(audio, d)})

    if force or not (d / "scenes.json").exists():
        log("• Dò điểm chuyển cảnh…")
        write_json(d / "scenes.json", _scenes(src, d))

    tcfg = cfg["transcribe"]
    if force or not (d / "words.json").exists():
        if tcfg["enabled"]:
            log(f"• Nhận dạng lời bình luận bằng whisper (video dài mất vài phút; tiến độ: work/{vid}/whisper.log)…")
            write_json(d / "words.json", _transcribe(audio, d, tcfg))
        else:
            write_json(d / "words.json", [])

    words = read_json(d / "words.json")
    log(f"✓ Phân tích xong: {len(read_json(d / 'scenes.json'))} lần chuyển cảnh, {len(words)} từ.")


def _loudness(audio, d):
    out = d / "_rms.txt"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", audio, "-af",
         "asetnsamples=n=8000:p=0,astats=metadata=1:reset=1:measure_perchannel=none:"
         f"measure_overall=RMS_level,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file={out}",
         "-f", "null", "-"], echo=False)
    db = []
    for line in out.read_text().splitlines():
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            val = line.split("=", 1)[1]
            db.append(round(max(-90.0, float(val)), 2) if val not in ("-inf", "inf", "nan") else -90.0)
    out.unlink()
    return db


def _scenes(src, d):
    """Hard cuts via ffmpeg's scene score (0..1) on every frame; 0.25 catches broadcast cuts
    without firing on fast camera pans."""
    out = d / "_scenes.txt"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-hwaccel", "videotoolbox",
         "-i", src, "-an", "-vf",
         f"scale=320:-2,select='gt(scene\\,0.25)',metadata=mode=print:file={out}",
         "-f", "null", "-"])
    times = []
    for m in re.findall(r"pts_time:([\d.]+)", out.read_text()):
        t = round(float(m), 2)
        if not times or t - times[-1] > 0.3:
            times.append(t)
    out.unlink()
    return times


def _transcribe(audio, d, tcfg):
    model = Path(tcfg["model"]).expanduser()
    if not model.exists():
        log(f"⚠ Không thấy model whisper {model} — bỏ qua phụ đề.")
        return []
    base = d / "_whisper"
    run(["whisper-cli", "-m", model, "-f", audio, "-l", tcfg["language"], "-t", tcfg["threads"],
         # -mc 0: no text context between windows, which stops whisper's repeat loops on crowd noise
         "-ml", "1", "-sow", "-sns", "-mc", "0", "-np", "-ojf", "-of", base],
        log_file=d / "whisper.log")
    raw = read_json(base.with_suffix(".json"))
    words = []
    for seg in raw.get("transcription", []):
        text = seg.get("text", "").strip()
        tokens = [t for t in seg.get("tokens", []) if not t.get("text", "").startswith("[_")]
        if not text or not tokens:
            continue
        p = sum(t.get("p", 0) for t in tokens) / len(tokens)
        words.append({"start": seg["offsets"]["from"] / 1000, "end": seg["offsets"]["to"] / 1000,
                      "text": text, "p": round(p, 3)})
    write_json(d / "transcript_lang.json", raw.get("result", {}))
    base.with_suffix(".json").unlink()
    return _drop_repeats(_drop_hallucinations(_retime_stretched(words), tcfg["min_sentence_prob"]))


# Phrases whisper invents over noise/music (incl. the infamous Vietnamese "Ghiền Mì Gõ" outro).
HALLUCINATIONS = ("thank you", "thanks for watching", "thank you for watching", "subscribe",
                  "ghiền mì gõ", "cảm ơn các bạn đã theo dõi", "hẹn gặp lại các bạn")
STRETCHED_S = 1.0   # a single spoken word longer than this is a timing artefact
PACKED_WORD_S = 0.32


def _retime_stretched(words):
    """Whisper pins the first words of a noisy 30s window to the window start and stretches them
    until the real speech. Re-pack each such run tightly against where it actually ends."""
    out, i = [], 0
    while i < len(words):
        j = i  # extend a chain of back-to-back words
        while j + 1 < len(words) and abs(words[j + 1]["start"] - words[j]["end"]) < 0.02:
            j += 1
        chain = words[i:j + 1]
        last = max((k for k, w in enumerate(chain) if w["end"] - w["start"] > STRETCHED_S), default=-1)
        if last >= 0:
            end = chain[last]["end"]
            start = max(chain[0]["start"], end - PACKED_WORD_S * (last + 1))
            step = (end - start) / (last + 1)
            for k in range(last + 1):
                chain[k] = {**chain[k], "start": round(start + k * step, 3),
                            "end": round(start + (k + 1) * step, 3)}
        out.extend(chain)
        i = j + 1
    return out


def _drop_hallucinations(words, min_p):
    """Remove known whisper inventions, then sentences whisper itself was unsure about."""
    norm = [re.sub(r"[^\w\s]", "", w["text"].lower()).strip() for w in words]
    bad = set()
    for h in HALLUCINATIONS:
        seq = h.split()
        for i in range(len(words) - len(seq) + 1):
            if norm[i:i + len(seq)] == seq:
                bad.update(range(i, i + len(seq)))
    kept = [w for i, w in enumerate(words) if i not in bad]

    out, sentence = [], []
    for i, w in enumerate(kept):
        sentence.append(w)
        nxt = kept[i + 1] if i + 1 < len(kept) else None
        if nxt and nxt["start"] - w["end"] < 0.8 and not re.search(r"[.!?]$", w["text"]):
            continue
        if sum(x["p"] for x in sentence) / len(sentence) >= min_p:
            out.extend(sentence)
        sentence = []
    return out


def _drop_repeats(words):
    """Whisper sometimes loops a phrase ("that's what I like to see" x4). Keep a phrase of 3+ words
    once when it repeats back to back; short chants like "Goal! Goal! Goal!" stay."""
    norm = [re.sub(r"[^\w\s]", "", w["text"].lower()).strip() for w in words]
    keep = [True] * len(words)
    for n in range(8, 2, -1):
        i = 0
        while i + 2 * n <= len(words):
            j = i + n
            while j + n <= len(words) and norm[j:j + n] == norm[i:i + n]:
                for k in range(j, j + n):
                    keep[k] = False
                j += n
            i = j if j > i + n else i + 1
    return [w for w, k in zip(words, keep) if k]
