## Purpose

Cloud providers give AutoCut access to hosted models under strict rules: opt-out, key handling that never touches config files, bounded retries, cached responses and a minimal payload.

## ADDED Requirements

### Requirement: Key lookup and storage

The system SHALL read the API key from the `OPENROUTER_API_KEY` environment variable, then from the OS keychain entry `autocut/openrouter`, and SHALL treat the absence of both as cloud unavailable. The key MUST never be written to `autocut.toml`, the manifest, the cache or any log. `autocut key set` SHALL store a key in the keychain and `autocut key clear` remove it.

#### Scenario: Environment wins

- **WHEN** both the environment variable and a keychain entry exist
- **THEN** the environment value is used

#### Scenario: No key

- **WHEN** neither source has a key
- **THEN** cloud features are skipped with one line saying so and no request is made

### Requirement: Opt-out gating

Cloud calls SHALL happen only when `providers.cloud` is true, a key is available, and `--no-cloud` was not passed. Any of the three MUST disable every cloud call in that run.

#### Scenario: Flag overrides config

- **WHEN** `providers.cloud` is true and `--no-cloud` is passed
- **THEN** no request is made and the run records `cloud_model: none`

### Requirement: Bounded retries and concurrency

Requests SHALL run with at most `providers.max_concurrency` in flight, retry on 429 and 5xx with exponential backoff up to `providers.max_retries` times, and then record the failure on the segment and continue. The run MUST NOT retry indefinitely and MUST stop issuing new requests after `providers.max_failures` consecutive failures.

#### Scenario: Persistent outage

- **WHEN** the provider returns 503 for every request
- **THEN** the run stops after the configured consecutive failures, records the error once per attempted segment and completes without exception

### Requirement: Data minimization

Each vision request SHALL contain only the segment's 320 px thumbnail as JPEG and the fixed prompt. File names, paths, GPS, timestamps, telemetry and any other manifest field MUST NOT be sent.

#### Scenario: Payload audit

- **WHEN** a request body is captured in a test
- **THEN** it contains the image, the prompt and the model id, and no other segment field

### Requirement: Response cache

Responses SHALL be cached in the analysis cache keyed by segment embedding reference, model id and `providers.prompt_version`, and a cached response MUST be used instead of a new request.

#### Scenario: Second run free

- **WHEN** `autocut describe` runs twice with the same model and prompt version
- **THEN** the second run makes no request

### Requirement: Cost accounting

The run SHALL record the number of requests and the cost in USD computed from the usage fields the provider returns, and the CLI SHALL print both at the end.

#### Scenario: Cost line

- **WHEN** 60 requests complete
- **THEN** the CLI prints the request count and the total cost with four decimals
