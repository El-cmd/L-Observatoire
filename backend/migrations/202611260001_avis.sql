-- Thumbs up or down on an answer of the chat or on a created image (thumbs down: reasons and a comment, optional).
-- Only recorded: the answers do not change. The question and the answer are copied with the vote, for a page that
-- will show the votes later; an answer replaced by "Relancer" keeps its old vote here, hidden by answer_sha256.
CREATE TABLE feedback (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE,
    message_index integer CHECK (message_index >= 0),
    answer_sha256 text,
    question text,
    answer text,
    attachment_id uuid REFERENCES attachments(id) ON DELETE CASCADE,
    rating smallint NOT NULL CHECK (rating IN (-1, 1)),
    reasons text[] NOT NULL DEFAULT '{}',
    comment text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((conversation_id IS NOT NULL AND message_index IS NOT NULL AND answer_sha256 IS NOT NULL AND attachment_id IS NULL)
        OR (conversation_id IS NULL AND message_index IS NULL AND attachment_id IS NOT NULL))
);
CREATE UNIQUE INDEX feedback_one_per_answer ON feedback(conversation_id, message_index) WHERE conversation_id IS NOT NULL;
CREATE UNIQUE INDEX feedback_one_per_image ON feedback(user_id, attachment_id) WHERE attachment_id IS NOT NULL;
CREATE INDEX feedback_by_date ON feedback(created_at DESC);
