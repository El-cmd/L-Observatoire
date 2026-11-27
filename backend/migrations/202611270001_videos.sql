-- Onglet Vidéo : une image devient une courte vidéo (Wan 2.2 I2V par LiteLLM, sur le serveur IA). Le backend tient
-- la file : il n'envoie qu'une vidéo à la fois au service, la suit en tâche de fond et range le MP4 fini dans la
-- bibliothèque, car le service efface ses vidéos au bout de 24 h et les oublie quand il redémarre.
--
-- waiting : dans la file de L'Observatoire, pas encore envoyée ; running : envoyée (service_id), suivie ;
-- ready : MP4 rangé (attachment_id) ; failed : refusée ou échouée ; lost : le service ne la connaît plus.
CREATE TABLE videos (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'running', 'ready', 'failed', 'lost')),
    -- Identifiant « video_… » exactement tel que la création le renvoie ; état vu chez le service (queued, in_progress).
    service_id text,
    service_status text,
    -- Réglages (résolution, durée, étapes, fluidité, graine, caméra…) et durée de calcul estimée.
    settings jsonb NOT NULL,
    -- Texte de l'utilisateur, version de Qwen éventuelle, et texte envoyé au modèle (caméra comprise).
    prompt text NOT NULL,
    improved text,
    sent text NOT NULL,
    negative text NOT NULL DEFAULT '',
    -- Image de départ : gardée ici (déjà nettoyée par image-guard) pour l'envoyer même si elle quitte la
    -- bibliothèque entre-temps ; sa vignette devient celle de la vidéo.
    source_id uuid REFERENCES attachments(id) ON DELETE SET NULL,
    source_mime text NOT NULL CHECK (source_mime IN ('image/jpeg', 'image/png')),
    source_data bytea NOT NULL,
    source_thumbnail bytea NOT NULL,
    attachment_id uuid REFERENCES attachments(id) ON DELETE SET NULL,
    error text,
    -- Envois ratés (service injoignable) : la vidéo reste dans la file et réessaie, quelques fois au plus.
    attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    -- Première fois vue « in_progress » chez le service : début du calcul, pour l'avancement estimé.
    started_at timestamptz,
    finished_at timestamptz,
    checked_at timestamptz
);
CREATE INDEX videos_by_user ON videos(user_id, created_at DESC);
CREATE INDEX videos_open ON videos(created_at) WHERE status IN ('waiting', 'running');

-- Les vidéos finies vivent dans la bibliothèque : MP4 seulement, avec leurs dimensions.
ALTER TABLE attachments
    DROP CONSTRAINT attachments_kind_check,
    DROP CONSTRAINT attachments_mime_check,
    ADD CONSTRAINT attachments_kind_check CHECK (kind IN ('image', 'document', 'video')),
    ADD CONSTRAINT attachments_mime_check CHECK (
        (kind = 'image' AND mime IN ('image/jpeg', 'image/png') AND width > 0 AND height > 0)
        OR (kind = 'document' AND mime IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain')
            AND width = 0 AND height = 0)
        OR (kind = 'video' AND mime = 'video/mp4' AND width > 0 AND height > 0));
