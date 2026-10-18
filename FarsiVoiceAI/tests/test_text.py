from farsivoice.text import clean_text, normalize_numbers, split_sentences


def test_normalize_numbers():
    assert normalize_numbers("سال 1357") == "سال ۱۳۵۷"


def test_clean_text_spacing_and_punctuation():
    src = "  ایران امروز ، داستانی است...\n   در سال 1357 اتفاقی رخ داد .بعد"
    out = clean_text(src)
    assert "…" in out
    assert " ،" not in out
    assert "۱۳۵۷" in out
    assert "داد. بعد" in out
    assert "\n " not in out


def test_clean_text_collapses_blank_lines():
    assert clean_text("الف\n\n\n\nب") == "الف\n\nب"


def test_split_sentences():
    text = "امروز ایران را ببینیم. حالا برویم سراغ داستان؟ این فقط یک آزمایش است!"
    assert split_sentences(text) == [
        "امروز ایران را ببینیم.",
        "حالا برویم سراغ داستان؟",
        "این فقط یک آزمایش است!",
    ]


def test_split_sentences_empty():
    assert split_sentences("   \n ") == []
