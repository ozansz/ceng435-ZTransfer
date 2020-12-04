import logging

def get_logger(name):
    logger = logging.getLogger(name)
    #logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(user)s - %(req_id)s"
        " - %(external_ctx)s - %(end_user)s - %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch) 

    return logger