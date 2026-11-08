"""Tests for beam_analysis.py.

Run with:  python -m pytest test_beam_analysis.py -q
"""
import glob
import os
from collections import Counter

import pytest

import beam_analysis as ba

HW2_DATA = os.path.join(os.path.dirname(__file__), "..", "hw2", "data")


# ---------------------------------------------------------------- helpers ---

def test_parse_links_keeps_duplicates_and_basenames():
    html = '<a HREF="1.html">x</a> <a href=\'dir/2.html\'>y</a> <a href="1.html">'
    assert ba.parse_links(html) == ["1.html", "2.html", "1.html"]


def test_page_words_strips_tags_and_punctuation():
    html = "<html><body>Lorem ipsum, dolor.\n<p>\n<a HREF=\"3.html\"> This is </a>"
    assert ba.page_words(html) == ["lorem", "ipsum", "dolor", "this", "is"]


def test_trigrams():
    assert ba.trigrams(["a", "b", "c", "d"]) == ["a b c", "b c d"]
    assert ba.trigrams(["a", "b"]) == []


def test_rank_key_orders_by_count_then_natural_name():
    items = [("10.html", 5), ("2.html", 5), ("1.html", 9), ("3.html", 1)]
    assert sorted(items, key=ba.rank_key) == [
        ("1.html", 9), ("2.html", 5), ("10.html", 5), ("3.html", 1)]


def test_join_incoming_drops_missing_pages_and_keeps_zero():
    assert list(ba.join_incoming(("1.html", {"page": [1], "hits": [4]}))) == [("1.html", 4)]
    assert list(ba.join_incoming(("2.html", {"page": [1], "hits": []}))) == [("2.html", 0)]
    assert list(ba.join_incoming(("x.html", {"page": [], "hits": [7]}))) == []


# ------------------------------------------------------- whole pipeline ----

def brute_force(files):
    """The same three answers computed with plain Python, for comparison."""
    pages = {}
    for path in files:
        with open(path, encoding="utf-8") as f:
            pages[ba.basename(path)] = f.read()
    links = {name: ba.parse_links(html) for name, html in pages.items()}
    outgoing = {name: len(t) for name, t in links.items()}
    incoming = Counter({name: 0 for name in pages})
    for targets in links.values():
        for t in targets:
            if t in pages:
                incoming[t] += 1
    tri = Counter()
    for html in pages.values():
        tri.update(ba.trigrams(ba.page_words(html)))

    def top(counts):
        return sorted(counts.items(), key=ba.rank_key)[:ba.TOP_N]

    best = max(tri.values())
    ties = sum(1 for c in tri.values() if c == best)
    return len(pages), top(incoming), top(outgoing), top(tri), (best, ties)


def run_pipeline(input_pattern, output_dir, capsys):
    ba.main(["--input", input_pattern, "--output", str(output_dir)])
    return capsys.readouterr().out


def expected_text(n, top_in, top_out, top_tri, ties):
    return "\n".join([
        f"Files processed: {n:,}",
        "",
        ba.format_ranking("TOP 5 FILES BY INCOMING LINKS", top_in, "links"),
        "",
        ba.format_ranking("TOP 5 FILES BY OUTGOING LINKS", top_out, "links"),
        "",
        ba.format_ranking("TOP 5 WORD TRIGRAMS", top_tri, "times"),
        "",
        ba.format_tie_note([ties]),
    ])


def test_pipeline_small_fixture(tmp_path, capsys):
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    contents = {
        # 0 links to 1 twice and to a page that does not exist
        "0.html": 'one two three <a href="1.html">x</a> <a href="1.html">x</a>'
                  ' <a href="99.html">x</a>',
        "1.html": 'one two three four <a href="2.html">x</a>',
        "2.html": 'one two three <a href="1.html">x</a>',
    }
    for name, html in contents.items():
        (pages_dir / name).write_text(html)

    out = run_pipeline(str(pages_dir / "*.html"), tmp_path / "out", capsys)

    n, top_in, top_out, top_tri, ties = brute_force(glob.glob(str(pages_dir / "*.html")))
    assert top_in == [("1.html", 3), ("2.html", 1), ("0.html", 0)]
    assert top_out[0] == ("0.html", 3)
    assert top_tri[0] == ("one two three", 3)
    assert expected_text(n, top_in, top_out, top_tri, ties) in out


@pytest.mark.skipif(not glob.glob(os.path.join(HW2_DATA, "*.html")),
                    reason="HW2 pages not present in ../hw2/data")
def test_pipeline_matches_brute_force_on_hw2_pages(tmp_path, capsys):
    pattern = os.path.join(HW2_DATA, "*.html")
    out = run_pipeline(pattern, tmp_path / "out", capsys)
    assert expected_text(*brute_force(glob.glob(pattern))) in out
