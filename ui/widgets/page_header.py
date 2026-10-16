"""
ui/widgets/page_header.py
Title block for FileManagerPro's own pages shown in the content area (Duplicates,
Inspector), in the style of Explorer's Home / Gallery headings.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.theme import style


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 4)
        lay.setSpacing(2)
        self.title = QLabel(title, self)
        self.title.setAccessibleName(title)
        style(self.title, "color: @text_primary; font-size: 20pt; font-weight: 600;")
        lay.addWidget(self.title)
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setWordWrap(True)
        style(self.subtitle, "color: @text_secondary;")
        self.subtitle.setVisible(bool(subtitle))
        lay.addWidget(self.subtitle)


def page(title: str, subtitle: str, body: QWidget) -> QWidget:
    """`body` under a PageHeader, as one widget for the window's page stack."""
    holder = QWidget()
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    holder.header = PageHeader(title, subtitle, holder)
    lay.addWidget(holder.header)
    lay.addWidget(body, 1)
    holder.body = body
    return holder
