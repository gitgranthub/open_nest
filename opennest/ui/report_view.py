"""A Research project's report, shown in the Workbench as the PDF's own pages.

Not a second drawing of the report. The pages here are the bytes Export PDF writes
(:func:`opennest.export.report.build`), rendered by Qt's PDF engine, so what the child
sees is what they save -- a preview that differs from the export cannot happen.

**Pictures of the pages, not QPdfView.** Qt's own viewer renders on a thread of its own
and frames the pages in its grey; this renders each page when shown, about 12 ms a page
at panel width (SPIKES.md section 34), again when the panel changes size, and sits in
the theme's colours.

**The website preview's ``PdfViewerEnabled=False`` is a different thing.** That turns off
Chromium's viewer for whatever PDF a child's web page opens. This shows only a PDF Open
Nest made itself, from the project's words and pictures: no scripts, forms or links.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

#: Room around and between the pages, in pixels.
PAGE_GAP = 12


class ReportView(QScrollArea):
    """The pages of one report, one under another, as wide as the panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The pages follow the panel's width; they never ask the splitter for more.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setProperty("role", "bare")
        self.viewport().setProperty("role", "bare")
        body = QWidget()
        body.setProperty("role", "bare")
        self._pages_layout = QVBoxLayout(body)
        self._pages_layout.setContentsMargins(2, 2, 2, 2)
        self._pages_layout.setSpacing(PAGE_GAP)
        self._pages_layout.addStretch(1)
        self.setWidget(body)
        self._document = QPdfDocument(self)
        # The document reads from these for as long as it is open, so they are kept.
        self._bytes = QByteArray()
        self._buffer: QBuffer | None = None
        self._pages: list[QLabel] = []
        self._rendered = 0
        # A drag across the splitter is dozens of resizes; draw once it settles.
        self._resized = QTimer(self)
        self._resized.setSingleShot(True)
        self._resized.setInterval(80)
        self._resized.timeout.connect(self._render)

    def show_pdf(self, pdf: bytes) -> int:
        """Show these bytes' pages. Returns how many there are; 0 if they did not open."""
        self.clear()
        self._bytes = QByteArray(pdf)
        self._buffer = QBuffer(self._bytes, self)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._document.load(self._buffer)
        if self._document.status() != QPdfDocument.Status.Ready:
            return 0
        for number in range(self._document.pageCount()):
            page = QLabel()
            page.setProperty("role", "reportPage")
            page.setAccessibleName(f"Page {number + 1} of {self._document.pageCount()}")
            self._pages_layout.insertWidget(number, page, 0, Qt.AlignmentFlag.AlignHCenter)
            self._pages.append(page)
        self._render()
        return len(self._pages)

    def clear(self) -> None:
        for page in self._pages:
            self._pages_layout.removeWidget(page)
            page.deleteLater()
        self._pages = []
        self._rendered = 0
        self._document.close()
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None

    def page_count(self) -> int:
        return len(self._pages)

    def page_image(self, number: int) -> QImage:
        """Page ``number`` (from 0) as it is on screen."""
        return self._pages[number].pixmap().toImage()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if self._pages:
            self._resized.start()

    def _render(self) -> None:
        width = max(self.viewport().width() - 6, 160)
        if not self._pages or width == self._rendered:
            return
        ratio = self.devicePixelRatioF()
        for number, page in enumerate(self._pages):
            points = self._document.pagePointSize(number)
            height = round(width * points.height() / points.width())
            image = self._document.render(number, QSize(round(width * ratio),
                                                        round(height * ratio)))
            image.setDevicePixelRatio(ratio)
            page.setPixmap(QPixmap.fromImage(image))
            page.setFixedSize(width + 2, height + 2)     # and its 1px border
        self._rendered = width
