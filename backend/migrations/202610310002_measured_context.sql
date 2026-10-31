ALTER TABLE conversations ADD COLUMN measured_tokens integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN measured_messages integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN measured_digest text NOT NULL DEFAULT '';
