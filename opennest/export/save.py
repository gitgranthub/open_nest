"""Writing a report outside Open Nest: one file, where a person chose, once.

HANDOFF section 5: export is a **privileged application action**. Everything Open Nest
writes lives under ``OPENNEST_HOME``, and saving to a parent's Documents folder crosses
that line on purpose -- so it is granted one more thing, explicitly, and nothing else.
``process_sandbox.grant_devices`` is the worked instance (one serial port, validated);
this is the same shape for a file.

- **The only way to a destination is a save dialog a person answered.** The Workbench
  turns the dialog's answer into a :class:`Destination` with :func:`from_dialog`, which
  checks it. Nothing else makes one, no tool can reach this module, and Gary has no way to
  name a path here: export is a button, not one of the four tools.
- **A destination is good for one write.** :func:`write` takes the grant and the report,
  never a path, so it cannot write anywhere but the chosen file -- and the grant is spent
  by writing. The next export asks again.
- **What leaves is scanned first**, with the scanner a GitHub push uses: every piece of text
  the PDF was made from (:attr:`Report.words`). The pixels of a chart cannot be scanned;
  the code that drew it is not in the PDF.
- **No parent PIN** (PLAN.md decision D14). A child must be able to save their own work,
  and a person choosing a place in a real save dialog is the permission -- the same logic
  that let Check for Updates go without one (D9).
- **Nothing is said that was not checked.** After writing, the file is read back: there,
  the right size, a PDF. Only then is "Saved" said.

The write itself goes to a hidden file beside the destination and is then renamed over
it, so a write that fails half-way leaves the old file as it was and no half a PDF.
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from opennest import paths
from opennest.export.report import Report
from opennest.versioning.secret_scanner import Finding, scan_text

SUFFIX = ".pdf"

#: Grants made by :func:`from_dialog` and not yet used, by nonce. A grant is checked
#: against what was validated, so changing a :class:`Destination` after the dialog does
#: not change where the file goes.
_ISSUED: dict[int, Path] = {}


class ExportRefused(Exception):
    """The report was not saved. The message is for the child."""


@dataclass(frozen=True)
class Destination:
    """Where a person chose to save one report. Made only by :func:`from_dialog`."""

    path: Path
    _nonce: int = field(default=0, repr=False, compare=False)


@dataclass(frozen=True)
class Saved:
    path: Path
    size: int
    pages: int

    def sentence(self) -> str:
        """What the child is told, from what was checked on disk."""
        pages = f"{self.pages} page{'' if self.pages == 1 else 's'}"
        return f"Saved “{self.path.name}” in {_folder_name(self.path.parent)}. {pages}."


def default_name(project_name: str) -> str:
    """``Weather Study report.pdf``: the project's name, safe as a file name."""
    name = re.sub(r"[/:\\\x00-\x1f]+", " ", project_name).strip().lstrip(".")
    name = " ".join(name.split())[:80] or "Report"
    return f"{name} report{SUFFIX}"


def default_folder() -> Path:
    """Where the save dialog opens: Documents, else the Desktop, else home."""
    home = Path.home()
    for candidate in (home / "Documents", home / "Desktop"):
        if candidate.is_dir():
            return candidate
    return home


def _folder_name(folder: Path) -> str:
    return folder.name or str(folder)


def _inside(path: Path, folder: Path) -> bool:
    """Whether ``path`` is ``folder`` or under it -- casefolded, because macOS paths are
    (HANDOFF section 4)."""
    try:
        folder = folder.resolve()
    except OSError:
        return False
    there = [part.casefold() for part in folder.parts]
    here = [part.casefold() for part in path.parts]
    return here[:len(there)] == there


def from_dialog(chosen: str) -> Destination:
    """Check what the save dialog returned, and grant one write there.

    Raises :class:`ExportRefused` with the reason, said for the child.
    """
    text = (chosen or "").strip()
    if not text:
        raise ExportRefused("No file name was chosen, so nothing was saved.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ExportRefused("Open Nest needs a whole location to save to. Press Export PDF "
                            "and choose a folder.")
    if path.suffix.lower() != SUFFIX:
        raise ExportRefused("A report is saved as a PDF. Choose a name that ends in .pdf.")
    try:
        folder = path.parent.resolve(strict=True)
    except OSError:
        raise ExportRefused(f"The folder “{path.parent.name}” is not there any "
                            f"more. Choose another one.") from None
    if not folder.is_dir():
        raise ExportRefused(f"“{path.parent.name}” is not a folder. Choose "
                            f"another one.")
    target = folder / path.name
    if target.is_symlink():
        raise ExportRefused(f"“{path.name}” there is a shortcut to another file. "
                            f"Choose another name.")
    if target.exists() and not target.is_file():
        raise ExportRefused(f"“{path.name}” there is a folder, not a file. Choose "
                            f"another name.")
    for location in paths.managed_locations().values():
        if _inside(target, location):
            raise ExportRefused(
                f"“{_folder_name(folder)}” is where Open Nest keeps its own "
                f"files. Save the report somewhere else, like Documents or the Desktop.")
    if not os.access(folder, os.W_OK):
        raise ExportRefused(f"Open Nest can't save in “{_folder_name(folder)}”: "
                            f"this Mac does not allow writing there. Choose another folder, "
                            f"like Documents.")
    nonce = secrets.randbits(63) | 1
    _ISSUED[nonce] = target
    return Destination(target, nonce)


def scan(report: Report) -> list[Finding]:
    """Anything credential-shaped in what the report was made from."""
    findings: list[Finding] = []
    for relative, text in report.words:
        findings.extend(scan_text(text, Path(relative).name))
    findings.extend(scan_text(report.title, "the title"))
    return findings


def refusal(findings: list[Finding]) -> str:
    """What the child is told when the report holds something credential-shaped."""
    lines = ["The report was not saved, because something in it looks like a password or "
             "key:", ""]
    lines += [f"  {finding.describe()}" for finding in findings[:10]]
    if len(findings) > 10:
        lines.append(f"  ...and {len(findings) - 10} more")
    lines += ["", "Take it out of the file, then export again. Keys belong in Settings, where "
              "a parent can keep them in the macOS Keychain."]
    return "\n".join(lines)


def write(destination: Destination, report: Report) -> Saved:
    """Save ``report`` to ``destination``, once. Raises :class:`ExportRefused`."""
    granted = _ISSUED.pop(destination._nonce, None)
    if granted is None or granted != destination.path:
        raise ExportRefused("That place to save was for one report. Press Export PDF again "
                            "and choose where to save it.")
    findings = scan(report)
    if findings:
        raise ExportRefused(refusal(findings))

    target = granted
    folder = target.parent
    handle, temporary = None, None
    try:
        handle, temporary = tempfile.mkstemp(dir=folder, prefix=f".{target.stem}.",
                                             suffix=".partial")
        with os.fdopen(handle, "wb") as stream:
            handle = None
            # mkstemp makes it private to its owner; a saved document is not.
            os.fchmod(stream.fileno(), 0o644)
            stream.write(report.pdf)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise ExportRefused(_why_not(exc, folder)) from None
    finally:
        if handle is not None:
            os.close(handle)
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)

    # Read back, so "Saved" is a fact about the disk and not a hope about the write.
    try:
        size = target.stat().st_size
        with target.open("rb") as stream:
            head = stream.read(5)
    except OSError:
        size, head = -1, b""
    if size != len(report.pdf) or head != b"%PDF-":
        raise ExportRefused(f"Open Nest wrote the report, but could not find it in "
                            f"“{_folder_name(folder)}” afterwards. Try saving it "
                            f"again, or somewhere else.")
    return Saved(target, size, report.pages)


def _why_not(error: OSError, folder: Path) -> str:
    where = f"“{_folder_name(folder)}”"
    if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return (f"Open Nest can't save in {where}: this Mac does not allow writing there. "
                f"Choose another folder, like Documents.")
    if error.errno == errno.ENOSPC:
        return "There is not enough space on the disk to save the report."
    if error.errno == errno.ENOENT:
        return f"The folder {where} is not there any more. Choose another one."
    return f"The report could not be saved in {where}: {error.strerror or error}."
