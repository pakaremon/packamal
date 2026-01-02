import logging
import os
import sys
import inspect
from pathlib import Path




def log_function_output(file_level: str, console_level: str, log_filepath: str = None) -> logging.Logger:
    """
    A custom logging to a file or console
    :file_level: logging level e.g., logging.DEBUG, logging.INFO
    :console_level: logging level e.e., logging.DEBG, logging.INFO
    :log_filename: filename of the logfile e.g., 'log_test.log'. The log file will be stored in the
    research_project/logs/
    """
    MIN_LEVEL = logging.DEBUG
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    logger.setLevel(MIN_LEVEL)  # By default, logs all messages

    # Setting logging for console
    logger.propagate = False
    console_logger = logging.StreamHandler(sys.stdout)  # StreamHandler logs to console
    console_logger.setLevel(console_level)
    console_message = logging.Formatter("%(asctime)s - %(lineno)d - %(levelname)-8s $ %(message)s $ {}".format(function_name))
    console_logger.setFormatter(console_message)
    logger.addHandler(console_logger)

    logger.propagate = False
    # Setting logging for file (optional - only if log_filepath is provided and writable)
    if log_filepath is not None:
        try:
            log_file = os.path.abspath(log_filepath)
            log_dir = os.path.dirname(log_file)
            # Only create directory and file handler if we can write to it
            os.makedirs(log_dir, exist_ok=True)
            file_logger = logging.FileHandler(str(log_file))
            file_logger.setLevel(file_level)
            file_message = logging.Formatter("%(asctime)s - %(lineno)d - %(levelname)-8s $ %(message)s $ {}".format(function_name))
            file_logger.setFormatter(file_message)
            logger.addHandler(file_logger)
        except (PermissionError, OSError) as e:
            # If file logging fails (e.g., permission denied), just use console logging
            # This is expected in containerized environments where we log to stdout/stderr
            pass

    return logger