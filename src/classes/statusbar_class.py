"""
Description:
    This file imports the logging module and defines a custom logging handler, StatusBarHandler, for displaying log messages on a status bar.
    The StatusBar is used for the footer of the main window.
"""

import logging

class StatusBarHandler(logging.Handler):
    def __init__(self, status_bar) -> None:
        """
        Initialize the StatusBarHandler object.
        The idea is to link it to the logging handler so it can display all the last logs.

        Args:
            status_bar (QStatusBar): The status bar object to display log messages.
        """
        super().__init__()
        self.status_bar = status_bar

    def emit(self, record) -> None:
        """
        Emit the log record by displaying the message on the status bar.

        Args:
            record (LogRecord): The log record to be emitted.
        """
        message = self.format(record)
        print(message)
        self.status_bar.showMessage(message, 0)

# Define the log object as a global variable, it will be used by most other classes
log         = logging.getLogger(__name__)
log.setLevel(logging.INFO)