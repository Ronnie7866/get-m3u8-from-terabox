import logging
import sys

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Clear any existing handlers if the logger has been initialized before
    if logger.handlers:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    # Console handler for stdout only
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # Colored formatter for console output
    class ColoredFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[94m',
            'INFO': '\033[92m',
            'WARNING': '\033[93m',
            'ERROR': '\033[91m',
            'CRITICAL': '\033[1;31m'
        }
        RESET = '\033[0m'

        def format(self, record):
            log_message = super().format(record)
            color = self.COLORS.get(record.levelname, '')
            return f"{color}{log_message}{self.RESET}"

    # Use a more robust encoding
    formatter = ColoredFormatter(
        '%(asctime)s | %(name)s | %(levelname)8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Assign formatter to handler
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)

    return logger