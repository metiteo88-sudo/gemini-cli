#!/usr/bin/env python3
"""audio-trace — ردگیری صفحه‌به‌صفحه از «متن استخراج‌شده» تا «صدای نهایی».

دو فرمان:

  capture INPUT --out DIR [--fake] [-- آرگومان‌های اضافهٔ fva]
      همان fva.py واقعی را اجرا می‌کند و فقط «ضبط» می‌کند؛ هیچ منطقی را عوض نمی‌کند.
      پنج مرحله در DIR/trace.json ذخیره می‌شود:
        s1 استخراج  ← extract_items
        s2 پردازش   ← process_text
        s3 فصل‌ها    ← split_chapters
        s4 به فرید  ← متن/SSML هر تکه (_edge_all)
        s5 صدا      ← فایل‌های فصل و تکه‌ها (merge_audio_files)
      --fake: به‌جای Edge سکوت می‌سازد (فقط برای آزمایش بدون اینترنت).
      اجرا از پوشهٔ backend.

  audition WORDS.txt --out DIR [--fake]
      چند املای یک کلمه (هر خط «املا | جمله») را شماره‌دار با صدای فرید می‌سازد تا
      با گوش بهترین انتخاب شود؛ متن مستقیم به موتور می‌رود (بدون حذف کسره).

  check --ref REF_PAGED --trace DIR [--uncertain FILE] [--report OUT.txt] [--checklist OUT.txt]
      REF_PAGED: متن درست با نشانگر [[page N]] (ویرایش انسانی/مرجع).
      برای هر صفحه و هر مرحله می‌گوید کدام کلمه، عدد یا عنوان حذف/خراب شد
      و «اولین مرحله»ای که خرابی در آن رخ داد. صدا با ffmpeg اندازه‌گیری می‌شود
      (مدت واقعی هر تکه و سکوت‌های بلند). فهرست شنیداری هر صفحه را هم می‌سازد.

فقط کتابخانهٔ استاندارد + ffmpeg. خروجی‌ها .txt هستند.
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

STAGES = [
    ("s1", "استخراج"),
    ("s2", "پردازش متن"),
    ("s3", "فصل‌بندی"),
    ("s4", "متن ارسالی به فرید"),
]
FAKE_CPS = 12.0  # حرف در ثانیه برای صدای ساختگی


# ───────────────────────── capture ─────────────────────────

def _silent_mp3(path, seconds):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{max(0.2, seconds):.2f}", "-q:a", "9", "-f", "mp3", str(path)],
        check=True,
    )


def cmd_capture(args, extra):
    backend = Path(args.backend).resolve()
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    import fva  # noqa: E402  (ماژول واقعی پروژه)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    T = {"input": str(Path(args.input).resolve()), "fake": bool(args.fake), "extra_args": extra,
         "s1": [], "s2": [], "s3": [], "s4": [], "merges": []}

    o_extract, o_process, o_split = fva.extract_items, fva.process_text, fva.split_chapters
    o_edge_all, o_merge = fva._edge_all, fva.merge_audio_files

    def extract_items(path):
        items = o_extract(path)
        T["s1"] = [i.get("text", "") for i in items if i.get("text")]
        return items

    def process_text(*a, **k):
        items = o_process(*a, **k)
        T["s2"] = [{"type": str(i.get("type", "")), "text": i.get("text", "")} for i in items]
        return items

    def split_chapters(items):
        ch = o_split(items)
        T["s3"] = [[t, list(p)] for t, p in ch]
        return ch

    async def _edge_all(jobs, voice, rate, retries, concurrency, progress):
        T["s4"] = [{"path": str(p), "text": t} for t, p in jobs]
        T["voice"], T["rate"] = voice, rate
        if not args.fake:
            return await o_edge_all(jobs, voice, rate, retries, concurrency, progress)
        for t, p in jobs:
            if fva._is_done(p):
                progress(skipped=True)
                continue
            _silent_mp3(p, len(_plain(t)) / FAKE_CPS)
            progress(skipped=False)

    def merge_audio_files(inputs, output):
        T["merges"].append({"out": str(output), "inputs": [str(p) for p in inputs]})
        return o_merge(inputs, output)

    fva.extract_items, fva.process_text, fva.split_chapters = extract_items, process_text, split_chapters
    fva._edge_all, fva.merge_audio_files = _edge_all, merge_audio_files

    sys.argv = ["fva.py", args.input, "--output-dir", str(out)] + extra
    try:
        fva.main()
    finally:
        (out / "trace.json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"trace: {out / 'trace.json'}  (تکه‌ها: {len(T['s4'])}، فایل‌ها: {len(T['merges'])})")


# ───────────────────────── text normalisation ─────────────────────────

_HARAKAT = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_TAG = re.compile(r"<break[^>]*>|<break_(?:short|medium|long)>|</?speak[^>]*>|<[^>]+>")
BREAK = "\u23F8"
_LAT2FA = str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹")
_TOKEN = re.compile(
    r"(?P<num>[۰-۹]+(?:[/٫.][۰-۹]+)*(?:\s+ممیز\s+[۰-۹]+)?)"
    r"|(?P<brk>" + BREAK + r")"
    r"|(?P<word>[^\W\d_]+)"
)


def _plain(ssml):
    return html.unescape(_TAG.sub(" ", ssml))


def norm(text):
    text = html.unescape(text)
    text = re.sub(r"<break[^>]*>|<break_(?:short|medium|long)>", f" {BREAK} ", text)
    text = _TAG.sub(" ", text)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ى", "ی")
    text = _HARAKAT.sub("", text)
    return text.translate(_LAT2FA)


def num_value(tok):
    """متن عدد ← مقدار متعارف (برای مقایسهٔ ۲/۵ با «۲ ممیز ۵»)."""
    t = tok.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    m = re.fullmatch(r"(\d+)\s+ممیز\s+(\d+)", t)
    if m:
        return f"{int(m.group(1))}.{m.group(2)}"
    if re.fullmatch(r"\d{1,3}(?:/\d{3})+", t):
        return str(int(t.replace("/", "")))
    if re.fullmatch(r"\d+[/٫.]\d+", t):
        a, b = re.split(r"[/٫.]", t)
        return f"{int(a)}.{b}"
    if re.fullmatch(r"\d+", t):
        return str(int(t))
    return t  # تاریخ و مانند آن


def tokenize(text):
    """[(token, kind)] ؛ kind: word | num | brk. نیم‌فاصله مرز توکن است."""
    out = []
    for m in _TOKEN.finditer(norm(text)):
        if m.group("num"):
            out.append(("#" + num_value(m.group("num")), "num"))
        elif m.group("brk"):
            out.append((BREAK, "brk"))
        else:
            out.append((m.group("word"), "word"))
    return out


# ───────────────────────── persian number words (for the checklist) ─────────────────────────

_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUND = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
_SCALE = ["", "هزار", "میلیون", "میلیارد"]


def _under_1000(n):
    parts = []
    if n >= 100:
        parts.append(_HUND[n // 100])
        n %= 100
    if 10 <= n < 20:
        parts.append(_TEENS[n - 10])
    else:
        if n >= 20:
            parts.append(_TENS[n // 10])
        if n % 10:
            parts.append(_ONES[n % 10])
    return " و ".join(parts)


def fa_words(value):
    if "." in value:
        a, b = value.split(".", 1)
        return f"{fa_words(a)} ممیز {fa_words(str(int(b))) if b.strip('0') else 'صفر'}"
    if not value.isdigit():
        return value
    n = int(value)
    if n == 0:
        return "صفر"
    groups, i = [], 0
    while n and i < len(_SCALE):
        n, g = divmod(n, 1000)
        if g:
            w = _under_1000(g)
            if i == 1 and g == 1:
                w = ""
            groups.append((w + " " + _SCALE[i]).strip())
        i += 1
    return " و ".join(reversed(groups))


# ───────────────────────── reference ─────────────────────────

_PAGE = re.compile(r"^\s*\[\[page (\d+)\]\]\s*$")
_END_PUNCT = tuple(".!?؟:…؛،»\"'")


def load_ref(path):
    """توکن‌های مرجع با شمارهٔ صفحه + عنوان‌ها (سطر کوتاه بدون نقطهٔ پایانی)."""
    tokens, pages, headings = [], [], []
    page = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = _PAGE.match(line)
        if m:
            page = int(m.group(1))
            continue
        s = line.strip()
        if not s:
            continue
        toks = [t for t in tokenize(s) if t[1] != "brk"]
        start = len(tokens)
        tokens += [t[0] for t in toks]
        pages += [page] * len(toks)
        if toks and not s.endswith(_END_PUNCT) and len(toks) <= 10:
            headings.append({"page": page, "text": s, "span": (start, len(tokens))})
    return tokens, pages, headings


def load_uncertain(path):
    items = []
    if not path:
        return items
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 3 and cols[0].strip().isdigit():
            items.append({"page": int(cols[0]), "text": cols[1].strip(), "status": cols[2].strip(),
                          "note": cols[3].strip() if len(cols) > 3 else ""})
    return items


# ───────────────────────── lexicon (expected respellings) ─────────────────────────

def load_lexicon(backend):
    try:
        sys.path.insert(0, str(Path(backend).resolve()))
        from core import lexicon as L  # noqa: E402
        lex = {}
        for d in (getattr(L, "TTS_LEXICON", {}), getattr(L, "HISTORICAL_NAMES", {})):
            for k, v in d.items():
                lex[norm(k).strip()] = norm(v).strip()
        return lex
    except Exception:
        return {}


_HAMZA = str.maketrans({"أ": "ا", "إ": "ا", "ؤ": "و", "ئ": "ی", "ء": None, "آ": "ا"})


def categorize(ref_span, hyp_span, lex):
    r, h = "".join(ref_span), "".join(hyp_span)
    if any(t.startswith("#") for t in ref_span + hyp_span):
        return "number"
    if r == h:
        # «وزیر» ← «و زیر»: «و»ی جدا «او» خوانده می‌شود ← تلفظ عوض شده، فقط فاصله نیست
        if ref_span.count("و") != hyp_span.count("و"):
            return "changed"
        return "spacing"
    if r.translate(_HAMZA) == h.translate(_HAMZA):
        return "hamza"
    if lex:
        s = " " + " ".join(ref_span) + " "
        for k in sorted(lex, key=len, reverse=True):
            s = re.sub(r"(?<= )" + re.escape(k) + r"(?= )", lex[k], s)
        if s.replace(" ", "") == h:
            return "lexicon"
    return "changed"


ERROR = {"missing", "changed", "number"}
LISTEN = {"hamza", "lexicon"}
CAT_FA = {"missing": "حذف شد", "changed": "خراب شد", "number": "عدد عوض شد",
          "hamza": "همزه عوض شد (بشنو)", "lexicon": "تلفظ واژه‌نامه (بشنو)", "spacing": "فاصله"}


# ───────────────────────── stage streams ─────────────────────────

def split_merges(T):
    """(ادغام‌های فصل، ادغام‌های «کامل») — کامل = ورودی‌هایش خروجی ادغام دیگری است."""
    outs = {m["out"] for m in T.get("merges", [])}
    chap = [m for m in T.get("merges", []) if not any(p in outs for p in m["inputs"])]
    full = [m for m in T.get("merges", []) if any(p in outs for p in m["inputs"])]
    return chap, full


def stage_streams(T):
    """هر مرحله ← (tokens, break_after, origin) ؛ origin برای s4 = (merge_idx, chunk_path, frac)."""
    streams = {}

    def build(pieces, sep_is_break):
        toks, brk = [], []
        for piece in pieces:
            for t, kind in tokenize(piece):
                if kind == "brk":
                    if brk:
                        brk[-1] = True
                    continue
                toks.append(t)
                brk.append(False)
            if sep_is_break and brk:
                brk[-1] = True
        return toks, brk

    streams["s1"] = build(T.get("s1", []), False) + (None,)
    streams["s2"] = build([i["text"] for i in T.get("s2", [])], False) + (None,)
    streams["s3"] = build([p for _, paras in T.get("s3", []) for p in paras], True) + (None,)

    text_of = {j["path"]: j["text"] for j in T.get("s4", [])}
    order = [(mi, p) for mi, m in enumerate(split_merges(T)[0]) for p in m["inputs"]]
    if not order:  # ادغام ضبط نشد: ترتیب کارها
        order = [(None, j["path"]) for j in T.get("s4", [])]
    toks, brk, origin = [], [], []
    for mi, p in order:
        pieces = [(t, k) for t, k in tokenize(text_of.get(p, ""))]
        words = [x for x in pieces if x[1] != "brk"]
        n, seen = max(1, len(words)), 0
        for t, kind in pieces:
            if kind == "brk":
                if brk:
                    brk[-1] = True
                continue
            toks.append(t)
            brk.append(False)
            origin.append((mi, p, seen / n))
            seen += 1
        if brk:
            brk[-1] = True  # مرز تکه = مکث
    streams["s4"] = (toks, brk, origin)
    return streams


def align(ref, hyp, lex):
    """برای هر توکن مرجع: (وضعیت، اندیس در hyp یا None، متن hyp) + فهرست ویرایش‌ها."""
    status = [("ok", None, None)] * len(ref)
    edits = []
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                status[i1 + k] = ("ok", j1 + k, hyp[j1 + k])
        elif op == "delete":
            for k in range(i1, i2):
                status[k] = ("missing", None, None)
            edits.append(("missing", i1, i2, j1, j2))
        elif op == "replace":
            cat = categorize(ref[i1:i2], hyp[j1:j2], lex)
            for k in range(i1, i2):
                status[k] = (cat, j1, " ".join(hyp[j1:j2]))
            edits.append((cat, i1, i2, j1, j2))
        elif op == "insert":
            edits.append(("inserted", i1, i2, j1, j2))
    return status, edits


# ───────────────────────── audio ─────────────────────────

_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_SIL = re.compile(r"silence_duration:\s*([\d.]+)")


def measure(path, min_silence):
    """(مدت ثانیه، [سکوت‌های بلند]) با رمزگشایی کامل ffmpeg؛ None اگر فایل نباشد."""
    if not Path(path).exists() or not shutil.which("ffmpeg"):
        return None, []
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"silencedetect=noise=-40dB:d={min_silence}", "-f", "null", "-", "-stats"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    times = _TIME.findall(r.stderr)
    dur = None
    if times:
        h, m, s = times[-1]
        dur = int(h) * 3600 + int(m) * 60 + float(s)
    return dur, [float(x) for x in _SIL.findall(r.stderr)]


def fmt_t(sec):
    if sec is None:
        return "؟"
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


# ───────────────────────── check ─────────────────────────

def cmd_check(args):
    trace_dir = Path(args.trace)
    T = json.loads((trace_dir / "trace.json").read_text(encoding="utf-8"))
    ref, ref_pages, headings = load_ref(args.ref)
    uncertain = load_uncertain(args.uncertain)
    lex = load_lexicon(args.backend)
    streams = stage_streams(T)
    page_list = sorted({p for p in ref_pages if p is not None})

    st = {}
    for key, _ in STAGES:
        toks, brk, origin = streams[key]
        status, edits = align(ref, toks, lex) if toks else ([("missing", None, None)] * len(ref), [])
        st[key] = {"status": status, "edits": edits, "toks": toks, "brk": brk, "origin": origin}

    # اولین مرحلهٔ خرابی برای هر توکن مرجع
    first_bad = [None] * len(ref)
    for i in range(len(ref)):
        for key, _ in STAGES:
            if st[key]["status"][i][0] in ERROR:
                first_bad[i] = key
                break

    # ── صدا ──
    merges, full_merges = split_merges(T)
    chunk_info, file_info = {}, []
    for m in merges:
        offs = 0.0
        for p in m["inputs"]:
            if p not in chunk_info:
                d, sil = measure(p, args.min_silence)
                text = next((j["text"] for j in T.get("s4", []) if j["path"] == p), "")
                chunk_info[p] = {"dur": d, "sil": sil, "chars": len(_plain(text).strip())}
            chunk_info[p].setdefault("start", {})[m["out"]] = offs
            offs += chunk_info[p]["dur"] or 0.0
        d, _ = measure(m["out"], 99)
        file_info.append({"out": m["out"], "dur": d, "sum": offs, "n": len(m["inputs"])})
    full_start = {}  # فایل فصل ← زمان شروعش در فایل کامل
    for m in full_merges:
        offs = 0.0
        for p in m["inputs"]:
            full_start[p] = (Path(m["out"]).name, offs)
            offs += next((f["dur"] or 0.0 for f in file_info if f["out"] == p), 0.0)
        d, _ = measure(m["out"], 99)
        file_info.append({"out": m["out"], "dur": d, "sum": offs, "n": len(m["inputs"])})
    cps = [c["chars"] / c["dur"] for c in chunk_info.values() if c["dur"]]
    med = statistics.median(cps) if cps else None

    def where(i):
        """توکن مرجع i در کدام فایل و چه زمانی شنیده می‌شود."""
        s = st["s4"]["status"][i]
        if s[1] is None or not st["s4"]["origin"]:
            return None
        mi, p, frac = st["s4"]["origin"][min(s[1], len(st["s4"]["origin"]) - 1)]
        if mi is None:
            return None
        out = merges[mi]["out"]
        c = chunk_info.get(p, {})
        t = tf = None
        if c.get("dur") is not None:
            t = c["start"].get(out, 0.0) + frac * c["dur"]
            if out in full_start:
                tf = (full_start[out][0], full_start[out][1] + t)
        return Path(out).name, t, tf

    def loc_fa(loc):
        if not loc:
            return ""
        s = f"فایل {loc[0]} از حدود {fmt_t(loc[1])}"
        if loc[2]:
            s += f" (در {loc[2][0]} از حدود {fmt_t(loc[2][1])})"
        return s

    # ── گزارش ──
    R = []
    w = R.append
    w("گزارش ردگیری صفحه‌به‌صفحه: متن استخراج‌شده ← صدای نهایی (audio-trace)")
    w(f"ورودی: {T.get('input')}")
    w(f"مرجع: {args.ref}")
    w(f"صدا: {'ساختگی (--fake، فقط آزمایش مسیر؛ صدای واقعی نیست)' if T.get('fake') else 'واقعی (Edge)'}"
      f"   صدا/سرعت: {T.get('voice')} {T.get('rate')}")
    w("")
    w("خلاصه (✗ = حذف/خراب/عدد عوض‌شده ؛ ⚠ = تلفظ را گوش کن):")
    w(f"{'صفحه':>5} {'کلمه':>5} | " + " | ".join(f"{k}:{n}" for k, n in STAGES) + " | عدد سالم | عنوان سالم")
    page_rows = {}
    for pg in page_list:
        idx = [i for i, p in enumerate(ref_pages) if p == pg]
        cols = []
        for key, _ in STAGES:
            s = st[key]["status"]
            e = sum(1 for i in idx if s[i][0] in ERROR)
            ls = sum(1 for i in idx if s[i][0] in LISTEN)
            cols.append(f"✗{e} ⚠{ls}")
        nums = [i for i in idx if ref[i].startswith("#")]
        n_ok = sum(1 for i in nums if st["s4"]["status"][i][0] == "ok")
        hs = [h for h in headings if h["page"] == pg]
        h_ok = sum(1 for h in hs if _heading_ok(h, st["s4"]))
        page_rows[pg] = (idx, nums, hs)
        w(f"{pg:>5} {len(idx):>5} | " + " | ".join(cols) + f" | {n_ok}/{len(nums)} | {h_ok}/{len(hs)}")
    w("")

    for pg in page_list:
        idx, nums, hs = page_rows[pg]
        w("=" * 70)
        loc = next((where(i) for i in idx if where(i)), None)
        w(f"صفحهٔ {pg}" + (f"   ← {loc_fa(loc)}" if loc else ""))
        w("عنوان‌ها:")
        if not hs:
            w("  (ندارد)")
        for h in hs:
            ok = _heading_ok(h, st["s4"])
            lost = [first_bad[i] for i in range(*h["span"]) if first_bad[i]]
            pause = _heading_pause(h, st["s4"])
            w(f"  {'✓' if ok else '✗'} «{h['text']}»"
              + ("" if ok else f"  — اولین خرابی: {_stage_fa(lost[0]) if lost else 'نامشخص'}")
              + ("" if pause or not ok else "  — ⚠ بعدش مکث نیست"))
        w("عددها (مرجع ← هر مرحله):")
        if not nums:
            w("  (ندارد)")
        for i in nums:
            row = []
            for key, _ in STAGES:
                s = st[key]["status"][i]
                row.append("✓" if s[0] == "ok" else f"✗{(s[2] or 'حذف')}")
            unc = _unc_for(uncertain, pg, ref[i])
            w(f"  {ref[i][1:]:>12}  " + "  ".join(f"{k}:{c}" for (k, _), c in zip(STAGES, row))
              + (f"   [نامطمئن: {unc['status']}]" if unc else ""))
        w("خرابی‌ها (اولین مرحله):")
        any_err = False
        for key, name in STAGES:
            for cat, i1, i2, j1, j2 in st[key]["edits"]:
                if cat not in ERROR or not any(ref_pages[k] == pg for k in range(i1, i2)):
                    continue
                if not any(first_bad[k] == key for k in range(i1, i2)):
                    continue  # در مرحلهٔ قبل رخ داده و این‌جا فقط ادامه دارد
                any_err = True
                hyp = " ".join(st[key]["toks"][j1:j2]) or "∅"
                pre = (ref[i1 - 1].lstrip("#") + " ") if i1 > 0 and ref_pages[i1 - 1] == pg else ""
                post = (" " + ref[i2].lstrip("#")) if i2 < len(ref) and ref_pages[i2] == pg else ""
                w(f"  [{name}] {CAT_FA[cat]}: «{' '.join(ref[i1:i2])}» ← «{hyp}»   (…{pre}[ ]{post}…)")
        if not any_err:
            w("  هیچ.")
        listen = [(cat, i1, i2, j1, j2) for cat, i1, i2, j1, j2 in st["s4"]["edits"]
                  if cat in LISTEN and any(ref_pages[k] == pg for k in range(i1, i2))]
        if listen:
            w("تلفظ‌هایی که باید گوش داد (عمدی در خط لوله):")
            for cat, i1, i2, j1, j2 in listen:
                w(f"  ⚠ «{' '.join(ref[i1:i2])}» ← «{' '.join(st['s4']['toks'][j1:j2])}»  ({CAT_FA[cat]})")
        unc_pg = [u for u in uncertain if u["page"] == pg]
        if unc_pg:
            w("موارد نامطمئن مرجع (با تصویر صفحه تطبیق داده نشده):")
            for u in unc_pg:
                w(f"  ؟ «{u['text']}» — {u['status']}" + (f" — {u['note']}" if u["note"] else ""))
    w("=" * 70)
    w("صدا — تکه‌ها (مدت واقعی با ffmpeg؛ حرف‌در‌ثانیه نسبت به میانه):")
    if not chunk_info:
        w("  ادغامی ضبط نشد.")
    for n, (p, c) in enumerate(chunk_info.items(), 1):
        flag = []
        if c["dur"] is None:
            flag.append("✗ فایل/مدت نیست")
        elif med and c["chars"]:
            r = (c["chars"] / c["dur"]) / med
            if r > 1.6:
                flag.append("✗ خیلی کوتاه‌تر از متن (احتمال جاافتادن)")
            elif r < 0.6:
                flag.append("✗ خیلی بلندتر از متن (سکوت/تکرار؟)")
        long_sil = [s for s in c["sil"] if s >= args.min_silence]
        if long_sil and not T.get("fake"):
            flag.append(f"⚠ سکوت بلند {', '.join(f'{s:.1f}s' for s in long_sil)}")
        w(f"  {n:>3}. {Path(p).name}  حرف {c['chars']:>4}  مدت {fmt_t(c['dur'])}"
          + (f"  ح/ث {c['chars'] / c['dur']:.1f}" if c["dur"] else "") + ("  " + " ".join(flag) if flag else ""))
    w("صدا — فایل‌های نهایی:")
    for f in file_info:
        ok = f["dur"] is not None and abs(f["dur"] - f["sum"]) <= max(1.0, 0.03 * f["sum"])
        w(f"  {'✓' if ok else '✗'} {Path(f['out']).name}  مدت {fmt_t(f['dur'])}  (جمع تکه‌ها {fmt_t(f['sum'])}، {f['n']} تکه)")
    w("")
    w("یادآوری: این ابزار «متن ارسالی» و «مدت/سکوت صدا» را می‌سنجد؛ این‌که فرید هر کلمه را درست ادا کرد")
    w("را فقط گوش انسان تأیید می‌کند ← فهرست شنیداری.")
    report = "\n".join(R) + "\n"

    # ── فهرست شنیداری ──
    C = []
    c = C.append
    c("فهرست شنیداری — هنگام گوش دادن تیک بزن (✓ درست / ✗ غلط + توضیح)")
    c(f"صدا: {'ساختگی — این فهرست را با صدای واقعی گوش بده' if T.get('fake') else 'واقعی'}")
    for pg in page_list:
        idx, nums, hs = page_rows[pg]
        loc = next((where(i) for i in idx if where(i)), None)
        c("")
        c(f"■ صفحهٔ {pg}" + (f" — {loc_fa(loc)}" if loc else ""))
        first = " ".join(ref[i].lstrip("#") for i in idx[:6])
        c(f"  شروع صفحه با: «{first} …»")
        for h in hs:
            c(f"  [ ] عنوان خوانده شد و بعدش مکث بود: «{h['text']}»")
        for i in nums:
            unc = _unc_for(uncertain, pg, ref[i])
            c(f"  [ ] عدد {ref[i][1:]} ← باید بشنوی: «{fa_words(ref[i][1:])}»"
              + ("   (عدد خودِ کتاب هنوز تأیید نشده)" if unc else ""))
        for cat, i1, i2, j1, j2 in st["s4"]["edits"]:
            if cat in LISTEN and any(ref_pages[k] == pg for k in range(i1, i2)):
                c(f"  [ ] تلفظ «{' '.join(ref[i1:i2])}» درست بود؟")
        c("  [ ] جمله یا کلمه‌ای جا نیفتاد / تکرار نشد؟")
    checklist = "\n".join(C) + "\n"

    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    if args.checklist:
        Path(args.checklist).write_text(checklist, encoding="utf-8")
    print(report if not args.quiet else report.split("\n\n")[1])
    errors = sum(1 for i in range(len(ref)) if st["s4"]["status"][i][0] in ERROR)
    return 1 if (args.strict and errors) else 0


# ───────────────────────── audition (شنیدن چند املای یک کلمه) ─────────────────────────

def cmd_audition(args):
    """هر خط فایل: «املا | جملهٔ نمونه». هر گزینه با شماره خوانده می‌شود؛ متن مستقیم به
    موتور می‌رود (بدون خط لوله، چون خط لوله کسره را حذف می‌کند) تا دقیقاً همان املا شنیده شود."""
    backend = Path(args.backend).resolve()
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    import asyncio
    import fva  # noqa: E402
    voice = args.voice or fva.VOICE_EDGE_MALE
    rate = args.rate or fva.DEFAULT_RATE
    opts = []
    for line in Path(args.words).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        variant, _, sentence = (x.strip() for x in line.partition("|"))
        opts.append((variant, sentence))
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    files, index = [], ["شماره\tاملا\tجمله"]
    for n, (variant, sentence) in enumerate(opts, 1):
        ssml = (f'<speak>گزینهٔ {fa_words(str(n))} <break time="500ms"/> {html.escape(variant)} '
                f'<break time="700ms"/> {html.escape(sentence)} <break time="1200ms"/></speak>')
        f = out / f"opt_{n:02d}.mp3"
        if args.fake:
            _silent_mp3(f, (len(variant) + len(sentence)) / FAKE_CPS + 3)
        else:
            from engines.edge_engine import generate_voice
            asyncio.run(generate_voice(ssml, str(f), voice=voice, rate=rate, is_ssml=True))
        files.append(f)
        index.append(f"{n}\t{variant}\t{sentence}")
        print(f"  {n:>2}. {variant}")
    allf = out / "audition_all.mp3"
    fva.merge_audio_files(files, allf)
    (out / "audition_index.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    d, _ = measure(allf, 99)
    print(f"فایل شنیداری: {allf}  مدت {fmt_t(d)}  ({len(files)} گزینه، صدا: {voice} {rate}"
          f"{'، ساختگی' if args.fake else ''})")
    print(f"فهرست گزینه‌ها: {out / 'audition_index.txt'}")
    return 0


def _stage_fa(key):
    return dict(STAGES).get(key, key)


def _heading_ok(h, s4):
    return all(s4["status"][i][0] in ("ok", "spacing", "lexicon", "hamza") for i in range(*h["span"]))


def _heading_pause(h, s4):
    last = s4["status"][h["span"][1] - 1]
    if last[1] is None:
        return False
    j = last[1] + (len((last[2] or "").split()) - 1 if last[0] != "ok" else 0)
    return bool(s4["brk"][min(j, len(s4["brk"]) - 1)])


def _unc_for(uncertain, page, tok):
    for u in uncertain:
        if u["page"] != page:
            continue
        ut = [t for t, k in tokenize(u["text"]) if k != "brk"]
        if tok in ut:
            return u
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        k = argv.index("--")
        argv, extra = argv[:k], argv[k + 1:]
    ap = argparse.ArgumentParser(prog="audio_trace", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=".", help="پوشهٔ backend پروژه (پیش‌فرض: پوشهٔ جاری)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("capture")
    a.add_argument("input")
    a.add_argument("--out", required=True)
    a.add_argument("--fake", action="store_true")
    b = sub.add_parser("check")
    b.add_argument("--ref", required=True)
    b.add_argument("--trace", required=True)
    b.add_argument("--uncertain")
    b.add_argument("--report")
    b.add_argument("--checklist")
    b.add_argument("--min-silence", type=float, default=1.5)
    b.add_argument("--strict", action="store_true", help="کد خروج ۱ اگر خرابی در متن ارسالی باشد")
    b.add_argument("--quiet", action="store_true")
    c = sub.add_parser("audition", help="چند املای یک کلمه را شماره‌دار با صدای فرید بساز")
    c.add_argument("words", help="فایل: هر خط «املا | جملهٔ نمونه»")
    c.add_argument("--out", required=True)
    c.add_argument("--voice")
    c.add_argument("--rate")
    c.add_argument("--fake", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "audition":
        return cmd_audition(args)
    if args.cmd == "capture":
        return cmd_capture(args, extra) or 0
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
