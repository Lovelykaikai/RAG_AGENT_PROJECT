from utils.config_handler import prompt_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


def _get_prompt_path(config_keys: tuple[str, ...], loader_name: str) -> str:
    for config_key in config_keys:
        prompt_path = prompt_conf.get(config_key)
        if prompt_path:
            return get_abs_path(prompt_path)

    logger.error(f"[{loader_name}] missing prompt path config: {config_keys}")
    raise KeyError(config_keys[0])


def _load_prompt(config_keys: tuple[str, ...], loader_name: str) -> str:
    prompt_path = _get_prompt_path(config_keys, loader_name)

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"[{loader_name}] failed to load prompt from {prompt_path}: {str(e)}")
        raise


def load_system_prompt() -> str:
    return _load_prompt(("main_prompt_path",), "load_system_prompt")


def load_rag_prompt() -> str:
    return _load_prompt(("rag_summarize_prompt_path",), "load_rag_prompt")


def load_report_prompt() -> str:
    return _load_prompt(("report_prompt_path",), "load_report_prompt")
