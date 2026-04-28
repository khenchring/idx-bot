import logging
import sys
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG:    Fore.CYAN,
        logging.INFO:     Fore.WHITE,
        logging.WARNING:  Fore.YELLOW,
        logging.ERROR:    Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }
    LABELS = {
        logging.DEBUG: "DBG", logging.INFO: "INF",
        logging.WARNING: "WRN", logging.ERROR: "ERR", logging.CRITICAL: "CRT",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        label = self.LABELS.get(record.levelno, "LOG")
        ts  = datetime.now().strftime("%H:%M:%S")
        msg = record.getMessage()

        for tag, col in [("[BUY]", Fore.GREEN), ("[SELL]", Fore.RED),
                         ("[HOLD]", Fore.CYAN), ("[AI]", Fore.MAGENTA),
                         ("[TRADE]", Fore.GREEN), ("[RISK]", Fore.YELLOW),
                         ("[SL]", Fore.RED + Style.BRIGHT), ("[TP]", Fore.GREEN + Style.BRIGHT)]:
            msg = msg.replace(tag, col + tag + Style.RESET_ALL)

        return f"{Fore.BLUE}{ts}{Style.RESET_ALL} {color}[{label}]{Style.RESET_ALL} {msg}"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(ColorFormatter())
        logger.addHandler(ch)
        fh = logging.FileHandler("trader.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    return logger
