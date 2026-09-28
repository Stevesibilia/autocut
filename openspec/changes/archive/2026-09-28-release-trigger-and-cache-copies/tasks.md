## 1. Release on demand (#72)

- [x] 1.1 `release.yml` triggers on `workflow_dispatch` only, with the reason in a comment.

## 2. Cache copies documented (#71)

- [x] 2.1 `cachekey.py` docstring names the copies that keep their entry and those that do not.
- [x] 2.2 SPEC §9 cache key sentence matches the code: no path in the key, with the copy limit.
- [x] 2.3 `test_copy_without_the_mtime_gets_a_new_key` in `tests/unit/test_cachekey.py`.

## 3. Gates

- [x] 3.1 `make lint`, `pytest tests/unit/test_cachekey.py`, `openspec validate release-trigger-and-cache-copies --strict`.
