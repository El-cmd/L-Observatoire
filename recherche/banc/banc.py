"""Banc d'essai de la recherche web : pose chaque question de questions.toml à L'Observatoire (bouton Web, mode
Automatique, version locale ou autre ORIGIN) et note la réponse sur 10.

Usage : python3 recherche/banc/banc.py <compte> <fichier du mot de passe> [id …]
Résultats : recherche/banc/resultats/<date>/ (une réponse par question, avec ses étapes, et resume.md).
"""
import json, os, re, sys, time, tomllib, urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlsplit

ICI = Path(__file__).parent
ORIGIN = os.environ.get("ORIGIN", "http://localhost:8080")
MODE = os.environ.get("MODE", "auto")
DUREE_MAX = 60


def officielle(url: str, domaines: list[str]) -> bool:
    hote = (urlsplit(url).hostname or "").lower()
    return any(hote == d or hote.endswith("." + d) for d in domaines)


def noter(q: dict, reponse: dict, duree: float) -> dict:
    texte = reponse.get("content", "")
    outils = reponse.get("outils") or []
    juste = all(re.search(a, texte, re.I) for a in q["attendu"])
    citees = [s.get("url", "") for e in outils if e.get("type") == "sources" for s in e.get("sources") or []]
    # Sources réellement citées dans la réponse : leur numéro [n] y figure (sinon, toutes celles listées).
    numeros = {int(n) for n in re.findall(r"\[(\d+)\]", texte)}
    sources = [s for e in outils if e.get("type") == "sources" for s in e.get("sources") or []]
    citees = [s.get("url", "") for s in sources if not numeros or s.get("numero", s.get("source")) in numeros] or citees
    lues = [p.get("url", "") for e in outils if e.get("type") == "recherche" for p in e.get("pages") or [] if p.get("etat") == "lue"]
    citee = any(officielle(u, q["officiels"]) for u in citees)
    lue = any(officielle(u, q["officiels"]) for u in lues)
    note = 5 * juste + 3 * citee + 1 * lue + 1 * (duree <= DUREE_MAX)
    return {"juste": juste, "officielle_citee": citee, "officielle_lue": lue, "duree": round(duree), "note": note,
            "pages_lues": len(lues), "pages_officielles_lues": sum(officielle(u, q["officiels"]) for u in lues)}


def main():
    compte, mot_de_passe, choix = sys.argv[1], Path(sys.argv[2]).read_text().strip(), set(sys.argv[3:])
    questions = [q for q in tomllib.loads((ICI / "questions.toml").read_text())["question"] if not choix or q["id"] in choix]
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), urllib.request.ProxyHandler({}))
    csrf = ""

    def call(path, method="GET", body=None, timeout=60, flux=False):
        headers = {"Origin": ORIGIN, **({"Content-Type": "application/json"} if body is not None else {}), **({"X-CSRF-Token": csrf} if csrf else {})}
        request = urllib.request.Request(ORIGIN + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
            return None if flux or not raw else json.loads(raw)

    csrf = call("/api/auth/login", "POST", {"username": compte, "password": mot_de_passe})["csrf_token"]
    dossier = ICI / "resultats" / datetime.now().strftime("%Y-%m-%d-%H%M")
    dossier.mkdir(parents=True, exist_ok=True)
    lignes = []
    for q in questions:
        chat = call("/api/conversations", "POST")
        texte = f"Cherche sur Internet : {q['question']} Donne tes sources."
        chat = call(f"/api/conversations/{chat['id']}", "PUT", {"version": chat["version"], "messages": [{"role": "user", "content": texte}]})
        debut = time.time()
        call(f"/api/conversations/{chat['id']}/generate", "POST", {"version": chat["version"], "recherche": MODE}, timeout=900, flux=True)
        duree = time.time() - debut
        reponse = call(f"/api/conversations/{chat['id']}")["messages"][-1]
        call(f"/api/conversations/{chat['id']}", "DELETE")
        note = noter(q, reponse, duree)
        (dossier / f"{q['id']}.json").write_text(json.dumps({"question": q, "note": note, "reponse": reponse}, ensure_ascii=False, indent=1))
        lignes.append((q, note))
        print(f"{q['id']:12} {note['note']:>2}/10  juste={'oui' if note['juste'] else 'NON'}  officielle citée={'oui' if note['officielle_citee'] else 'non'}"
              f"  lue={'oui' if note['officielle_lue'] else 'non'}  {note['duree']} s", flush=True)
    moyenne = sum(n["note"] for _, n in lignes) / max(len(lignes), 1)
    resume = [f"# Banc d'essai de la recherche — {dossier.name} (mode {MODE})", "",
              "| Question | Thème | Note | Juste | Officielle citée | Officielle lue | Durée |", "|---|---|---|---|---|---|---|"]
    resume += [f"| {q['id']} | {q['theme']} | {n['note']}/10 | {'oui' if n['juste'] else '**non**'} | {'oui' if n['officielle_citee'] else '**non**'} | "
               f"{'oui' if n['officielle_lue'] else 'non'} | {n['duree']} s |" for q, n in lignes]
    resume += ["", f"Moyenne : {moyenne:.1f}/10 · sous 9 : {sum(n['note'] < 9 for _, n in lignes)} question(s)"]
    (dossier / "resume.md").write_text("\n".join(resume) + "\n")
    print(f"moyenne {moyenne:.1f}/10 → {dossier}")


if __name__ == "__main__":
    main()
