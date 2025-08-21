import logging
import os
from datetime import datetime


class Logger:
    """
    A singleton Logger class to handle logging operations.

    This class ensures that only one instance of the logger is created and used
    throughout the application. It supports logging to both a file and the console,
    with different log levels (INFO and DEBUG).

    Attributes:
        _instance (Logger): The singleton instance of the Logger class.
        _initialized (bool): A flag to indicate if the logger has been initialized.
        logger (logging.Logger): The underlying logger instance from the logging module.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        """
        Ensure that only one instance of the Logger class is created.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            Logger: The singleton instance of the Logger class.
        """
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_file=None, verbose=False):
        """
        Initialize the Logger instance.

        This method sets up the logger with a file handler and a console handler,
        and configures the log level based on the verbose flag.

        Args:
            log_file (str, optional): The name of the log file. If not provided, a timestamped log file name is used.
            verbose (bool): A flag to set the log level to DEBUG if True, or INFO if False. Defaults to False.
        """

        if self._initialized:
            return
        self._initialized = True

        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        if log_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(log_dir, f"app_{timestamp}.log")
        else:
            log_file = os.path.join(log_dir, log_file)

        self.logger = logging.getLogger("AppLogger")
        self.logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        # Check if handlers already exist
        if not self.logger.handlers:
            # Create file handler
            fh = logging.FileHandler(log_file)
            fh.setLevel(logging.DEBUG if verbose else logging.INFO)

            # Create console handler
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG if verbose else logging.INFO)

            # Create formatter and add it to the handlers
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)

            # Add the handlers to the logger
            self.logger.addHandler(fh)
            self.logger.addHandler(ch)

    def info(self, message):
        """
        Log an info-level message.

        Args:
            message (str): The message to log.
        """
        self.logger.info(message)

    def debug(self, message):
        """
        Log a debug-level message.

        Args:
            message (str): The message to log.
        """
        self.logger.debug(message)

    def error(self, message):
        """
        Log an error-level message.

        Args:
            message (str): The message to log.
        """
        self.logger.error(message)
