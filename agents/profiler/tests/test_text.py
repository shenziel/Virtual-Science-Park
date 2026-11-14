from agents.profiler.text import collapse, html_to_document, is_verbatim, sentences, truncate
from agents.profiler.tests.conftest import PAGE_HTML


def test_html_to_document_drops_scripts_and_keeps_text():
    document = html_to_document(PAGE_HTML)
    assert "We develop industrial IoT sensors" in document.text
    assert "ignore previous instructions" not in document.text
    assert document.title.startswith("NordSense AB")
    assert document.description.startswith("NordSense develops industrial IoT sensors")


def test_sentences_are_quote_sized():
    document = html_to_document(PAGE_HTML)
    found = sentences(document.text)
    assert "We develop industrial IoT sensors for predictive maintenance in heavy industry." in found
    assert all(len(s) >= 20 for s in found)


def test_is_verbatim_ignores_case_and_whitespace():
    text = "A lignin-based   barrier coating keeps grease out."
    assert is_verbatim("A lignin-based barrier coating", text)
    assert is_verbatim("a LIGNIN-BASED barrier coating keeps grease out.", text)
    assert not is_verbatim("A plastic-based barrier coating", text)
    assert not is_verbatim("", text)


def test_collapse_and_truncate():
    assert collapse("  a\n b\tc ") == "a b c"
    assert truncate("word " * 100, 20).endswith("\u2026")
    assert truncate("short", 20) == "short"
