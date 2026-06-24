"""
Description:
    This file define the ui of the usermanual tab.
    This UI is using the mardown library and is simply rendering the content of 'user_manual.md'

"""

import markdown
from PyQt5.QtWidgets import QTextBrowser
from pymeasure.display.widgets import TabWidget

class UserManualTab(TabWidget, QTextBrowser):
    def __init__(self, name, parent=None):
        """
        Initialize a UserManualTab object.

        Args:
            name (str): The name of the tab.
            parent (QWidget): The parent widget (default: None).
        """
        super().__init__(parent)
        self.name = name

        with open("doc/user_manual.md", "r", encoding="utf-8") as file:
            content = file.read()

        html = markdown.markdown(content)

        self.setHtml(html)
