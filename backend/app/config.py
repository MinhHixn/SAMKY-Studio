"""
Configuration Management
Loads configuration from .env file in project root directory
"""

import os
from typing import Any
from dotenv import load_dotenv

# Load .env file from project root
# Path: MiroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=False)
else:
    # If no .env in root, try to load environment variables (for production)
    load_dotenv(override=False)


def _env_get(name: str, default: Any = None) -> Any:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default))
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int_or_raw(name: str, default: int):
    value = os.environ.get(name, str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _env_float_or_raw(name: str, default: float):
    value = os.environ.get(name, str(default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


class Config:
    """Flask configuration class"""

    # Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON configuration - disable ASCII escaping to display Chinese directly (not as \uXXXX)
    JSON_AS_ASCII = False

    # LLM configuration (unified OpenAI format)
    LLM_API_KEY = os.environ.get('LLM_API_KEY') or 'sam-local'
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'qwen2.5:32b')
    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY') or LLM_API_KEY
    OPENROUTER_BASE_URL = os.environ.get('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    OPENROUTER_GRAPH_MODEL = os.environ.get('OPENROUTER_GRAPH_MODEL')
    OPENROUTER_BENCHMARK_MODEL = os.environ.get('OPENROUTER_BENCHMARK_MODEL')
    OPENROUTER_EVALUATOR_MODEL = os.environ.get('OPENROUTER_EVALUATOR_MODEL')
    OPENROUTER_HTTP_REFERER = os.environ.get('OPENROUTER_HTTP_REFERER')
    OPENROUTER_X_TITLE = os.environ.get('OPENROUTER_X_TITLE')
    BENCHMARK_MODE = _env_bool('BENCHMARK_MODE', False)
    BENCHMARK_TEMPERATURE = _env_float_or_raw('BENCHMARK_TEMPERATURE', 0.0)
    BENCHMARK_SEED = _env_int_or_raw('BENCHMARK_SEED', 42)
    HEADLESS_MODE = _env_bool('HEADLESS_MODE', False)
    LLM_TIMEOUT_SECONDS = _env_float_or_raw('LLM_TIMEOUT_SECONDS', 600.0)
    LLM_USE_JSON_SCHEMA = _env_bool('LLM_USE_JSON_SCHEMA', True)
    LLM_RETRY_MAX_RETRIES = _env_int_or_raw('LLM_RETRY_MAX_RETRIES', 3)
    LLM_RETRY_INITIAL_DELAY = _env_float_or_raw('LLM_RETRY_INITIAL_DELAY', 1.0)
    LLM_RETRY_MAX_DELAY = _env_float_or_raw('LLM_RETRY_MAX_DELAY', 30.0)
    LLM_RETRY_JITTER_MAX = _env_float_or_raw('LLM_RETRY_JITTER_MAX', 0.0)

    # Neo4j configuration
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'mirofish')

    # Embedding configuration
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'nomic-embed-text')
    EMBEDDING_BASE_URL = _env_get('EMBEDDING_BASE_URL', 'http://localhost:11434')

    # Dual-server support for HPC scalability
    EVALUATOR_LLM_BASE_URL = _env_get('EVALUATOR_LLM_BASE_URL', None)
    GRAPH_LLM_BASE_URL = _env_get('GRAPH_LLM_BASE_URL', None)


    # File upload configuration
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # Text processing configuration
    DEFAULT_CHUNK_SIZE = 500  # Default chunk size
    DEFAULT_CHUNK_OVERLAP = 50  # Default overlap size

    # OASIS simulation configuration
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '60'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS platform available actions configuration
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent configuration
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY not configured (set to any non-empty value, e.g. 'ollama')")
        if not cls.NEO4J_URI:
            errors.append("NEO4J_URI not configured")
        if not cls.NEO4J_PASSWORD:
            errors.append("NEO4J_PASSWORD not configured")
        return errors
