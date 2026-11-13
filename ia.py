"""Appel au modèle de langage : API Albert (Etat) ou Claude (Anthropic)."""
import json
import re

ALBERT_URL = "https://albert.api.etalab.gouv.fr/v1"


def appeler_ia(systeme, utilisateur, fournisseur, cle, modele):
    if fournisseur == "Albert":
        from openai import OpenAI
        client = OpenAI(api_key=cle, base_url=ALBERT_URL)
        rep = client.chat.completions.create(
            model=modele, temperature=0.2,
            messages=[{"role": "system", "content": systeme},
                      {"role": "user", "content": utilisateur}])
        return rep.choices[0].message.content
    if fournisseur == "Claude":
        import anthropic
        client = anthropic.Anthropic(api_key=cle)
        rep = client.messages.create(
            model=modele, max_tokens=8000, temperature=0.2, system=systeme,
            messages=[{"role": "user", "content": utilisateur}])
        return "".join(b.text for b in rep.content if b.type == "text")
    raise ValueError(f"Fournisseur inconnu : {fournisseur}")


def lire_json(texte):
    """Récupère le premier objet JSON dans la réponse (tolère ```json ... ```)."""
    texte = re.sub(r"^```(?:json)?|```$", "", texte.strip(), flags=re.M).strip()
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("L'IA n'a pas renvoyé de JSON :\n" + texte[:500])
    return json.loads(texte[debut:fin + 1])
