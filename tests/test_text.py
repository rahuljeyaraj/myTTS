from mytts.text import normalize, segment, speakable


def spans(text):
    return [text[s.start : s.end] for s in segment(text)]


def test_splits_sentences_and_keeps_offsets():
    text = normalize("Hello there. How are you? I'm fine!  Thanks.")
    assert spans(text) == ["Hello there.", "How are you?", "I'm fine!", "Thanks."]


def test_abbreviations_initials_and_lowercase_continuations_do_not_split():
    text = "Dr. Smith met J. K. Rowling in the U.S. on Monday. It went well, e.g. the talk."
    assert spans(text) == [
        "Dr. Smith met J. K. Rowling in the U.S. on Monday.",
        "It went well, e.g. the talk.",
    ]


def test_quoted_question_followed_by_lowercase_stays_together():
    assert spans("“Really?” she asked. Yes.") == ["“Really?” she asked.", "Yes."]


def test_decimals_and_numbered_list_items():
    text = normalize("1. Pi is 3.14 roughly.\n2. Next item")
    assert spans(text) == ["1. Pi is 3.14 roughly.", "2. Next item"]


def test_unwraps_hard_wrapped_prose_but_keeps_lists_and_paragraphs():
    raw = (
        "This paragraph was wrapped by a PDF viewer at a fixed width and\n"
        "continues on the next line with an exam-\n"
        "ple of hyphenation.\n"
        "\n\n\n"
        "Shopping:\n"
        "- milk\n"
        "- eggs\r\n"
    )
    assert normalize(raw) == (
        "This paragraph was wrapped by a PDF viewer at a fixed width and "
        "continues on the next line with an example of hyphenation.\n\n"
        "Shopping:\n- milk\n- eggs"
    )


def test_removes_invisible_characters_and_collapses_spaces():
    assert normalize("a​­b   c\t\tdﬁ") == "ab c dfi"


def test_long_sentences_split_at_clause_boundaries():
    clause = "this clause keeps going for quite a while without stopping"
    text = ", ".join([clause] * 8) + "."
    segs = segment(text, max_chars=120)
    assert len(segs) > 1
    assert all(s.end - s.start <= 120 for s in segs)
    assert all(text[s.start : s.end].endswith((",", ".")) for s in segs)
    # Every word is covered exactly once, in order.
    assert " ".join(text[s.start : s.end] for s in segs) == text


def test_segments_without_letters_are_skipped():
    assert spans(normalize("Title\n\n***\n\nBody.")) == ["Title", "Body."]


def test_speakable_cleans_bullets_markdown_and_urls():
    assert speakable("- **Bold** `code`") == "Bold code"
    assert speakable("See https://www.example.com/a/b?c=1.") == "See link to example.com."
