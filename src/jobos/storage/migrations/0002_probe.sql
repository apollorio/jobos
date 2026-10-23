-- Confirmação individual de anúncios fora do escopo da listagem (DEC-018).
ALTER TABLE source_postings ADD COLUMN last_probe_at TEXT;
ALTER TABLE source_postings ADD COLUMN last_probe_result TEXT;
CREATE INDEX idx_postings_probe ON source_postings(source_id, posting_state, last_probe_at);
