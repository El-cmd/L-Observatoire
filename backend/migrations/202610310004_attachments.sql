-- User library: images sanitized by image-guard. Messages only reference them, so deleting
-- a conversation keeps its images; deleting an image leaves a "deleted" mention in messages.
CREATE TABLE attachments (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sha256 text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('image')),
    name text NOT NULL,
    mime text NOT NULL CHECK (mime IN ('image/jpeg', 'image/png')),
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    size integer NOT NULL,
    data bytea NOT NULL,
    thumbnail bytea NOT NULL,
    -- Written by Qwen only when old messages are summarized to free the context.
    transcript text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, sha256)
);
CREATE INDEX attachments_by_user ON attachments(user_id, created_at DESC);
