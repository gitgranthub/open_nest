"""What a website preview is allowed to load.

A website project is the one thing Open Nest shows a child that is neither a process nor
a picture: it is a page, rendered. There is no process to confine, so
``security/process_sandbox.py`` -- the kernel-enforced boundary every other kind of
project runs behind -- has nothing to attach to. This module is the boundary that
replaces it, and it is the same shape: a policy the caller cannot skip, refusing by
default, tested on its own.

**The rule is that a preview may read the project and nothing else.** Section 17 of the
Phase 11 work order asks that a starter website make no network request, load no remote
script, no CDN and no web font, and work offline. That is a promise about the shipped
files, and a shipped file is easy to check. What it does not cover is the page six weeks
later, after a child has asked for a picture from the internet and Gary has obliged.

**Two layers hold that, and they were measured rather than assumed** -- SPIKES.md
section 19 has the runs. It matters which does what, because the first draft of this
module claimed the wrong one:

- **Chromium's own ``LocalContentCanAccessRemoteUrls=False`` refuses every remote
  request from a ``file:`` page**, and it does so *before* the request interceptor is
  consulted. An ``<img src="https://...">``, a remote ``<link>`` and a JavaScript
  ``fetch()`` were all refused with the hook seeing nothing at all. So the internet is
  already unreachable, and :class:`PreviewPolicy` is not what makes that true.
- **The interceptor is what stops the page leaving the project on disk.** An
  ``<iframe src="file:///…/outside.txt">`` *is* seen by the hook, is blocked, and the
  canary in it did not reach the page.

**A refusal nobody can see is half a bug, so the page is also read before it is shown.**
The consequence of the first layer firing first is that a remote reference simply does
not appear -- no hook, no message, a picture that is silently missing. That is the exact
failure section 17 is about, so :func:`remote_references` reads the project's own source
and says what will not load, deterministically and before the render. Same reasoning as
``execution/outputs.py`` comparing the directory instead of asking the model: the
application can know this for itself, so it should not depend on being told.

No Qt in this module on purpose: both the policy and the scan are functions of files and
strings, so they can be tested without starting a browser engine.
``opennest/ui/web_preview.py`` is the thin part that hands Qt's request interceptor to
this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

#: Schemes that reach neither the network nor the filesystem. ``about:blank`` is what a
#: view holds before anything is loaded, ``data:`` and ``blob:`` are content the page
#: already has, and ``chrome-error:`` is how the engine renders its own failure page --
#: refusing that one makes a blocked load look like a crash.
SELF_CONTAINED_SCHEMES = frozenset({"about", "data", "blob", "chrome-error"})

#: The only scheme that touches disk, and it is checked against the project root.
FILE_SCHEME = "file"


@dataclass(frozen=True)
class PreviewPolicy:
    """Whether the page being previewed may load a given URL.

    ``root`` is the project directory rather than ``src/``: a child's imported pictures
    live in the project's ``assets/``, one level up from the page, and a website that
    could not show them would send them to the internet for pictures instead.
    """

    root: Path

    def allows(self, url: str) -> bool:
        """Whether the page may load this.

        Measured to be consulted for ``file:`` requests and, in the shipped
        configuration, never for remote ones -- Chromium refuses those first. The
        remote branch is kept anyway: it is one line, it is what makes the rule
        "everything except the project" rather than "whatever Chromium happens to
        allow", and it would be the boundary again the day that setting moved.
        """
        scheme = urlsplit(url).scheme.lower()
        if scheme in SELF_CONTAINED_SCHEMES:
            return True
        if scheme != FILE_SCHEME:
            # Everything not named above, which is the point: http, https, ws, ftp and
            # anything a future engine invents are refused because they were not
            # allowed, not because somebody remembered to list them.
            return False
        target = local_path(url)
        if target is None:
            return False
        return _is_inside(self.root, target)

    def refusal(self, url: str) -> str:
        """Why that was blocked, in a sentence a child can act on."""
        scheme = urlsplit(url).scheme.lower()
        if scheme in {"http", "https"}:
            return (
                f"This page tried to load something from the internet "
                f"({_host(url) or url}). Open Nest blocked it, so the page works the "
                f"same with the Wi-Fi off. Put the file in the project instead."
            )
        if scheme == FILE_SCHEME:
            return (
                "This page tried to open a file outside the project. Open Nest blocked "
                "it. Everything the page uses has to live in the project."
            )
        return f"This page tried to use {scheme or 'something'}, which Open Nest blocks."


def local_path(url: str) -> Path | None:
    """The filesystem path a ``file:`` URL names, or None if it names none."""
    parts = urlsplit(url)
    if parts.scheme.lower() != FILE_SCHEME or not parts.path:
        return None
    # A file URL for another host is not this machine's filesystem.
    if parts.netloc and parts.netloc.lower() != "localhost":
        return None
    return Path(unquote(parts.path))


def _is_inside(root: Path, target: Path) -> bool:
    """Containment, resolved so that ``..`` and symlinks cannot get out.

    Deliberately fails closed: a path that cannot be resolved is not inside anything.
    """
    try:
        base = Path(root).resolve(strict=True)
        candidate = Path(target).resolve()
    except OSError:
        return False
    return candidate == base or base in candidate.parents


def _host(url: str) -> str:
    return urlsplit(url).netloc


# ------------------------------------------------------------------ what will not load

#: Text files worth reading for remote references. A binary asset cannot carry one that
#: the engine would follow from a page.
SCANNED_SUFFIXES = frozenset({".html", ".htm", ".css", ".js", ".svg", ".json"})

#: Lines that only talk about a URL rather than asking for one. Comments are the common
#: false positive -- the shipped starter explains itself in them -- and a note about an
#: address fetches nothing.
_COMMENT_STARTS = ("//", "/*", "*", "<!--", "#")

_REMOTE = re.compile(r"https?://[^\s\"'`)<>]+", re.IGNORECASE)

#: Read at most this much of a file. A page a child wrote is kilobytes; a pasted blob of
#: base64 could be megabytes, and scanning it line by line buys nothing.
_SCAN_LIMIT_BYTES = 512_000


@dataclass(frozen=True)
class RemoteReference:
    """One address the page asks for that the preview will not fetch."""

    file: str
    line: int
    url: str


def remote_references(project) -> tuple[RemoteReference, ...]:
    """Every internet address the project's own source asks for.

    Read from the files rather than observed during the render, because the render does
    not report them: Chromium drops a remote request from a ``file:`` page before
    anything Open Nest installed is consulted, so the only signal at that point is a
    picture that is not there.

    Deliberately conservative in one direction only. A line that is plainly a comment is
    skipped, because the starter explains itself in comments and warning about those
    would train a child to ignore the warning. Everything else counts, including a URL
    in a string the page may never use -- over-reporting costs a sentence, and
    under-reporting costs the one explanation of why the page looks wrong.
    """
    source = Path(project.directory) / "src"
    if not source.is_dir():
        return ()
    found: list[RemoteReference] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _SCAN_LIMIT_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = str(path.relative_to(source))
        for number, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith(_COMMENT_STARTS):
                continue
            for match in _REMOTE.finditer(line):
                found.append(RemoteReference(relative, number, match.group(0)))
    return tuple(found)


def remote_warning(references) -> str:
    """One sentence about what will not load, or empty when there is nothing to say."""
    references = tuple(references)
    if not references:
        return ""
    first = references[0]
    others = len(references) - 1
    tail = f" (and {others} more)" if others else ""
    return (
        f"This page asks for something on the internet -- {first.url} in "
        f"{first.file}{tail}. Open Nest does not load it, so the page works the same "
        f"with the Wi-Fi off. Put the file in the project instead."
    )


# --------------------------------------------------------------------------- the page

def entry_file(project) -> Path:
    """The page a preview opens: the profile's entrypoint inside ``src/``."""
    return project.directory / "src" / project.manifest.entrypoint


def entry_url(project) -> str:
    """That page as a ``file:`` URL."""
    return entry_file(project).resolve().as_uri()


def is_previewable(project) -> bool:
    """Whether there is actually a page to show yet.

    False for a project started empty, which is a normal state rather than a fault --
    the Workbench offers the starter instead of rendering a blank window.
    """
    return project.profile.previews and entry_file(project).is_file()
