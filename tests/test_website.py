"""The Website profile, and the boundary its preview runs behind.

A website is the one thing Open Nest shows a child that is neither a process nor a
picture, so the kernel-enforced boundary every other project runs behind
(``security/process_sandbox.py``) has nothing to attach to. These tests cover what
replaces it.

The split between the two halves is deliberate and measured (SPIKES.md section 19):
Chromium refuses a remote request from a ``file:`` page *before* the interceptor is
consulted, and the interceptor is what stops the page reading files outside the project.
The policy below is therefore tested as the second of those, and
:func:`remote_references` exists because the first one is silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opennest.execution import web_preview
from opennest.projects.manager import create_project
from opennest.projects.profiles import get_profile

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture()
def site(tmp_path: Path):
    return create_project("Arcade", "website", root=tmp_path)


# --------------------------------------------------------------------------- the profile

def test_a_website_is_previewed_rather_than_executed() -> None:
    """No process, no exit code, and nothing for the sandbox to confine."""
    profile = get_profile("website")
    assert profile.previews
    assert not profile.can_run
    assert not profile.can_compile
    assert not profile.generates


def test_the_website_profile_needs_no_toolchain() -> None:
    """Section 6: a first website is files, not React, Node, npm or a bundler."""
    profile = get_profile("website")
    assert profile.packages == ()
    assert profile.frameworks == ()


def test_gary_gets_no_tool_that_would_let_him_claim_to_have_looked() -> None:
    """The section 13 honesty rule, applied to a rendered page.

    He cannot see the page any more than he can see a picture, so there is no preview
    tool to call and nothing that would return "the page looks fine".
    """
    profile = get_profile("website")
    assert "run_project" not in profile.tools
    assert "compile_project" not in profile.tools
    assert not any("preview" in tool for tool in profile.tools)


def test_the_website_prompt_says_he_has_not_seen_the_page() -> None:
    prompt = get_profile("website").system_prompt().lower()
    assert "you have not seen the page" in prompt
    # And the no-toolchain rule is stated to the model, not only to the reader here.
    for banned in ("react", "npm", "bundler"):
        assert banned in prompt, banned


# --------------------------------------------------------------------- the shipped kit

def test_the_starter_is_three_files_and_a_place_for_pictures(site) -> None:
    """Section 6's structure, exactly."""
    src = site.directory / "src"
    assert sorted(p.name for p in src.iterdir()) == [
        "assets", "index.html", "script.js", "styles.css",
    ]


def test_the_starter_loads_nothing_from_the_internet(site) -> None:
    """Section 17, checked on the shipped bytes rather than asserted in a comment."""
    assert web_preview.remote_references(site) == ()


def test_the_starter_is_semantic_responsive_and_reachable(site) -> None:
    """Section 6's list, each as something that is either in the file or is not."""
    html = (site.directory / "src" / "index.html").read_text(encoding="utf-8")
    for tag in ("<header", "<nav", "<main", "<section", "<footer", "<h1", "<h2"):
        assert tag in html, tag
    assert 'lang="en"' in html
    assert 'name="viewport"' in html

    css = (site.directory / "src" / "styles.css").read_text(encoding="utf-8")
    assert "@media" in css, "nothing responds to the size of the window"
    assert "focus-visible" in css, "no visible focus ring for a keyboard user"
    # A downloaded font is a network request wearing a different hat.
    assert "@font-face" not in css
    assert "@import" not in css


def test_the_starter_has_one_javascript_interaction(site) -> None:
    script = (site.directory / "src" / "script.js").read_text(encoding="utf-8")
    assert "addEventListener" in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script


# --------------------------------------------------------------------------- the policy

def test_the_page_may_read_the_project(site) -> None:
    policy = web_preview.PreviewPolicy(root=site.directory)
    assert policy.allows((site.directory / "src" / "index.html").as_uri())
    # One level up from the page: where a child's imported pictures actually land.
    picture = site.directory / "assets" / "dragon.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert policy.allows(picture.as_uri())


def test_the_page_may_not_read_anything_else(site, tmp_path: Path) -> None:
    """Measured to be the interceptor's actual job (SPIKES.md section 19).

    A real ``<iframe src="file:///…/outside">`` was seen by the hook, blocked, and the
    canary inside it did not reach the page.
    """
    policy = web_preview.PreviewPolicy(root=site.directory)
    outside = tmp_path / "secret.txt"
    outside.write_text("canary", encoding="utf-8")
    assert not policy.allows(outside.as_uri())
    assert not policy.allows("file:///etc/passwd")
    assert not policy.allows("file:///etc/../etc/passwd")


def test_a_symlink_out_of_the_project_is_still_out(site, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("canary", encoding="utf-8")
    link = site.directory / "src" / "escape.txt"
    link.symlink_to(outside)
    policy = web_preview.PreviewPolicy(root=site.directory)
    assert not policy.allows(link.as_uri())


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example.com/framework.js",
        "http://example.com/tracker.gif",
        "ws://example.com/socket",
        "ftp://example.com/file",
        "chrome://settings",
        "devtools://devtools/bundled/x.js",
    ],
)
def test_nothing_that_is_not_a_project_file_is_allowed(site, url: str) -> None:
    """Refused because they were not allowed, not because someone listed them."""
    assert not web_preview.PreviewPolicy(root=site.directory).allows(url)


def test_the_page_may_use_what_it_already_has(site) -> None:
    """``about:``, ``data:`` and ``blob:`` reach neither the network nor the disk.

    ``chrome-error:`` is how the engine draws its own failure page -- refusing that one
    makes a blocked load look like a crash.
    """
    policy = web_preview.PreviewPolicy(root=site.directory)
    for url in ("about:blank", "data:image/png;base64,iVBORw0KGgo=", "blob:x",
                "chrome-error://chromewebdata/"):
        assert policy.allows(url), url


def test_a_refusal_says_something_a_child_can_act_on(site) -> None:
    policy = web_preview.PreviewPolicy(root=site.directory)
    internet = policy.refusal("https://cdn.example.com/framework.js")
    assert "internet" in internet
    assert "cdn.example.com" in internet
    assert "outside the project" in policy.refusal("file:///etc/passwd")


# ------------------------------------------------------------- telling the child anyway

def test_a_remote_reference_in_the_page_is_found_before_the_render(site) -> None:
    """The gap the measurement exposed.

    Chromium drops the request before the interceptor sees it, so without this the only
    symptom of a CDN font or a hotlinked picture is that it is missing.
    """
    page = site.directory / "src" / "index.html"
    page.write_text(
        '<img src="https://example.com/cat.gif" alt="a cat">', encoding="utf-8"
    )
    found = web_preview.remote_references(site)
    assert [r.url for r in found] == ["https://example.com/cat.gif"]
    assert found[0].file == "index.html"
    assert found[0].line == 1


def test_a_url_in_a_comment_is_not_reported(site) -> None:
    """The starter explains itself in comments; warning about those trains them away."""
    (site.directory / "src" / "notes.css").write_text(
        "/* see https://example.com/docs for more */\n"
        "// https://example.com/other\n"
        "body { color: red; }\n",
        encoding="utf-8",
    )
    assert web_preview.remote_references(site) == ()


def test_a_remote_stylesheet_and_a_fetch_are_both_reported(site) -> None:
    (site.directory / "src" / "index.html").write_text(
        '<link rel="stylesheet" href="https://fonts.example.com/x.css">', encoding="utf-8"
    )
    (site.directory / "src" / "script.js").write_text(
        'fetch("https://api.example.com/things")', encoding="utf-8"
    )
    urls = {r.url for r in web_preview.remote_references(site)}
    assert urls == {"https://fonts.example.com/x.css", "https://api.example.com/things"}


def test_the_warning_names_the_first_one_and_counts_the_rest(site) -> None:
    (site.directory / "src" / "index.html").write_text(
        '<img src="https://a.example.com/1.gif">\n<img src="https://b.example.com/2.gif">',
        encoding="utf-8",
    )
    warning = web_preview.remote_warning(web_preview.remote_references(site))
    assert "https://a.example.com/1.gif" in warning
    assert "1 more" in warning
    assert "Wi-Fi off" in warning


def test_a_page_with_nothing_remote_says_nothing(site) -> None:
    assert web_preview.remote_warning(web_preview.remote_references(site)) == ""


# --------------------------------------------------------------------------- the page

def test_an_empty_website_project_has_nothing_to_preview(tmp_path: Path) -> None:
    """Starting empty is a supported choice, so it cannot render a blank window."""
    empty = create_project("Nothing Yet", "website", starter_id=None, root=tmp_path)
    assert not web_preview.is_previewable(empty)
    assert web_preview.is_previewable(create_project("Full", "website", root=tmp_path))


def test_a_project_that_does_not_preview_is_never_previewable(tmp_path: Path) -> None:
    game = create_project("Asteroids", "games", root=tmp_path)
    assert not web_preview.is_previewable(game)


def test_the_page_a_preview_opens_is_the_profiles_entry_point(site) -> None:
    assert web_preview.entry_file(site) == site.directory / "src" / "index.html"
    assert web_preview.entry_url(site).startswith("file://")
    assert web_preview.entry_url(site).endswith("/src/index.html")
