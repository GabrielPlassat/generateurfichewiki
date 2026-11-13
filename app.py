"""Générateur de fiches pour le wiki XD (wikixd.fabmob.io).
L'appli ne se connecte pas au wiki : elle lit le document fourni et rédige la fiche
selon le modèle choisi. On colle ensuite le résultat sur le wiki.
Lancer en local :  streamlit run app.py
"""
from urllib.parse import quote

import streamlit as st

from extraction import texte_depuis_fichier, texte_depuis_url
from generateur import (categories_utilisees, charger_modeles, coordonnees, generer_fiche,
                        probleme_titre, remplacer_champ)
from listes_wiki import charger_liste

WIKI_BASE = "https://wikixd.fabmob.io"

st.set_page_config(page_title="Générateur de fiches wiki XD", page_icon="📝", layout="wide")


def secret(nom, defaut=""):
    try:
        return st.secrets.get(nom, defaut)
    except Exception:
        return defaut


@st.cache_data(ttl=3600, show_spinner="Chargement des listes du wiki…")
def listes_du_wiki(categories):
    listes, provenances = {}, {}
    for cat in categories:
        listes[cat], provenances[cat] = charger_liste(cat)
    return listes, provenances


# ------------------------------------------------------------ barre latérale : IA
st.sidebar.header("Moteur d'IA")
fournisseurs = [f for f, k in (("Albert", "ALBERT_API_KEY"), ("Claude", "ANTHROPIC_API_KEY")) if secret(k)]
if not fournisseurs:
    st.sidebar.error("Aucune clé d'API dans les secrets (ALBERT_API_KEY ou ANTHROPIC_API_KEY).")
    st.stop()
fournisseur = st.sidebar.radio("Fournisseur", fournisseurs)
if fournisseur == "Albert":
    cle, modele_ia = secret("ALBERT_API_KEY"), secret("ALBERT_MODEL", "mistral-small-3-2-24b-instruct-2506")
else:
    cle, modele_ia = secret("ANTHROPIC_API_KEY"), secret("CLAUDE_MODEL", "claude-sonnet-5-5")
modele_ia = st.sidebar.text_input("Modèle", modele_ia)

# ------------------------------------------------------------ page principale
st.title("📝 Générateur de fiches pour le wiki XD")
st.caption("Choisis le type de fiche, dépose un document ou un lien qui le décrit : l'IA rédige "
           "la fiche au format du wiki. Tu relis, puis tu la colles sur le wiki.")

modeles = charger_modeles()
choix = st.selectbox("Type de fiche (choisir dans la liste)", list(modeles))
conf = modeles[choix]

listes, provenances = listes_du_wiki(tuple(categories_utilisees(conf)))
for cat, prov in provenances.items():
    if listes[cat]:
        st.caption(f"Liste « {cat} » : {len(listes[cat])} noms — {prov}")
    else:
        st.warning(f"Liste « {cat} » du wiki indisponible : les noms ne pourront pas être vérifiés. "
                   f"Lance le notebook rafraichir_listes_wiki.ipynb.", icon="⚠️")

titre = st.text_input("Titre de la page wiki à créer",
                      help="Le nom du projet, de l'évènement ou de l'acteur, tel qu'il apparaîtra sur le wiki. Pas d'apostrophe.")
st.caption("⚠️ N'utilise pas d'apostrophe dans le titre (ni ' ni ’).")
erreur_titre = probleme_titre(titre) if titre else ""
if erreur_titre:
    st.error(erreur_titre)

with st.expander("Valeurs par défaut (modifiables)"):
    defauts = {}
    for c in conf["champs"]:
        if c["source"] == "defaut":
            defauts[c["nom"]] = st.text_input(c["nom"], c.get("valeur", ""), key=f"{choix}-{c['nom']}")

st.markdown("**Source** : un document, un lien, ou les deux")
fichiers = st.file_uploader("Document (PDF ou Word)",
                            type=["pdf", "docx", "doc", "txt", "md"], accept_multiple_files=True)
lien = st.text_input("Lien vers une page web qui le décrit (site, article, programme…)",
                     placeholder="https://…")

pret = (bool(fichiers) or bool(lien.strip())) and bool(titre) and not erreur_titre
if st.button("Générer la fiche", type="primary", disabled=not pret):
    textes = []
    for f in fichiers:
        try:
            textes.append(f"===== Document : {f.name} =====\n" + texte_depuis_fichier(f.name, f.getvalue()))
        except Exception as e:
            st.error(str(e))
    if lien.strip():
        with st.spinner("Lecture du lien…"):
            try:
                textes.append(f"===== Page web : {lien.strip()} =====\n" + texte_depuis_url(lien))
            except Exception as e:
                st.error(str(e))
    texte_docs = "\n\n".join(textes)
    if len(texte_docs.strip()) < 200:
        st.error("Presque aucun texte n'a pu être lu. Le PDF est peut-être scanné (image), ou la "
                 "page web est construite en JavaScript : enregistre-la en PDF et dépose-la.")
        st.stop()
    with st.spinner("L'IA rédige la fiche…"):
        try:
            res = generer_fiche(conf, titre.strip(), texte_docs, listes, defauts,
                                fournisseur, cle, modele_ia, liens=[lien.strip()] if lien.strip() else [])
            res["modele"] = choix
            st.session_state["resultat"] = res
            st.session_state["wikitexte"] = res["wikitexte"]
            st.session_state["lieu"] = res["lieu"]
        except Exception as e:
            st.session_state.pop("resultat", None)     # ne pas laisser affichée une ancienne fiche
            st.error(f"Échec de la génération : {e}")

# ------------------------------------------------------------ résultat
champ_geo = next((c for c in conf["champs"] if c["source"] == "geo"), None)


def recalculer_coordonnees():
    val, rq = coordonnees(champ_geo, st.session_state["lieu"])
    st.session_state["wikitexte"] = remplacer_champ(st.session_state["wikitexte"], champ_geo["nom"], val)
    if champ_geo.get("lieu_depuis") and not champ_geo.get("consigne"):   # le lieu est aussi un champ de la fiche
        st.session_state["wikitexte"] = remplacer_champ(st.session_state["wikitexte"],
                                                        champ_geo["lieu_depuis"], st.session_state["lieu"])
    st.session_state["message_geo"] = rq


res = st.session_state.get("resultat")
if res and res.get("modele") != choix:      # fiche d'un autre type : on ne l'affiche pas
    res = None
if res:
    st.divider()
    col1, col2 = st.columns([2, 1])
    with col1:
        titre_page = res["titre"]
        st.markdown(f"**Page :** {titre_page}")
        wikitexte = st.text_area("Fiche en wikitexte (modifiable)", key="wikitexte", height=600)
    with col2:
        if res.get("extrait"):
            with st.expander("Passage retenu dans la source"):
                st.caption("Seul ce passage a servi à rédiger la fiche.")
                st.text(res["extrait"])
        st.subheader("À vérifier")
        if res["remarques_ia"]:
            st.info(res["remarques_ia"])
        for r in res["remarques"]:
            st.write("• " + r)

        if champ_geo:
            st.subheader("Coordonnées")
            st.text_input("Lieu (commune, département)", key="lieu",
                          help="Exemple : Saint-Flour, Cantal — ou une adresse complète.")
            st.button("📍 Recalculer les coordonnées", on_click=recalculer_coordonnees)
            if st.session_state.get("message_geo"):
                st.caption(st.session_state["message_geo"])

        st.subheader("Publier")
        st.download_button("⬇️ Télécharger (.txt)", wikitexte,
                           file_name=f"{titre_page}.txt", mime="text/plain")
        if titre_page:
            lien = f"{WIKI_BASE}/index.php?title={quote(titre_page.replace(' ', '_'))}&action=edit"
            st.link_button("✏️ Ouvrir la page sur le wiki", lien)
            st.caption("Copie le wikitexte, ouvre la page, colle-le en mode « Modifier le wikicode », publie.")
