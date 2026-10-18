"""آزمون ابزار audio-trace (ردگیری صفحه‌به‌صفحه تا صدا).

مهم‌ترین آزمون: ابزار باید خرابی واقعی را «بگیرد» (عنوان حذف‌شده، عدد کوتاه‌شده،
نخست‌وزیر ← نخست و زیر)، نه این‌که همیشه «سالم» بگوید.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
TOOL = BACKEND.parent / ".skills" / "audio-trace" / "audio_trace.py"

spec = importlib.util.spec_from_file_location("audio_trace", TOOL)
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)

REF = """[[page 1]]
پاسخ به تاریخ
فصل چهارم: انقلاب سفید و کارگران
جمعیت تهران در سال ۱۳۳۵ برابر با ۱۵۰۰۰۰۰ نفر بود و ۲/۵ میلیون خانواده مالک شدند.
[[page 2]]
زمانی که او نخست‌وزیر شد به ما خبر دادند.
"""


def _write(tmp_path, s4_texts, merges=True):
    ref = tmp_path / "ref.txt"
    ref.write_text(REF, encoding="utf-8")
    tr = tmp_path / "tr"
    tr.mkdir()
    jobs = [{"path": str(tmp_path / f"c{i}.mp3"), "text": t} for i, t in enumerate(s4_texts)]
    T = {"input": "x", "fake": True, "s1": s4_texts, "s2": [{"type": "p", "text": t} for t in s4_texts],
         "s3": [["t", s4_texts]], "s4": jobs,
         "merges": [{"out": str(tmp_path / "ch.mp3"), "inputs": [j["path"] for j in jobs]}] if merges else []}
    (tr / "trace.json").write_text(json.dumps(T, ensure_ascii=False), encoding="utf-8")
    return ref, tr


GOOD = [
    '<speak>پاسخ به تاریخ.<break time="500ms"/></speak>',
    '<speak>فصل چهارم: انقلاب سفید و کارگران.<break time="500ms"/> جمعیت تهران در سال ۱۳۳۵ برابر با '
    '۱۵۰۰۰۰۰ نفر بود و ۲ ممیز ۵ میلیون خانواده مالک شدند.<break time="500ms"/> '
    'زمانی که او نخست‌وزیر شد به ما خبر دادند.</speak>',
]
BAD = [
    # عنوان «پاسخ به تاریخ» و «فصل چهارم…» حذف، عدد کوتاه، «و» جدا
    '<speak>جمعیت تهران در سال ۱۳۳۵ برابر با ۱۵۰ نفر بود و ۲ ممیز ۵ میلیون خانواده مالک شدند.'
    '<break time="500ms"/> زمانی که او نخست و زیر شد به ما خبر دادند.</speak>',
]


def test_good_pipeline_has_no_errors(tmp_path):
    ref, tr = _write(tmp_path, GOOD)
    rc = at.main(["check", "--ref", str(ref), "--trace", str(tr), "--strict", "--quiet",
                  "--report", str(tmp_path / "r.txt")])
    assert rc == 0
    rep = (tmp_path / "r.txt").read_text(encoding="utf-8")
    assert "✓ «پاسخ به تاریخ»" in rep and "✓ «فصل چهارم: انقلاب سفید و کارگران»" in rep


def test_bad_pipeline_is_caught(tmp_path):
    ref, tr = _write(tmp_path, BAD)
    rc = at.main(["check", "--ref", str(ref), "--trace", str(tr), "--strict", "--quiet",
                  "--report", str(tmp_path / "r.txt")])
    assert rc == 1
    rep = (tmp_path / "r.txt").read_text(encoding="utf-8")
    assert "✗ «پاسخ به تاریخ»" in rep
    assert "✗ «فصل چهارم: انقلاب سفید و کارگران»" in rep
    assert "«#1500000» ← «#150»" in rep
    assert "«وزیر» ← «و زیر»" in rep


def test_number_forms_are_equal():
    assert at.num_value("۲/۵") == at.num_value("۲ ممیز ۵") == "2.5"
    assert at.num_value("۲/۵۰۰/۰۰۰") == at.num_value("۲۵۰۰۰۰۰") == "2500000"
    assert at.num_value("۱۳۵۷/۱۱/۲۲") == "1357/11/22"


def test_waw_split_is_not_just_spacing():
    assert at.categorize(["وزیر"], ["و", "زیر"], {}) == "changed"
    assert at.categorize(["میشود"], ["می", "شود"], {}) == "spacing"


@pytest.mark.parametrize("v,words", [
    ("1500000", "یک میلیون و پانصد هزار"),
    ("1335", "هزار و سیصد و سی و پنج"),
    ("2.5", "دو ممیز پنج"),
    ("255000", "دویست و پنجاه و پنج هزار"),
])
def test_fa_words(v, words):
    assert at.fa_words(v) == words


def test_uncertain_marked_in_checklist(tmp_path):
    ref, tr = _write(tmp_path, GOOD)
    unc = tmp_path / "u.txt"
    unc.write_text("# x\n1\t۱۵۰۰۰۰۰\tحدس — نیاز به تطبیق با تصویر\tتهران\n", encoding="utf-8")
    at.main(["check", "--ref", str(ref), "--trace", str(tr), "--uncertain", str(unc), "--quiet",
             "--report", str(tmp_path / "r.txt"), "--checklist", str(tmp_path / "c.txt")])
    c = (tmp_path / "c.txt").read_text(encoding="utf-8")
    assert "عدد 1500000 ← باید بشنوی: «یک میلیون و پانصد هزار»   (عدد خودِ کتاب هنوز تأیید نشده)" in c


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg لازم است")
def test_capture_real_fva_fake_audio(tmp_path):
    """fva.py واقعی، فقط Edge ساختگی: عنوان و عدد تا متن ارسالی سالم می‌رسند."""
    inp = tmp_path / "in.txt"
    inp.write_text(REF.replace("[[page 1]]\n", "").replace("[[page 2]]\n", ""), encoding="utf-8")
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(TOOL), "capture", str(inp), "--out", str(out), "--fake"],
                       cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    ref = tmp_path / "ref.txt"
    ref.write_text(REF, encoding="utf-8")
    rc = at.main(["--backend", str(BACKEND), "check", "--ref", str(ref), "--trace", str(out),
                  "--strict", "--quiet", "--report", str(tmp_path / "r.txt")])
    assert rc == 0, (tmp_path / "r.txt").read_text(encoding="utf-8")
