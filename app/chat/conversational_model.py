"""Load the complete quantized local GGUF model; shared across the chat agent."""
import logging
import os
from functools import lru_cache
from threading import Lock

log = logging.getLogger(__name__)
lock = Lock()
def _integer_setting(name, default, minimum, maximum):
    value = int(os.getenv(name, str(default)))
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


@lru_cache(maxsize=1)
def model(path):
    from llama_cpp import Llama
    engine = Llama(
        model_path=path,
        n_ctx=_integer_setting("GGUF_CONTEXT_TOKENS", 2048, 512, 4096),
        n_threads=_integer_setting("GGUF_THREADS", 1, 1, 4),
        n_threads_batch=_integer_setting("GGUF_THREADS", 1, 1, 4),
        n_batch=32,
        n_gpu_layers=0,
        use_mmap=True,
        chat_format="chatml",
        verbose=False,
    )
    log.info("Loaded local GGUF chat model on CPU")
    return engine


