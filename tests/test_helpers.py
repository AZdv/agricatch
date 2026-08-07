import datetime

from lxml import etree

from agricatch import xpath_functions
from agricatch.helpers import text as text_helpers


def test_extension_functions_are_usable_from_xpath():
    doc = etree.fromstring("<r><p>example;tokenize;string</p><q>make me a title</q></r>")
    assert doc.xpath('tokenize(//p/text(), ";")') == ["example", "tokenize", "string"]
    assert doc.xpath("make_title(//q/text())") == "Make Me A Title"


def test_findzipcode_returns_every_match():
    doc = etree.fromstring("<r><p>Berlin 10115 and 10247</p></r>")
    assert doc.xpath("findzipcode(//p/text())") == ["10115", "10247"]


def test_iter_functions_exposes_names_without_the_prefix():
    names = dict(xpath_functions.iter_functions())
    assert {"tokenize", "make_title", "findzipcode"} <= set(names)


def test_slugify_transliterates_and_cleans():
    assert text_helpers.slugify("Straße  &amp; Größe!") == "strasse-groesse"


def test_slugify_can_skip_the_aggressive_pass():
    assert text_helpers.slugify("Grüße!", extra_clean=False) == "gruesse!"


def test_replace_parameters_expands_the_crawl_date():
    when = datetime.date(2024, 3, 9)
    assert text_helpers.replace_parameters("/e/%Y-%m-%d", when) == "/e/2024-03-09"


def test_relative_url_to_absolute_handles_both_forms():
    base = "https://example.com/blog/"
    assert text_helpers.relative_url_to_absolute("/a", base) == "https://example.com/a"
    assert text_helpers.relative_url_to_absolute("//cdn.example.com/i.png", base) == (
        "https://cdn.example.com/i.png"
    )


def test_collapse_whitespace():
    assert text_helpers.collapse_whitespace("  a \n\t b  ") == "a b"
