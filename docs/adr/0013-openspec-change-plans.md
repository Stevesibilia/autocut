# 13. OpenSpec changes as the plan of record

Date: 2026-09-03 (recorded 2026-09-28)

## Status

Accepted

## Context

AutoCut is built mostly by coding agents. An architect session plans the work and implementer sessions build it. A plan kept in a chat message is lost when the session ends, and a reviewer cannot check code against it. SPEC.md describes the product as a whole, but it has no place for one change's decisions, its rejected alternatives, its tasks, or the requirement text it adds or alters.

OpenSpec was adopted with the first milestone (commit `30a3e30`) and has carried every change since. This record states the practice, which was never written down.

## Decision

Every change to behaviour, and every change to tooling large enough to need decisions, is planned as an OpenSpec change in `openspec/changes/<name>/`. The change holds `proposal.md`, `design.md` with numbered decisions and their reasons, spec deltas under `specs/`, and `tasks.md` grouped into commits. The plan is the first commit on the feature branch and must pass `openspec validate <name> --strict`. After the merge the change is archived into `openspec/changes/archive/`, which folds its deltas into `openspec/specs/`, in a small follow-up pull request.

A change with no behaviour to specify says so in its proposal instead of inventing a requirement. ADRs remain the place for decisions about structure, dependencies and interfaces. A change that makes such a decision also adds an ADR.

## Consequences

An implementer can start from a clean context and a reviewer has something to diff against. `openspec/specs/` becomes the current requirement set, capability by capability.

The practice costs one planning commit per change, one archive pull request per merge, and the discipline of amending the design when the build departs from it. The `openspec` CLI is a development tool on the author's machine, not a project dependency.
