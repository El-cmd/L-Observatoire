-- Recherche web ouverte à tous les comptes (15/11/2026), y compris ceux créés ensuite. Le droit reste : make recherche-web
-- la ferme ou la rouvre pour un compte.
ALTER TABLE users ALTER COLUMN recherche_web SET DEFAULT true;
UPDATE users SET recherche_web = true;
