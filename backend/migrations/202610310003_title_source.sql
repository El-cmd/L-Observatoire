ALTER TABLE conversations ADD COLUMN title_source text NOT NULL DEFAULT 'question'
    CHECK (title_source IN ('question', 'generated', 'manual'));
