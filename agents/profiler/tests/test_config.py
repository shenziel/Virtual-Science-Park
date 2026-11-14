"""The cache location, including the docker-compose case.

``docker-compose.yml`` gives every service ``CACHE_DIR=/data/cache`` and the
one-off agent run has no writable source folder, so that variable has to be
honoured; ``PROFILER_CACHE_DIR`` still wins when a developer wants it elsewhere.
"""
from agents.profiler.config import PROFILER_DIR, _cache_root, _load_env_file


def test_profiler_cache_dir_wins():
    env = {"PROFILER_CACHE_DIR": "/tmp/one", "CACHE_DIR": "/data/cache"}
    assert str(_cache_root(env)) == "/tmp/one"


def test_cache_dir_from_compose_is_used_when_the_profiler_var_is_unset():
    assert str(_cache_root({"CACHE_DIR": "/data/cache"})) == "/data/cache"


def test_default_is_the_folder_next_to_the_code():
    assert _cache_root({}) == PROFILER_DIR / "cache"


def test_empty_values_fall_through_to_the_default():
    assert _cache_root({"PROFILER_CACHE_DIR": "", "CACHE_DIR": ""}) == PROFILER_DIR / "cache"


def test_env_file_loads_profiler_variables_without_overriding_process_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODEL_RUNTIME=api\n"
        "MODEL_NAME=example/model\n"
        "MODEL_API_KEY=file-key\n"
        "CACHE_DIR=/data/cache\n"
        "PROFILER_CACHE_DIR=/data/profiles\n"
        "PROFILER_PAGE_CACHE_DIR=/data/pages\n"
        "PROFILER_USER_AGENT=Profiler/1.0\n"
        "PROFILER_MIN_INTERVAL=0.5\n"
        "PROFILER_TIMEOUT=40\n"
        "CHAT_API_KEY=not-for-profiler\n",
        encoding="utf-8",
    )
    environ = {"MODEL_API_KEY": "process-key"}

    _load_env_file(env_file, environ)

    assert environ == {
        "MODEL_RUNTIME": "api",
        "MODEL_NAME": "example/model",
        "MODEL_API_KEY": "process-key",
        "CACHE_DIR": "/data/cache",
        "PROFILER_CACHE_DIR": "/data/profiles",
        "PROFILER_PAGE_CACHE_DIR": "/data/pages",
        "PROFILER_USER_AGENT": "Profiler/1.0",
        "PROFILER_MIN_INTERVAL": "0.5",
        "PROFILER_TIMEOUT": "40",
    }
