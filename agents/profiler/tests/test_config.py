"""The cache location, including the docker-compose case.

``docker-compose.yml`` gives every service ``CACHE_DIR=/data/cache`` and the
one-off agent run has no writable source folder, so that variable has to be
honoured; ``PROFILER_CACHE_DIR`` still wins when a developer wants it elsewhere.
"""
from agents.profiler.config import PROFILER_DIR, _cache_root


def test_profiler_cache_dir_wins():
    env = {"PROFILER_CACHE_DIR": "/tmp/one", "CACHE_DIR": "/data/cache"}
    assert str(_cache_root(env)) == "/tmp/one"


def test_cache_dir_from_compose_is_used_when_the_profiler_var_is_unset():
    assert str(_cache_root({"CACHE_DIR": "/data/cache"})) == "/data/cache"


def test_default_is_the_folder_next_to_the_code():
    assert _cache_root({}) == PROFILER_DIR / "cache"


def test_empty_values_fall_through_to_the_default():
    assert _cache_root({"PROFILER_CACHE_DIR": "", "CACHE_DIR": ""}) == PROFILER_DIR / "cache"
