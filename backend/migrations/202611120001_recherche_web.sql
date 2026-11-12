-- Recherche web (orchestrateur et outil recherche_web) : seulement pour les comptes qui y ont droit.
-- Changer ce droit : make recherche-web (commande « recherche-web » de l'API).
ALTER TABLE users ADD COLUMN recherche_web boolean NOT NULL DEFAULT false;
-- Ouverte d'abord au seul compte de l'auteur.
UPDATE users SET recherche_web = true WHERE username = 'vloth';
