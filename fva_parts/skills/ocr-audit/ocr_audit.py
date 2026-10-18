#!/usr/bin/env python3
"""ocr_audit — read-only audit of the "scan -> raw text" stage (and any text stage).

Commands (all read-only; reports are .txt under backend/work/ocr_audit/):
  map      Static map of OCR-related code: imports, external tools, entrypoints,
           hard-coded paths that no longer exist, reachability from production.
  quality  Page-aligned comparison hyp vs ref: WER/CER + error taxonomy
           (glued, split, ZWNJ, char confusions, missing/extra text) + rule candidates
           with a collision check (would the rule damage correct text?).
  stage    Attribution raw -> cleaned -> ref: what the cleaner fixed, what it BROKE.
  rules    Measure every rule of an existing table (e.g. OCR_SPACING_RULES):
           pages helped vs pages hurt, on real data, before anyone trusts it.

The reference is "the best available text", not ground truth. Disagreements are
candidates for human review, never automatic corrections. Stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import collections
import difflib
import importlib
import os
import re
import sys
import unicodedata
from pathlib import Path

PAGE_RE = re.compile(r"\[\[page (\d+)\]\]")
TOKEN_RE = re.compile(r"[^\s.,،؛;:!?؟«»\"'()\[\]{}<>…\-–—/\\*|]+")
MARKS_RE = re.compile(r"[\u064B-\u0652\u0670\u0640]")  # harakat + tatweel
ZWNJ = "\u200c"
LATIN_RE = re.compile(r"[A-Za-z]")
ARABIC_FORMS_RE = re.compile(r"[يكة]")
OCR_HINTS = ("tesseract", "pytesseract", "pdf2image", "pdfplumber", "pdftotext",
             "pdftoppm", "fitz", "easyocr", "ocr")
HINT_RE = re.compile(r"(?<![a-z])(" + "|".join(OCR_HINTS) + r")(?![a-z])")
TOOLS = ("tesseract", "pdftotext", "pdftoppm", "pdfimages", "ffmpeg", "ffprobe")
FILE_EXTS = {"txt", "png", "jpg", "pdf", "json", "py", "tsv", "csv", "log", "wav", "mp3",
             "docx", "sh", "onnx", "md", "epub", "tif", "tiff"}
MIME_RE = re.compile(r"^(application|text|image|audio|video)/")
PATH_LIT_RE = re.compile(r"^[\w./~-]*/[\w./-]*$")


# ----------------------------------------------------------------- loading
def load_pages(path: str) -> dict[int, str]:
    """{page: text}. Files without [[page N]] markers become page 0."""
    text = Path(path).read_text(encoding="utf-8")
    parts = PAGE_RE.split(text)
    if len(parts) == 1:
        return {0: text}
    return {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


DIGITS = str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹" * 2)


def norm(s: str) -> str:
    """NFC, no diacritics/tatweel, all digits folded to Persian (a convention, not an error)."""
    return MARKS_RE.sub("", unicodedata.normalize("NFC", s)).translate(DIGITS)


def tokens(s: str) -> list[str]:
    return TOKEN_RE.findall(norm(s).replace("\f", " "))


def bare(tok: str) -> str:
    return tok.replace(ZWNJ, "")


def load_func(spec: str, root: str):
    mod, _, attr = spec.partition(":")
    sys.path.insert(0, root)
    obj = importlib.import_module(mod)
    for a in attr.split("."):
        obj = getattr(obj, a)
    return obj


# ----------------------------------------------------------------- alignment
class Stats:
    def __init__(self):
        self.ref_words = 0
        self.word_err = 0
        self.ref_chars = 0
        self.char_err = 0
        self.cat = collections.Counter()
        self.ex = collections.defaultdict(list)
        self.subs = collections.Counter()      # (hyp_tok, ref_tok)
        self.joins = collections.Counter()     # ("درسال", "در سال")
        self.splits = collections.Counter()    # ("در آمد", "درآمد")
        self.conf = collections.Counter()      # (hyp_chars, ref_chars)
        self.per_page = {}

    def add_ex(self, cat, page, h, r, limit=8):
        if len(self.ex[cat]) < limit:
            self.ex[cat].append((page, h, r))


def char_edits(a: str, b: str):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    n, pairs = 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            n += max(i2 - i1, j2 - j1)
            pairs.append((a[i1:i2], b[j1:j2]))
    return n, pairs


def align(h: list[str], r: list[str]):
    return difflib.SequenceMatcher(None, h, r, autojunk=False).get_opcodes()


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, bare(a), bare(b), autojunk=False).ratio()


MOVES = ((1, 1), (1, 2), (2, 1), (1, 3), (3, 1), (1, 0), (0, 1))


def split_block(hs: list[str], rs: list[str]) -> list[tuple[list[str], list[str]]]:
    """Mini-DP inside one mismatch block: cut it into 1:1, 1:n (glued), n:1 (split),
    extra and missing pieces, so neighbouring errors are classified separately."""
    n, m = len(hs), len(rs)
    if n * m > 1600:
        return [(hs, rs)]
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if cost[i][j] == inf:
                continue
            for di, dj in MOVES:
                a, b = i + di, j + dj
                if a > n or b > m:
                    continue
                if di == 0 or dj == 0:
                    c = 1.0
                else:
                    hj, rj = "".join(hs[i:a]), "".join(rs[j:b])
                    c = 0.0 if bare(hj) == bare(rj) else (1.0 - _sim(hj, rj)) * 1.6 + 0.05 * (di + dj)
                if cost[i][j] + c < cost[a][b]:
                    cost[a][b] = cost[i][j] + c
                    back[a][b] = (i, j)
    pieces, i, j = [], n, m
    while (i, j) != (0, 0):
        pi, pj = back[i][j]
        pieces.append((hs[pi:i], rs[pj:j]))
        i, j = pi, pj
    return pieces[::-1]


def classify_piece(st: Stats, page: int, hs: list[str], rs: list[str]) -> None:
    hj, rj = " ".join(hs), " ".join(rs)
    if not rs:
        st.cat["extra_text"] += 1
        st.char_err += sum(len(t) for t in hs)
        st.add_ex("extra_text", page, hj[:60], "")
        return
    if not hs:
        st.cat["missing_text"] += 1
        st.char_err += sum(len(t) for t in rs)
        st.add_ex("missing_text", page, "", rj[:60])
        return
    if bare("".join(hs)) == bare("".join(rs)):
        if len(hs) < len(rs):
            c = "glued"
            st.joins[(hj, rj)] += 1
        elif len(hs) > len(rs):
            c = "split"
            st.splits[(hj, rj)] += 1
        else:
            c = "zwnj"
        st.cat[c] += 1
        st.add_ex(c, page, hj, rj)
        return
    n, pairs = char_edits(hj, rj)
    st.char_err += n
    for x, y in pairs:
        st.conf[(x, y)] += 1
    if len(hs) == 1 and len(rs) == 1:
        st.subs[(hs[0], rs[0])] += 1
        if LATIN_RE.search(hs[0]):
            c = "latin_in_word"
        elif ARABIC_FORMS_RE.search(hs[0]) and norm(rs[0]) == hs[0].replace(
                "ي", "ی").replace("ك", "ک").replace("ة", "ه"):
            c = "arabic_letter_form"
        elif len(hs[0]) == len(rs[0]):
            c = "char_substitution"
        else:
            c = "char_insert_delete"
    elif len(hs) < len(rs):
        c = "glued_and_chars"
    elif len(hs) > len(rs):
        c = "split_and_chars"
    else:
        c = "complex"
    st.cat[c] += 1
    st.add_ex(c, page, hj[:50], rj[:50])


def score_page(st: Stats, page: int, hyp: str, ref: str) -> int:
    h, r = tokens(hyp), tokens(ref)
    st.ref_words += len(r)
    st.ref_chars += sum(len(t) for t in r)
    page_err = 0
    for op, i1, i2, j1, j2 in align(h, r):
        if op == "equal":
            continue
        page_err += max(i2 - i1, j2 - j1)
        for hs, rs in split_block(h[i1:i2], r[j1:j2]):
            classify_piece(st, page, hs, rs)
    st.word_err += page_err
    st.per_page[page] = (page_err, len(r))
    return page_err


def page_errors(hyp: str, ref: str) -> int:
    h, r = tokens(hyp), tokens(ref)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in align(h, r) if op != "equal")


def matched_ref_positions(hyp: str, ref: str) -> set[int]:
    h, r = tokens(hyp), tokens(ref)
    out = set()
    for op, i1, i2, j1, j2 in align(h, r):
        if op == "equal":
            out.update(range(j1, j2))
    return out


# ----------------------------------------------------------------- helpers
def common_pages(a: dict, b: dict) -> list[int]:
    return sorted(set(a) & set(b))


def ref_vocab(ref_pages: dict) -> collections.Counter:
    c = collections.Counter()
    for t in ref_pages.values():
        c.update(tokens(t))
    return c


def write_report(out: Path, lines: list[str], inputs: list[str]) -> None:
    for i in inputs:
        if i and Path(i).resolve() == out.resolve():
            sys.exit(f"refusing to overwrite an input file: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:60]))
    if len(lines) > 60:
        print(f"... ({len(lines) - 60} more lines)")
    print(f"\nreport: {out}")


def pct(a, b):
    return f"{100.0 * a / b:.2f}%" if b else "n/a"


# ----------------------------------------------------------------- quality
def cmd_quality(a) -> None:
    hyp, ref = load_pages(a.hyp), load_pages(a.ref)
    if a.apply:
        f = load_func(a.apply, a.root)
        hyp = {p: f(t) for p, t in hyp.items()}
    pages = common_pages(hyp, ref)
    st = Stats()
    for p in pages:
        score_page(st, p, hyp[p], ref[p])
    vocab = ref_vocab(ref)
    hyp_vocab = collections.Counter()
    for p in pages:
        hyp_vocab.update(tokens(hyp[p]))

    L = [f"ocr_audit quality   hyp={a.hyp}   ref={a.ref}" + (f"   apply={a.apply}" if a.apply else ""),
         "NOTE: ref = best available text, not ground truth.", "",
         f"pages compared: {len(pages)}  (hyp only: {len(set(hyp) - set(ref))}, ref only: {len(set(ref) - set(hyp))})",
         f"WER ~ {pct(st.word_err, st.ref_words)}   ({st.word_err} word edits / {st.ref_words} ref words)",
         f"CER ~ {pct(st.char_err, st.ref_chars)}   (character edits inside mismatches)", "",
         "== error categories (occurrences)"]
    for c, n in st.cat.most_common():
        L.append(f"  {c:<22}{n:>7}")
    for c in st.cat:
        L.append(f"\n-- examples: {c}  (page | hyp -> ref)")
        for p, h, r in st.ex[c]:
            L.append(f"  p{p:<4} {h!r} -> {r!r}")
    L.append("\n== top character confusions (hyp -> ref)")
    for (x, y), n in st.conf.most_common(a.top):
        L.append(f"  {x!r:>8} -> {y!r:<8}{n:>6}")
    L.append("\n== worst pages (word edits / ref words)")
    worst = sorted(st.per_page.items(), key=lambda kv: kv[1][0] / max(1, kv[1][1]), reverse=True)
    for p, (e, n) in worst[:a.top]:
        L.append(f"  p{p:<5}{e:>5} / {n:<5} {pct(e, n)}")

    L.append("\n== rule candidates (seen >= %d times). collision = the hyp form also" % a.min_count)
    L.append("   appears as a correct word in ref, so a blind rule would damage text.")
    L.append(f"   {'kind':<7}{'n':>5}{'collide':>9}  hyp -> ref")
    cands = [("subst", k, n) for k, n in st.subs.items() if n >= a.min_count]
    cands += [("join", k, n) for k, n in st.joins.items() if n >= a.min_count]
    cands += [("split", k, n) for k, n in st.splits.items() if n >= a.min_count]
    cands.sort(key=lambda x: -x[2])
    for kind, (h, r), n in cands[:a.top * 3]:
        coll = vocab[h]
        if kind == "split":
            coll = sum(1 for p in pages if f" {h} " in f" {' '.join(tokens(ref[p]))} ")
        flag = "SAFE?" if coll == 0 else "RISKY"
        L.append(f"   {kind:<7}{n:>5}{coll:>9}  {h!r} -> {r!r}   {flag}")
    L.append("\n'SAFE?' still needs `rules` measurement before it is applied.")
    write_report(Path(a.out or Path(a.root) / "work/ocr_audit/quality.txt"), L, [a.hyp, a.ref])


# ----------------------------------------------------------------- stage
def cmd_stage(a) -> None:
    raw, ref = load_pages(a.raw), load_pages(a.ref)
    if a.cleaned:
        cleaned = load_pages(a.cleaned)
        label = a.cleaned
    else:
        f = load_func(a.apply, a.root)
        cleaned = {p: f(t) for p, t in raw.items()}
        label = a.apply
    pages = sorted(set(raw) & set(ref) & set(cleaned))
    s_raw, s_cln = Stats(), Stats()
    fixed = broken = 0
    broken_ex, fixed_ex = collections.Counter(), collections.Counter()
    for p in pages:
        score_page(s_raw, p, raw[p], ref[p])
        score_page(s_cln, p, cleaned[p], ref[p])
        mr, mc = matched_ref_positions(raw[p], ref[p]), matched_ref_positions(cleaned[p], ref[p])
        r = tokens(ref[p])
        lost, gained = mr - mc, mc - mr
        broken += len(lost)
        fixed += len(gained)
        if lost:
            ct = tokens(cleaned[p])
            sm = difflib.SequenceMatcher(None, ct, r, autojunk=False)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != "equal" and set(range(j1, j2)) & lost:
                    broken_ex[(" ".join(r[j1:j2])[:40], " ".join(ct[i1:i2])[:40])] += 1
        for j in list(gained)[:3]:
            fixed_ex[r[j]] += 1
    L = [f"ocr_audit stage   raw={a.raw}   cleaned={label}   ref={a.ref}",
         "NOTE: ref = best available text, not ground truth.", "",
         f"pages: {len(pages)}",
         f"WER raw     -> ref : {pct(s_raw.word_err, s_raw.ref_words)}",
         f"WER cleaned -> ref : {pct(s_cln.word_err, s_cln.ref_words)}",
         f"ref words fixed by cleaner : {fixed}",
         f"ref words BROKEN by cleaner: {broken}   (correct in raw, wrong after cleaning)", "",
         f"== category            {'raw':>8}{'cleaned':>9}{'delta':>8}"]
    for c in sorted(set(s_raw.cat) | set(s_cln.cat), key=lambda c: -s_raw.cat[c]):
        L.append(f"   {c:<22}{s_raw.cat[c]:>8}{s_cln.cat[c]:>9}{s_cln.cat[c] - s_raw.cat[c]:>+8}")
    L.append("\n== regressions introduced by the cleaner (ref -> cleaned), most frequent")
    for (r, c), n in broken_ex.most_common(a.top):
        L.append(f"   {n:>4}  {r!r} -> {c!r}")
    L.append("\n== sample of words the cleaner fixed")
    L.append("   " + "  ".join(f"{w}({n})" for w, n in fixed_ex.most_common(a.top)))
    write_report(Path(a.out or Path(a.root) / "work/ocr_audit/stage.txt"), L, [a.raw, a.ref, a.cleaned])


# ----------------------------------------------------------------- rules
def _apply_rule(text: str, src: str, dst: str, mode: str) -> str:
    if mode == "token":
        return re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, text)
    return text.replace(src, dst)


def cmd_rules(a) -> None:
    hyp, ref = load_pages(a.hyp), load_pages(a.ref)
    table = load_func(a.table, a.root)
    pairs = list(table.items()) if isinstance(table, dict) else list(table)
    pages = common_pages(hyp, ref)
    base = {}
    L = [f"ocr_audit rules   table={a.table}   mode={a.mode}   hyp={a.hyp}   ref={a.ref}",
         "Each rule is applied ALONE to hyp; delta = word edits after - before (negative = better).",
         "NOTE: ref = best available text, not ground truth.", "",
         "REF-KEEPS-SRC = the reference itself still contains the source form, so a",
         "                'hurt' may mean the REFERENCE is unclean. A human must judge.",
         "good~ = clearly helps; hurts on <= 1 of 10 pages (often noise in the reference).", "",
         f"   {'verdict':<14}{'hits':>6}{'helped':>8}{'hurt':>6}{'delta':>7}{'in_ref':>8}  rule"]
    ref_all = {p: norm(ref[p]) for p in pages}
    verdicts = collections.Counter()
    for src, dst in pairs:
        hits = helped = hurt = delta = 0
        for p in pages:
            if src not in hyp[p]:
                continue
            new = _apply_rule(hyp[p], src, dst, a.mode)
            if new == hyp[p]:
                continue
            hits += 1
            if p not in base:
                base[p] = page_errors(hyp[p], ref[p])
            d = page_errors(new, ref[p]) - base[p]
            delta += d
            helped += d < 0
            hurt += d > 0
        in_ref = sum(len(re.findall(rf"(?<!\w){re.escape(norm(src))}(?!\w)", t)) if a.mode == "token"
                     else t.count(norm(src)) for t in ref_all.values())
        v = ("unused" if hits == 0 else
             "good~" if delta < 0 and hurt * 10 <= helped else
             "REF-KEEPS-SRC" if hurt and in_ref else
             "HARMFUL" if hurt and delta >= 0 else
             "mixed" if hurt else "good" if helped else "neutral")
        verdicts[v] += 1
        L.append(f"   {v:<14}{hits:>6}{helped:>8}{hurt:>6}{delta:>+7}{in_ref:>8}  {src!r} -> {dst!r}")
    L.insert(7, "summary: " + ", ".join(f"{k}={n}" for k, n in verdicts.most_common()))
    write_report(Path(a.out or Path(a.root) / "work/ocr_audit/rules.txt"), L, [a.hyp, a.ref])


# ----------------------------------------------------------------- map
def _module_name(path: Path, root: Path) -> str | None:
    try:
        rel = path.relative_to(root).with_suffix("")
    except ValueError:
        return None
    return ".".join(rel.parts)


def cmd_map(a) -> None:
    root = Path(a.root).resolve()
    scan_roots = [root] + [Path(x).resolve() for x in a.extra]
    files = []
    for sr in scan_roots:
        for p in sorted(sr.rglob("*.py")):
            if any(s in p.parts for s in ("__pycache__", ".git", "archive", "_archive_extra", "node_modules")):
                continue
            files.append(p)
    info, graph = {}, collections.defaultdict(set)
    modnames = {_module_name(p, root): p for p in files if _module_name(p, root)}
    for p in files:
        src = p.read_text(encoding="utf-8", errors="replace")
        low = src.lower()
        d = {"ocr": sorted(set(HINT_RE.findall(low))), "imports": set(), "tools": set(),
             "main": "__main__" in src, "missing_paths": set(), "syntax": None}
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            d["syntax"] = f"line {e.lineno}"
            info[p] = d
            continue
        fstr_parts = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                d["imports"].update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                d["imports"].add(node.module)
                d["imports"].update(f"{node.module}.{n.name}" for n in node.names)
            elif isinstance(node, ast.JoinedStr):
                fstr_parts.update(id(v) for v in node.values)
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and id(node) not in fstr_parts):
                v = node.value
                last = v.rstrip("/").rsplit("/", 1)[-1]
                is_pathish = v.endswith("/") or last.rsplit(".", 1)[-1].lower() in FILE_EXTS
                is_pathish = is_pathish and not MIME_RE.match(v)
                if v in TOOLS:
                    d["tools"].add(v)
                if (is_pathish and PATH_LIT_RE.match(v) and len(v) > 3 and not v.startswith(("http", "/"))
                        and "." not in v.split("/")[0][:1] and "{" not in v):
                    cands = [root / v, p.parent / v, root.parent / v]
                    if not any(c.exists() for c in cands) and not v.startswith("~"):
                        d["missing_paths"].add(v)
        me = _module_name(p, root)
        for imp in d["imports"]:
            if imp in modnames and me:
                graph[me].add(imp)
        info[p] = d
    reach, via = set(), {}
    stack = [(e, e) for e in a.entry if e in modnames]
    while stack:
        m, chain = stack.pop()
        if m in reach:
            continue
        reach.add(m)
        via[m] = chain
        stack.extend((n, f"{chain} -> {n}") for n in graph.get(m, ()))
    ocr_files = [p for p in files if info[p]["ocr"] or info[p]["tools"] & {"tesseract", "pdftotext", "pdftoppm"}]
    L = [f"ocr_audit map   root={root}   entrypoints={a.entry}", "",
         f"python files scanned: {len(files)}   OCR-related: {len(ocr_files)}",
         f"modules reachable from entrypoints: {len(reach)}", "",
         "status: PROD = reachable from an entrypoint; SCRIPT = runnable on its own;",
         "        ORPHAN = neither; BROKEN = syntax error or hard-coded paths that do not exist", ""]
    rows = []
    for p in ocr_files:
        d = info[p]
        me = _module_name(p, root)
        is_test = "tests" in p.parts or p.name.startswith("test_")
        status = ("PROD" if me in reach else "TEST" if is_test
                  else "SCRIPT" if d["main"] else "ORPHAN")
        if d["syntax"] or d["missing_paths"]:
            status += "+BROKEN"
        rel = os.path.relpath(p, root)
        rows.append((status, rel, d))
    rows.sort(key=lambda r: (not r[0].startswith("PROD"), r[0], r[1]))
    for status, rel, d in rows:
        L.append(f"[{status}] {rel}")
        if status.startswith("PROD"):
            L.append(f"    via: {via[_module_name(root / rel, root)]}")
        L.append(f"    hints: {', '.join(d['ocr']) or '-'}   tools: {', '.join(sorted(d['tools'])) or '-'}")
        if d["syntax"]:
            L.append(f"    SYNTAX ERROR at {d['syntax']}")
        if d["missing_paths"]:
            L.append(f"    missing paths: {', '.join(sorted(d['missing_paths']))[:200]}")
    cnt = collections.Counter(r[0] for r in rows)
    L.insert(4, "summary: " + ", ".join(f"{k}={n}" for k, n in cnt.most_common()))
    write_report(Path(a.out or root / "work/ocr_audit/map.txt"), L, [])


# ----------------------------------------------------------------- cli
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="backend directory (default: .)")
    ap.add_argument("--out", help="report path (.txt)")
    ap.add_argument("--top", type=int, default=20)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map")
    m.add_argument("--entry", nargs="+", default=["main", "fva", "fva_agents", "pipeline", "core.pipeline"])
    m.add_argument("--extra", nargs="*", default=[], help="extra dirs to scan (e.g. ../extract-book-standalone)")

    q = sub.add_parser("quality")
    q.add_argument("hyp")
    q.add_argument("ref")
    q.add_argument("--apply", help="MODULE:FUNC applied to every hyp page first")
    q.add_argument("--min-count", type=int, default=3)

    s = sub.add_parser("stage")
    s.add_argument("raw")
    s.add_argument("ref")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--cleaned", help="cleaned file with the same [[page N]] markers")
    g.add_argument("--apply", help="MODULE:FUNC that cleans one page, e.g. core.text_cleaner:clean_text")

    r = sub.add_parser("rules")
    r.add_argument("hyp")
    r.add_argument("ref")
    r.add_argument("--table", required=True, help="MODULE:NAME of (src, dst) pairs or a dict")
    r.add_argument("--mode", choices=["substring", "token"], default="substring")

    a = ap.parse_args(argv)
    {"map": cmd_map, "quality": cmd_quality, "stage": cmd_stage, "rules": cmd_rules}[a.cmd](a)


if __name__ == "__main__":
    main()
