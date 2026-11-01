-- Documents (PDF, Word, text) join images in the library. doc-guard opens them, Qwen lays out
-- PDF pages (or reads scanned ones on their image) once, and the Markdown is kept in `content`.
ALTER TABLE attachments
    DROP CONSTRAINT attachments_kind_check,
    DROP CONSTRAINT attachments_mime_check,
    DROP CONSTRAINT attachments_width_check,
    DROP CONSTRAINT attachments_height_check,
    ADD COLUMN status text NOT NULL DEFAULT 'ready' CHECK (status IN ('reading', 'ready', 'failed')),
    -- Pages done while a PDF is read, then pages read on their image and doubtful readings.
    ADD COLUMN pages integer NOT NULL DEFAULT 0,
    ADD COLUMN progress integer NOT NULL DEFAULT 0,
    ADD COLUMN scanned integer NOT NULL DEFAULT 0,
    ADD COLUMN doubts integer NOT NULL DEFAULT 0,
    ADD COLUMN tokens integer NOT NULL DEFAULT 0,
    ADD COLUMN content text,
    ADD COLUMN error text,
    ADD CONSTRAINT attachments_kind_check CHECK (kind IN ('image', 'document')),
    ADD CONSTRAINT attachments_mime_check CHECK (
        (kind = 'image' AND mime IN ('image/jpeg', 'image/png') AND width > 0 AND height > 0)
        OR (kind = 'document' AND mime IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain')
            AND width = 0 AND height = 0));
