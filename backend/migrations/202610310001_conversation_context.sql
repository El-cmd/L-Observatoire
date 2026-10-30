ALTER TABLE conversations ADD COLUMN context_summary text NOT NULL DEFAULT '';
ALTER TABLE conversations ADD COLUMN compacted_through integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN compaction_count integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD CONSTRAINT conversations_compacted_range
    CHECK (compacted_through >= 0 AND compacted_through <= jsonb_array_length(messages));
