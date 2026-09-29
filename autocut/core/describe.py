"""Cloud descriptions per segment: specific tags, a caption and an aesthetic judgment.

Local zero-shot tags say `beach` where a hosted vision model says `snorkeling over a
reef`, and the M4 soundtrack prompt needs the second kind. ADR 4 allows the call behind
a key, an opt-out and a local baseline, and asks for three things this module owns.

**One request per segment, then never again.** Answers are cached under the analysis
cache keyed by the segment's embedding reference, the model id and the prompt version,
so a project costs cents once and nothing on every run after it. Changing the prompt
means bumping ``providers.prompt_version``, which invalidates the cache on purpose.

**Failures never break a run and never loop.** A request retries inside the provider and
then records its error on the segment; ``providers.max_failures`` consecutive failures
stop the step from issuing anything more, so an outage costs a bounded number of
requests rather than one per segment forever.

**Only the picture leaves the machine.** The payload is built in
:mod:`autocut.core.providers.openrouter` and carries the thumbnail and the prompt.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from autocut.core.aesthetic import AESTHETIC_RANGE
from autocut.core.cache import cache_dir, read_entry, thumb_index
from autocut.core.config import AutocutConfig, DescribeScope
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.manifest import Manifest, Metrics, Segment, Tag
from autocut.core.providers import Description, ProviderError, VisionProvider
from autocut.core.providers.openrouter import bounded_int
from autocut.core.score import rescore

DESCRIPTIONS_DIRNAME = "descriptions"
MAX_TAGS = 5
MAX_CAPTION_WORDS = 20
#: An aesthetic is clamped into range, but a stored one has to be finite first. A cache
#: file is written by this module and read back later, and a hand-edited one is a file
#: like any other.
MAX_STORED_AESTHETIC = 1_000_000

CORRECTION = (
    "That was not a JSON object. Answer again with only the JSON object and the three "
    "keys tags, caption and aesthetic."
)


@dataclass(slots=True)
class DescribeResult:
    """What one describe pass did, for the run record and the CLI."""

    model: str = "none"
    scope: DescribeScope = "candidates"
    in_scope: int = 0
    described: int = 0
    from_cache: int = 0
    requests: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    aborted: bool = False
    skipped_reason: str | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def descriptions_dir(config: AutocutConfig) -> Path:
    """Where cached answers live, one directory per model and prompt version."""
    model = _safe(config.providers.vision_model)
    version = f"v{config.providers.prompt_version}"
    return cache_dir(config) / DESCRIPTIONS_DIRNAME / model / version


def _safe(text: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in text)


def cache_path(config: AutocutConfig, key: str) -> Path:
    """The file an answer for ``key`` is stored in. A segment key carries a colon."""
    return descriptions_dir(config) / f"{key.replace(':', '_')}.json"


def description_key(segment: Segment) -> str:
    """What an answer is keyed on.

    The embedding reference, because it names the cached frame the request was made
    from: a re-analysis that moves the shot boundaries produces different references
    and invalidates the answers naturally. A project without embeddings falls back to
    the segment id, which is the same string in every case except a clamped index.
    """
    return segment.embedding_ref or segment.id


def read_cached(config: AutocutConfig, key: str) -> Description | None:
    """A stored answer, or ``None`` when there is none or it cannot be read."""
    path = cache_path(config, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return Description(
        tags=[str(tag) for tag in payload.get("tags", [])],
        caption=payload.get("caption"),
        aesthetic=payload.get("aesthetic"),
        model=str(payload.get("model", "")),
        cost_usd=float(payload.get("cost_usd", 0.0)),
    )


def write_cached(config: AutocutConfig, key: str, description: Description) -> None:
    """Store an answer. The raw text is deliberately not kept: it is not needed again."""
    path = cache_path(config, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {
                "tags": description.tags,
                "caption": description.caption,
                "aesthetic": description.aesthetic,
                "model": description.model,
                "cost_usd": description.cost_usd,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def validate(description: Description) -> tuple[Description, str | None]:
    """The answer with its fields brought into range, or a reason it cannot be used.

    Out of range values are corrected rather than rejected: a caption of thirty words
    and an aesthetic of 11 are answers to the right question, and throwing them away
    would spend a second request to ask it again. An answer with none of the three
    fields is a different matter and earns the one correction retry.
    """
    if not description.parsed:
        return description, "the answer was not a JSON object"
    tags = [tag.strip().lower() for tag in description.tags if tag and tag.strip()]
    caption = description.caption
    if caption is not None:
        words = caption.strip().split()
        caption = " ".join(words[:MAX_CAPTION_WORDS]).rstrip(".").lower() or None
    aesthetic = description.aesthetic
    if aesthetic is not None:
        # Bounded at the transport, clamped to the asked-for range here. A value that
        # survived neither guard reads as no aesthetic rather than as an exception.
        finite = bounded_int(aesthetic, MAX_STORED_AESTHETIC)
        aesthetic = (
            None if finite is None else max(AESTHETIC_RANGE[0], min(AESTHETIC_RANGE[1], finite))
        )
    if not tags and caption is None and aesthetic is None:
        return description, "the answer carried none of the three fields"
    return (
        Description(
            tags=tags[:MAX_TAGS],
            caption=caption,
            aesthetic=aesthetic,
            model=description.model,
            cost_usd=description.cost_usd,
            prompt_tokens=description.prompt_tokens,
            completion_tokens=description.completion_tokens,
            raw=description.raw,
        ),
        None,
    )


def apply_description(segment: Segment, description: Description) -> None:
    """Put an answer on a segment, leaving its local tags where they are."""
    local = [tag for tag in segment.tags if tag.source != "cloud"]
    cloud = [
        Tag(label=label, confidence=1.0, source="cloud", group=None, primary=True)
        for label in description.tags
    ]
    # Cloud first, in the order the model returned them: that order is the model's own
    # answer to "what is this", and the dominant tag reads the first of them.
    segment.tags = cloud + local
    if description.caption is not None:
        segment.caption = description.caption
    if description.aesthetic is not None:
        metrics = segment.metrics
        if metrics is None:
            metrics = Metrics(
                sharpness=0.0, exposure_clipped=0.0, motion=0.0, stability=0.0, colorfulness=0.0
            )
            segment.metrics = metrics
        # Scaled to 0 to 1 so it normalizes beside the other metrics rather than
        # swamping them with a number ten times their size.
        metrics.aesthetic = description.aesthetic / AESTHETIC_RANGE[1]
        metrics.aesthetic_source = "cloud"


def segments_in_scope(manifest: Manifest, scope: DescribeScope) -> list[Segment]:
    """The segments a run describes, in a stable order."""
    if scope == "selected":
        chosen = [s for s in manifest.segments.values() if s.outcome == "selected"]
        return sorted(chosen, key=lambda s: (s.order or 0, s.id))
    wanted = {"candidate", "selected"}
    return sorted(
        (s for s in manifest.segments.values() if s.outcome in wanted), key=lambda s: s.id
    )


def thumbnail_bytes(segment: Segment, config: AutocutConfig) -> bytes | None:
    """The 320 px JPEG for a segment, from the report thumbnail or from the cache.

    The written thumbnail is preferred because it is the exact file the user can look at
    beside the answer. A project whose thumbnails were deleted re-encodes from the
    cached frame rather than failing.
    """
    path = segment.thumbnail
    if path is not None and Path(path).exists():
        try:
            return Path(path).read_bytes()
        except OSError:
            pass
    entry = read_entry(segment.file_id, config)
    if entry is None or entry.thumb_frames is None or entry.thumb_frames.size == 0:
        return None
    index = thumb_index(segment.id, int(entry.thumb_frames.shape[0]))
    if index < 0:
        return None
    import io

    import numpy as np
    from PIL import Image

    buffer = io.BytesIO()
    frame = np.ascontiguousarray(entry.thumb_frames[index])
    Image.fromarray(frame, mode="RGB").save(
        buffer, format="JPEG", quality=config.analysis.thumbnail_quality
    )
    return buffer.getvalue()


def describe_project(
    manifest: Manifest,
    config: AutocutConfig,
    provider: VisionProvider | None = None,
    progress: ProgressCallback = null_progress,
    labels: list[str] | None = None,
) -> DescribeResult:
    """Describe every segment in scope that has no cached answer.

    Cached answers are applied without a request, so a second run over the same project
    costs nothing and still fills in everything the first one learned.
    """
    scope = config.providers.describe_scope
    result = DescribeResult(scope=scope)
    if provider is None:
        return DescribeResult(scope=scope, skipped_reason="no provider was given")
    result.model = provider.model

    in_scope = segments_in_scope(manifest, scope)
    result.in_scope = len(in_scope)
    if not in_scope:
        return result

    wanted = labels if labels is not None else _configured_labels(config)
    pending: list[Segment] = []
    for segment in in_scope:
        cached = read_cached(config, description_key(segment))
        if cached is None:
            pending.append(segment)
            continue
        apply_description(segment, cached)
        segment.description_error = None
        result.from_cache += 1
        result.described += 1

    if pending:
        _run_requests(pending, config, provider, wanted, progress, result)
    _rescore(manifest, config)
    return result


def _configured_labels(config: AutocutConfig) -> list[str]:
    """The local label set, offered to the model so its tags line up with ours."""
    return [label.label for group in config.tags.groups for label in group.labels]


def _run_requests(
    pending: list[Segment],
    config: AutocutConfig,
    provider: VisionProvider,
    labels: list[str],
    progress: ProgressCallback,
    result: DescribeResult,
) -> None:
    """Describe the segments with no cached answer, bounded in flight and in failures.

    Work is submitted a batch at a time rather than all at once, so the consecutive
    failure count can stop the step between batches. That is what makes an outage cost
    about ``max_failures`` requests instead of one per segment; requests already in
    flight are allowed to finish and counted.
    """
    workers = max(config.providers.max_concurrency, 1)
    limit = max(config.providers.max_failures, 1)
    consecutive = 0
    done = 0
    total = len(pending)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, total, workers):
            if consecutive >= limit:
                result.aborted = True
                break
            batch = pending[start : start + workers]
            futures = [
                pool.submit(_describe_one, segment, config, provider, labels) for segment in batch
            ]
            for segment, future in zip(batch, futures, strict=True):
                outcome, attempts, wasted = future.result()
                # Requests and cost are what the transport actually did, so a retry
                # storm and an answer thrown away for being malformed both show up.
                result.requests += attempts
                result.cost_usd += wasted
                done += 1
                if isinstance(outcome, Description):
                    apply_description(segment, outcome)
                    segment.description_error = None
                    write_cached(config, description_key(segment), outcome)
                    result.described += 1
                    result.cost_usd += outcome.cost_usd
                    consecutive = 0
                else:
                    segment.description_error = outcome.message
                    result.failed += 1
                    result.errors.append((segment.id, outcome.message))
                    consecutive += 1
                progress(
                    ProgressEvent(stage="describe", current=done, total=total, message=segment.id)
                )

    if result.aborted:
        # Every segment the step never reached says so, so the report does not show a
        # clip as simply undescribed when the run gave up before asking about it.
        for segment in pending[done:]:
            segment.description_error = "describe stopped after repeated failures"
            result.failed += 1


def _describe_one(
    segment: Segment,
    config: AutocutConfig,
    provider: VisionProvider,
    labels: list[str],
) -> tuple[Description | ProviderError, int, float]:
    """One segment's answer, the HTTP attempts it took, and the cost of any answer
    that was paid for and then discarded. Runs in a pool thread.

    The attempt count comes from the provider rather than from the number of calls made
    here, because one call can be several requests once retries are involved.
    """
    jpeg = thumbnail_bytes(segment, config)
    if jpeg is None:
        return ProviderError(message="no thumbnail to describe", retryable=False), 0, 0.0

    outcome = provider.describe_frame(jpeg, labels)
    attempts = max(outcome.attempts, 1)
    if isinstance(outcome, ProviderError):
        return outcome, attempts, 0.0
    validated, reason = validate(outcome)
    if reason is None:
        return validated, attempts, 0.0

    # One correction, then it is a failure. The first answer was billed even though it
    # is thrown away, so its cost travels back separately.
    wasted = outcome.cost_usd
    retry = provider.describe_frame(jpeg, labels, CORRECTION)
    attempts += max(retry.attempts, 1)
    if isinstance(retry, ProviderError):
        return retry, attempts, wasted
    corrected, retry_reason = validate(retry)
    if retry_reason is None:
        return corrected, attempts, wasted
    return (
        ProviderError(message=f"invalid answer twice: {retry_reason}", retryable=False),
        attempts,
        wasted + retry.cost_usd,
    )


def _rescore(manifest: Manifest, config: AutocutConfig) -> None:
    """Score the segments again when the aesthetic now carries weight.

    Scoring happens during analysis, before any description exists, so a project whose
    aesthetic weight is above zero has stale scores until this runs. Selection reads
    scores and does not compute them, which is why this belongs here rather than there.
    """
    if config.weights.aesthetic <= 0:
        return
    rescore(manifest, config.weights)
