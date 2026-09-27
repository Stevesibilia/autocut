## Context

`cache_key` (`autocut/core/cachekey.py`) hashes `st_size`, `st_mtime_ns` and the first and last MiB. `ingest_file` (`autocut/core/ingest.py:146`) uses the same key as `SourceFile.id`, and segment ids derive from it. Re-analysis writes segments by id (`autocut/core/analyze.py:368`) and never removes old ones.

## Decisions

**1. Keep the key.** Dropping the mtime would cost a one-time re-analysis of every cached file. It would also give existing projects new file and segment ids, which would orphan the keep and reject decisions stored on the old segments. ADR 6 already records the trade: a copy keeps its entry when size and mtime survive, which holds for `rsync -a`, Finder copies and reading over a share. Rejected: dropping the mtime everywhere, as the review suggested. Also rejected: a separate content-only key for the cache alone. It avoids the id churn but still re-analyzes everything, for a case the user's workflow rarely hits.

**2. Say it where people read it.** The `cachekey.py` docstring, SPEC §9 and the `footage-ingest` requirement all name which copies keep their entry. A test pins the limit, so a future change to the key is a visible decision.

**3. Release on demand only.** `release.yml` triggers on `workflow_dispatch` instead of `push: tags`, with a comment that tags come back when `make dmg` builds a bundle (M6, ADR 7). Rejected: building a wheel as a stopgap artifact. Nobody installs AutoCut from a wheel, and that would be new release scope.

## Not touched

`cache_key`'s code, ADR 6 (still accurate), `ci.yml`, the `Makefile`.

## Risks / Trade-offs

A user who copies footage with plain `cp` pays a full re-analysis. That is documented rather than prevented.

## Migration Plan

None.

## Open Questions

None.
