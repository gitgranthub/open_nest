"""Showing a website project inside Open Nest.

The thin Qt half of :mod:`opennest.execution.web_preview`, which owns the actual policy.
Three decisions are worth knowing.

**The page is shown here, not handed to a browser.** Opening the child's ``index.html``
in Safari would work and would give the page the whole internet, a browsing history, a
cookie jar and whatever extensions are installed -- none of which Open Nest could
promise anything about. Section 16 of the Phase 11 work order says Open Nest owns this
complexity; owning it means rendering the page under a policy rather than passing it on.

**There is no local server and no port.** A static site loads from ``file:`` perfectly
well, and a port is a thing a child would have to be told about and a thing that listens.
The one cost is that ``fetch()`` of a local file will not work from a ``file:`` page --
which is fine, because section 17 rules that out anyway.

**What each guard actually stops was measured, and it is not what it looks like.**
``LocalContentCanAccessRemoteUrls=False`` is the thing that makes the internet
unreachable, and it fires *before* the interceptor; the interceptor's own contribution is
stopping the page reading files outside the project, which it was measured doing. Both
are kept. SPIKES.md section 19, and the module docstring of
:mod:`opennest.execution.web_preview`.

**The engine is created the first time a page is shown, not when the Workbench is
built.** Starting Chromium costs about a second and several processes; a child who opens
a website project and talks to Gary without pressing Preview should not pay it, and
neither should the test suite.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from opennest.execution.web_preview import PreviewPolicy

#: What to say when PySide6 was installed without its web engine. Not a crash and not a
#: silent empty panel: an installation fact, phrased for whoever has to fix it.
ENGINE_MISSING = (
    "Open Nest cannot show web pages on this Mac. The web engine that comes with "
    "PySide6 is not installed. Everything else about a website project still works, and "
    "the files are in the project's src folder."
)


def engine_available() -> bool:
    """Whether Qt's web engine can be imported.

    Probed by importing it rather than inferred from the PySide6 version: the web engine
    ships in a separate wheel from the essentials, so a perfectly good PySide6 can be
    present without it.
    """
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except Exception:
        return False
    return True


def _make_interceptor(policy: PreviewPolicy, report):
    """Qt's request hook, delegating every decision to the policy.

    Built rather than declared at module level because
    :class:`QWebEngineUrlRequestInterceptor` cannot be imported until the engine is
    known to be present.
    """
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info) -> None:  # noqa: N802 - Qt's name
            url = info.requestUrl().toString()
            if policy.allows(url):
                return
            info.block(True)
            report(policy.refusal(url))

    return Interceptor()


class WebPreview(QWidget):
    """The rendered page, with a line above it when something was refused."""

    #: Emitted with the refusal sentence when the page tried to load something blocked.
    blocked = Signal(str)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "bare")
        self.project = project
        self.policy = PreviewPolicy(root=project.directory)
        self._view = None
        self._page = None
        self._profile = None
        self._interceptor = None
        # Qt may call the interceptor from its own thread, so the widget is updated
        # through the signal rather than from inside the hook. A cross-thread emit
        # queues; a same-thread one does not, and both end up in the same slot.
        self.blocked.connect(self._show_refusal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._layout = layout

        self._notice = QLabel()
        self._notice.setProperty("role", "cardBody")
        self._notice.setProperty("state", "attention")
        self._notice.setWordWrap(True)
        self._notice.hide()
        layout.addWidget(self._notice)

        self._placeholder = QLabel("Press Preview Website to see the page.")
        self._placeholder.setProperty("role", "cardBody")
        self._placeholder.setWordWrap(True)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder, 1)

    # -- the engine ---------------------------------------------------------

    def _ensure_view(self) -> bool:
        """Build the engine on first use. False when it is not installed."""
        if self._view is not None:
            return True
        if not engine_available():
            return False

        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._interceptor = _make_interceptor(self.policy, self.blocked.emit)

        # Unnamed, so the profile is off the record: no disk cache, no cookie jar and
        # no history for a child's own page. There is nothing here worth persisting and
        # a persistent profile is a thing that would have to be cleaned up.
        profile = QWebEngineProfile(self)
        profile.setUrlRequestInterceptor(self._interceptor)
        self._profile = profile

        view = QWebEngineView(self)
        # The page is parented to the profile, not to the view. Qt destroys a profile
        # that still has a live page with "Release of profile requested but
        # WebEnginePage still not deleted. Expect troubles!", and the trouble is a crash
        # on closing the project rather than a message. Making the profile the owner is
        # what guarantees the page goes first; ``closeEvent`` below does the same job
        # for the ordinary case where the widget is closed rather than collected.
        self._page = _page(profile, profile)
        view.setPage(self._page)
        settings = view.settings()
        # Belt and braces behind the interceptor. Each of these is a route to the
        # network or to the rest of the disk that a local page could otherwise take.
        for attribute, value in (
            (QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False),
            (QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False),
            (QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False),
            (QWebEngineSettings.WebAttribute.PluginsEnabled, False),
            (QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, False),
            (QWebEngineSettings.WebAttribute.PdfViewerEnabled, False),
        ):
            settings.setAttribute(attribute, value)

        self._view = view
        self._placeholder.hide()
        self._layout.addWidget(view, 1)
        return True

    # -- showing ------------------------------------------------------------

    def show_page(self, url: str) -> bool:
        """Load one page. False when the engine is missing, having said so."""
        self._notice.hide()
        if not self._ensure_view():
            self._placeholder.setText(ENGINE_MISSING)
            return False
        self._view.setUrl(QUrl(url))
        return True

    def reload(self) -> None:
        if self._view is not None:
            self._view.reload()

    def _show_refusal(self, message: str) -> None:
        self._notice.setText(message)
        self._notice.show()

    # -- shutting down ------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """Let go of the page before the profile that owns it."""
        self._release()
        super().closeEvent(event)

    def _release(self) -> None:
        if self._view is not None:
            self._view.stop()
            self._view.setPage(None)
        if self._page is not None:
            self._page.deleteLater()
            self._page = None
            # Flushed rather than left posted. ``deleteLater`` only takes effect the
            # next time the event loop turns, and the whole point of this method is
            # that the page is gone *before* the profile it belongs to -- which, when
            # a project is closing, may be moments later and may be during teardown
            # with no loop left to turn.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _page(profile, parent):
    from PySide6.QtWebEngineCore import QWebEnginePage

    return QWebEnginePage(profile, parent)
