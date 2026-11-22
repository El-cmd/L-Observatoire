-- Images créées dans l'onglet Images : elles vivent dans la bibliothèque comme les autres, avec la façon dont
-- elles ont été faites (prompt de l'utilisateur, prompt envoyé au modèle, style, taille, graine). NULL : image envoyée.
ALTER TABLE attachments ADD COLUMN generation jsonb;
