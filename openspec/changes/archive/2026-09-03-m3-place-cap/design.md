## Context

Selection already caps per file and per visual cluster and penalizes by combined similarity, where the spatial signal maps GPS distance onto 0 to 1 within 200 m. On the Sardinia edit that was not enough: five drone files at one spot passed because the hash split them into three clusters and the slot count was generous. GPS exists for every drone and phone file (format tag) and per second in drone telemetry; action cam files have none.

## Goals / Non-Goals

**Goals:**

- A cap the user can state in one sentence: "at most three clips from one visit to one place".
- No model, milliseconds, explainable on the card.
- A slot count that scales with the folder without a new flag.

**Non-Goals:**

- Naming places (reverse geocoding, M4 soundtrack).
- Grouping the edit by place instead of chronology (M3+, GPS chapters).
- Handling action cam without GPS; embeddings cover those.

## Decisions

**Place radius 150 m, single linkage.** Smaller than the 200 m spatial signal radius on purpose: the signal is a soft penalty, the cap is hard. Single linkage matches how a walk along a beach produces a chain of positions. Alternative, grid cells, rejected because a cell edge splits a place arbitrarily.

**Visits by time gap, default two hours.** Coming back to the same beach the next day is a new visit and deserves its own clips. Two hours separates morning from afternoon. Configurable.

**Position source.** Telemetry sample nearest the window center when available, else the file tag. A drone file's tag is the takeoff point; the shot may be 300 m away. Phones have only the tag.

**Cap default 3.** Two would have kept only the two best of the five and the user asked for fewer, not for one. Three keeps a wide, a medium and a detail from one spot, which is how a montage covers a location.

**Eligibility, not penalty.** Same mechanism as the cluster cap: a candidate is ineligible while its visit has `max_clips_per_place` selected clips and other eligible candidates exist. Lifted in the same last-resort pass as the temporal gap and the tag share cap. `held_by` records the winners for the card.

**Candidate share ceiling 0.5.** Bounds `max_clips` to half the eligible candidates unless `--max-clips` is explicit. On 60 candidates that gives 30; on the 150 file vacation the spec targets, about 130 candidates give 65 and `max_clips` 40 still binds. The ceiling is reported in the summary line so the user sees why fewer clips came out.

**Order in `select`.** Places and visits are computed once from GPS and time before the greedy loop; the cap is checked inside `_eligible`. Durations and window placement follow, unchanged.

## Risks / Trade-offs

- [Drone tag is takeoff point when telemetry lacks GPS] → telemetry preferred; documented.
- [Two hour gap merges a lunch break into one visit] → configurable; the user's feedback was about eleven minutes, not hours.
- [Ceiling surprises a user expecting 40] → printed in the summary and the report header; `--max-clips` overrides.
- [Chain linkage merges two coves connected by a walked path] → radius is small and the cap is per visit, so the damage is one extra clip at most.
