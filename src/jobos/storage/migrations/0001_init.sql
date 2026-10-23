-- JOBOS canonical schema v1. Instantes em UTC ISO-8601; datas só-dia como AAAA-MM-DD com precisão explícita.

CREATE TABLE imports (
    import_id     TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,              -- legacy_sqlite | legacy_portal_json | browser_export
    origin_path   TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL CHECK (status IN ('running','complete','failed')),
    counts_json   TEXT,
    UNIQUE (kind, sha256)
);

CREATE TABLE companies (
    company_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    aliases_json  TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL
);

CREATE TABLE source_registry_versions (
    sha256        TEXT PRIMARY KEY,
    content       TEXT NOT NULL,
    loaded_at     TEXT NOT NULL
);

CREATE TABLE sources (
    source_id     TEXT PRIMARY KEY,
    company_id    TEXT NOT NULL REFERENCES companies(company_id),
    platform      TEXT NOT NULL,
    adapter       TEXT,
    enabled       INTEGER NOT NULL,
    config_json   TEXT NOT NULL,
    registry_sha  TEXT REFERENCES source_registry_versions(sha256),
    updated_at    TEXT NOT NULL
);

CREATE TABLE job_records (
    job_id                   TEXT PRIMARY KEY,           -- UUID interno persistente
    company_id               TEXT REFERENCES companies(company_id),
    company_name             TEXT NOT NULL,
    title                    TEXT NOT NULL,
    location                 TEXT,
    workplace                TEXT,
    listing_state            TEXT NOT NULL DEFAULT 'unknown'
        CHECK (listing_state IN ('active','missing_unconfirmed','closed_confirmed','unknown')),
    talent_pool              INTEGER NOT NULL DEFAULT 0,
    published_at             TEXT,
    published_date_precision TEXT NOT NULL DEFAULT 'unknown'
        CHECK (published_date_precision IN ('timestamp','date_only','relative_estimate','unknown')),
    published_date_source    TEXT,
    published_raw            TEXT,
    first_seen_at            TEXT,
    first_seen_precision     TEXT CHECK (first_seen_precision IN ('timestamp','date_only') OR first_seen_precision IS NULL),
    first_seen_source        TEXT,
    last_seen_at             TEXT,
    imported_at              TEXT,
    content_changed_at       TEXT,
    current_version_id       TEXT,
    origin                   TEXT NOT NULL,               -- observed | legacy_sqlite | legacy_portal_json | fixture
    is_baseline              INTEGER NOT NULL DEFAULT 0,
    is_fixture               INTEGER NOT NULL DEFAULT 0,
    closed_at                TEXT,
    close_reason             TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);
CREATE INDEX idx_job_records_state ON job_records(listing_state);
CREATE INDEX idx_job_records_company ON job_records(company_id);

CREATE TABLE source_postings (
    posting_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            TEXT NOT NULL REFERENCES job_records(job_id),
    source_id         TEXT NOT NULL,
    platform          TEXT NOT NULL,
    tenant            TEXT NOT NULL DEFAULT '',
    external_id       TEXT,
    canonical_url     TEXT,
    url               TEXT,
    posting_state     TEXT NOT NULL DEFAULT 'unknown'
        CHECK (posting_state IN ('active','missing_unconfirmed','closed_confirmed','unknown')),
    first_seen_at     TEXT,
    last_seen_at      TEXT,
    last_run_id       TEXT,
    last_scope_id     TEXT,
    missing_count     INTEGER NOT NULL DEFAULT 0,
    missing_since     TEXT,
    last_missing_run  TEXT,
    detail_fetched_at TEXT,
    listing_signature TEXT,
    origin            TEXT NOT NULL,
    is_fixture        INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX ux_postings_external ON source_postings(platform, tenant, external_id) WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX ux_postings_url ON source_postings(platform, canonical_url) WHERE external_id IS NULL AND canonical_url IS NOT NULL;
CREATE INDEX idx_postings_job ON source_postings(job_id);
CREATE INDEX idx_postings_source ON source_postings(source_id, posting_state);

CREATE TABLE job_versions (
    version_id            TEXT PRIMARY KEY,
    job_id                TEXT NOT NULL REFERENCES job_records(job_id),
    content_hash          TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    observed_at           TEXT NOT NULL,
    run_id                TEXT,
    source_id             TEXT,
    origin                TEXT NOT NULL,
    title                 TEXT NOT NULL,
    location              TEXT,
    workplace             TEXT,
    salary                TEXT,
    department            TEXT,
    description           TEXT,
    description_status    TEXT NOT NULL CHECK (description_status IN ('full','partial','missing','truncated')),
    description_length    INTEGER NOT NULL DEFAULT 0,
    original_length       INTEGER,
    truncation_note       TEXT,
    payload_json          TEXT,
    UNIQUE (job_id, content_hash)
);

CREATE TABLE job_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES job_records(job_id),
    kind            TEXT NOT NULL,
    occurred_at     TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    origin          TEXT NOT NULL,
    run_id          TEXT,
    alertable       INTEGER NOT NULL DEFAULT 0,
    payload_json    TEXT,
    dedupe_key      TEXT UNIQUE
);
CREATE INDEX idx_job_events_job ON job_events(job_id, occurred_at);
CREATE INDEX idx_job_events_run ON job_events(run_id);

CREATE TABLE job_relations (
    a_job_id     TEXT NOT NULL REFERENCES job_records(job_id),
    b_job_id     TEXT NOT NULL REFERENCES job_records(job_id),
    kind         TEXT NOT NULL CHECK (kind IN ('possible_repost','possible_duplicate')),
    reason       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','confirmed','rejected')),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (a_job_id, b_job_id, kind)
);

CREATE TABLE legacy_id_map (
    origin            TEXT NOT NULL,
    legacy_id         TEXT NOT NULL,
    canonical_job_id  TEXT NOT NULL REFERENCES job_records(job_id),
    rule              TEXT NOT NULL,
    import_id         TEXT NOT NULL REFERENCES imports(import_id),
    PRIMARY KEY (origin, legacy_id)
);

CREATE TABLE legacy_payloads (
    origin        TEXT NOT NULL,
    legacy_id     TEXT NOT NULL,
    import_id     TEXT NOT NULL REFERENCES imports(import_id),
    payload_json  TEXT NOT NULL,
    PRIMARY KEY (origin, legacy_id)
);

CREATE TABLE legacy_events (
    origin           TEXT NOT NULL,
    legacy_event_id  INTEGER NOT NULL,
    legacy_job_id    TEXT,
    job_id           TEXT REFERENCES job_records(job_id),
    ts               TEXT,
    kind             TEXT,
    detail           TEXT,
    import_id        TEXT NOT NULL REFERENCES imports(import_id),
    PRIMARY KEY (origin, legacy_event_id)
);

CREATE TABLE legacy_runs (
    origin         TEXT NOT NULL,
    legacy_run_id  INTEGER NOT NULL,
    ts             TEXT,
    source         TEXT,
    fetched        INTEGER,
    new_jobs       INTEGER,
    errors         TEXT,
    import_id      TEXT NOT NULL REFERENCES imports(import_id),
    PRIMARY KEY (origin, legacy_run_id)
);

CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    trigger       TEXT NOT NULL,                -- manual | scheduler | api | test
    mode          TEXT NOT NULL,                -- normal | dry_run | fixtures
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    stage         TEXT,
    status        TEXT NOT NULL CHECK (status IN ('running','complete','partial','failed','interrupted','skipped_overlap')),
    exit_code     INTEGER,
    counts_json   TEXT,
    error         TEXT,
    pid           INTEGER
);

CREATE TABLE source_runs (
    run_id             TEXT NOT NULL REFERENCES runs(run_id),
    source_id          TEXT NOT NULL,
    adapter            TEXT,
    adapter_version    TEXT,
    status             TEXT NOT NULL CHECK (status IN ('complete','partial','failed','blocked','unconfigured','skipped')),
    complete           INTEGER NOT NULL,
    coverage_kind      TEXT,
    scope_id           TEXT,
    can_infer_absence  INTEGER NOT NULL DEFAULT 0,
    is_baseline        INTEGER NOT NULL DEFAULT 0,
    absence_applied    INTEGER NOT NULL DEFAULT 0,
    pages_expected     INTEGER,
    pages_received     INTEGER,
    raw_count          INTEGER NOT NULL DEFAULT 0,
    normalized_count   INTEGER NOT NULL DEFAULT 0,
    new_count          INTEGER NOT NULL DEFAULT 0,
    changed_count      INTEGER NOT NULL DEFAULT 0,
    missing_count      INTEGER NOT NULL DEFAULT 0,
    closed_count       INTEGER NOT NULL DEFAULT 0,
    details_fetched    INTEGER NOT NULL DEFAULT 0,
    error_code         TEXT,
    error_message      TEXT,
    warnings_json      TEXT,
    started_at         TEXT,
    finished_at        TEXT,
    PRIMARY KEY (run_id, source_id)
);
CREATE INDEX idx_source_runs_source ON source_runs(source_id, finished_at);

CREATE TABLE profile_versions (
    profile_id    TEXT PRIMARY KEY,               -- sha256 do conteúdo
    origin        TEXT NOT NULL,
    path          TEXT NOT NULL,
    received_at   TEXT NOT NULL,
    valid         INTEGER NOT NULL,
    error         TEXT,
    content       TEXT,
    is_active     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE analyses (
    analysis_id     TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES job_records(job_id),
    job_version_id  TEXT NOT NULL REFERENCES job_versions(version_id),
    profile_id      TEXT NOT NULL REFERENCES profile_versions(profile_id),
    policy_version  TEXT NOT NULL,
    method          TEXT NOT NULL,
    decision        TEXT NOT NULL,
    fit_score       REAL,
    coverage        REAL NOT NULL,
    confidence      TEXT NOT NULL,
    priority        REAL,
    preference_json TEXT,
    result_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (job_version_id, profile_id, policy_version, method)
);
CREATE INDEX idx_analyses_job ON analyses(job_id, created_at);

CREATE TABLE requirements (
    requirement_id     TEXT PRIMARY KEY,
    analysis_id        TEXT NOT NULL REFERENCES analyses(analysis_id),
    ord                INTEGER NOT NULL,
    text               TEXT NOT NULL,
    category           TEXT NOT NULL,
    importance         TEXT NOT NULL CHECK (importance IN ('mandatory','desirable','ambiguous')),
    requirement_source TEXT,
    status             TEXT NOT NULL CHECK (status IN ('met','partial','gap','unknown')),
    evidence_json      TEXT NOT NULL,
    explanation        TEXT NOT NULL
);

CREATE TABLE applications (
    application_id    TEXT PRIMARY KEY,
    job_id            TEXT NOT NULL UNIQUE REFERENCES job_records(job_id),
    prep_state        TEXT NOT NULL CHECK (prep_state IN ('discovered','shortlisted','cv_draft','cv_ready','awaiting_review',
                        'submission_unknown','submitted_manual','submitted_verified','legacy_needs_review','dismissed')),
    selection_stage   TEXT NOT NULL DEFAULT 'none' CHECK (selection_stage IN ('none','screening','test','interview','offer',
                        'rejected','withdrawn','hired')),
    provenance        TEXT,                        -- user_asserted | platform_confirmation | legacy_import | system
    submitted_at      TEXT,
    submitted_precision TEXT,
    legacy_status     TEXT,
    legacy_source     TEXT,
    legacy_date       TEXT,
    legacy_hint       TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE application_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  TEXT NOT NULL REFERENCES applications(application_id),
    axis            TEXT NOT NULL CHECK (axis IN ('prep','stage','note')),
    from_state      TEXT,
    to_state        TEXT,
    occurred_at     TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    origin          TEXT NOT NULL,
    reason          TEXT,
    proof           TEXT,
    payload_json    TEXT,
    dedupe_key      TEXT UNIQUE
);
CREATE INDEX idx_application_events_app ON application_events(application_id, occurred_at);

CREATE TABLE artifacts (
    artifact_id     TEXT PRIMARY KEY,
    job_id          TEXT REFERENCES job_records(job_id),
    application_id  TEXT REFERENCES applications(application_id),
    rel_path        TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    meta_json       TEXT
);

CREATE TABLE notification_outbox (
    notification_id        TEXT PRIMARY KEY,
    idempotency_key        TEXT NOT NULL UNIQUE,
    channel                TEXT NOT NULL,
    recipient_ref          TEXT,
    subject                TEXT NOT NULL,
    payload_ref            TEXT,
    body_text              TEXT NOT NULL,
    body_html              TEXT,
    message_id             TEXT NOT NULL,
    run_id                 TEXT,
    created_at             TEXT NOT NULL,
    attempts               INTEGER NOT NULL DEFAULT 0,
    next_attempt_at        TEXT,
    status                 TEXT NOT NULL CHECK (status IN ('draft','queued','sending','accepted','failed_transient',
                             'failed_permanent','unknown','cancelled')),
    last_error_code        TEXT,
    last_error             TEXT,
    provider_message_id    TEXT,
    smtp_accepted_at       TEXT,
    delivery_confirmed_at  TEXT,
    updated_at             TEXT NOT NULL
);

CREATE TABLE work_items (
    item_id           TEXT PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN ('cycle','collect_source','analyze_job')),
    target            TEXT,
    status            TEXT NOT NULL CHECK (status IN ('queued','leased','done','failed','cancelled')),
    dedupe_key        TEXT,
    origin            TEXT NOT NULL,
    lease_owner       TEXT,
    lease_expires_at  TEXT,
    attempts          INTEGER NOT NULL DEFAULT 0,
    result_json       TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_work_items_open ON work_items(dedupe_key) WHERE status IN ('queued','leased');
