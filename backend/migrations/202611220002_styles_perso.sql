-- Styles of the Images tab written by a user: a name and the words added after the description,
-- with an example image (a JPEG thumbnail from image-guard, created by the image model).
CREATE TABLE image_styles (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name text NOT NULL,
    words text NOT NULL,
    example bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX image_styles_by_user ON image_styles(user_id, created_at);
