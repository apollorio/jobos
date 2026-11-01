CREATE TABLE requirements_v3 (
    requirement_id     TEXT PRIMARY KEY,
    analysis_id        TEXT NOT NULL REFERENCES analyses(analysis_id),
    ord                INTEGER NOT NULL,
    text               TEXT NOT NULL,
    category           TEXT NOT NULL,
    importance         TEXT NOT NULL CHECK (importance IN ('mandatory','desirable','ambiguous','responsibility')),
    requirement_source TEXT,
    status             TEXT NOT NULL CHECK (status IN ('met','partial','gap','unknown')),
    evidence_json      TEXT NOT NULL,
    explanation        TEXT NOT NULL
);
INSERT INTO requirements_v3 SELECT * FROM requirements;
DROP TABLE requirements;
ALTER TABLE requirements_v3 RENAME TO requirements;

