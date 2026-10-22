import logging, sys

def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

setup_logger()
logger = logging.getLogger("PaperAgent")