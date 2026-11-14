import pytest

from agents.profiler.paths import (
    UnsafePathError,
    check_url,
    contained,
    readable_file,
    writable_file,
)


def test_contained_allows_a_plain_file_name(tmp_path):
    assert contained(tmp_path, "nordsense.json") == (tmp_path / "nordsense.json").resolve()


@pytest.mark.parametrize(
    "name",
    ["../escape.json", "../../etc/passwd", "sub/x.json", "/etc/passwd", ".."],
)
def test_contained_refuses_anything_outside_the_directory(tmp_path, name):
    with pytest.raises(UnsafePathError):
        contained(tmp_path, name)


def test_check_url_only_allows_http_and_https():
    assert check_url("https://example.com/about").hostname == "example.com"
    assert check_url("http://example.com").hostname == "example.com"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/about",
        "data:text/html,<p>x</p>",
        "javascript:alert(1)",
        "",
        "//example.com/about",
        "https://",
    ],
)
def test_check_url_refuses_other_schemes_and_hostless_urls(url):
    with pytest.raises(UnsafePathError):
        check_url(url)


def test_readable_file_requires_an_existing_regular_file(tmp_path):
    target = tmp_path / "page.html"
    target.write_text("<html></html>", encoding="utf-8")

    assert readable_file(target) == target.resolve()
    with pytest.raises(UnsafePathError):
        readable_file(tmp_path / "missing.html")
    with pytest.raises(UnsafePathError):
        readable_file(tmp_path)  # a directory


def test_writable_file_needs_an_existing_directory(tmp_path):
    assert writable_file(tmp_path / "out.json") == (tmp_path / "out.json").resolve()
    with pytest.raises(UnsafePathError):
        writable_file(tmp_path / "missing-dir" / "out.json")
    with pytest.raises(UnsafePathError):
        writable_file(tmp_path)  # a directory
