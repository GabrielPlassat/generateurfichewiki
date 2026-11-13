"""Générateur de fiches pour le wiki XD (wikixd.fabmob.io).
L'appli ne se connecte pas au wiki : elle lit le document fourni et rédige la fiche
selon le modèle choisi. On colle ensuite le résultat sur le wiki.
Lancer en local :  streamlit run app.py
"""
from urllib.parse import quote

import streamlit as st

from extraction import texte_depuis_fichier
from generateur import charger_modeles, generer_fiche

WIKI_BASE = "https://wikixd.fabmob.io"

st.set_page_config(page_title="Générateur de fiches wiki XD", page_icon="📝", layout="wide")


def secret(nom, defaut=""):
    try:
        return st.secrets.get(nom, defaut)
    except Exception:
        return defaut


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
st.caption("Choisis le type de fiche, dépose le document qui décrit le projet : l'IA rédige "
           "la fiche au format du wiki. Tu relis, puis tu la colles sur le wiki.")

modeles = charger_modeles()
choix = st.selectbox("Type de fiche", list(modeles))
conf = modeles[choix]

with st.expander("Valeurs par défaut (modifiables)"):
    defauts = {}
    for c in conf["champs"]:
        if c["source"] == "defaut":
            defauts[c["nom"]] = st.text_input(c["nom"], c.get("valeur", ""), key=f"{choix}-{c['nom']}")

fichiers = st.file_uploader("Document source (PDF ou Word)",
                            type=["pdf", "docx", "doc", "txt", "md"], accept_multiple_files=True)

if st.button("Générer la fiche", type="primary", disabled=not fichiers):
    textes = []
    for f in fichiers:
        try:
            textes.append(f"===== Document : {f.name} =====\n" + texte_depuis_fichier(f.name, f.getvalue()))
        except Exception as e:
            st.error(str(e))
    texte_docs = "\n\n".join(textes)
    if len(texte_docs.strip()) < 200:
        st.error("Presque aucun texte n'a pu être lu. Le PDF est peut-être scanné (image) : "
                 "il faut un PDF avec du texte sélectionnable.")
        st.stop()
    with st.spinner("L'IA rédige la fiche…"):
        try:
            st.session_state["resultat"] = generer_fiche(conf, texte_docs, defauts,
                                                         fournisseur, cle, modele_ia)
        except Exception as e:
            st.error(f"Échec de la génération : {e}")

# ------------------------------------------------------------ résultat
res = st.session_state.get("resultat")
if res:
    st.divider()
    col1, col2 = st.columns([2, 1])
    with col1:
        titre = st.text_input("Titre de la page", res["titre"])
        wikitexte = st.text_area("Fiche en wikitexte (modifiable)", res["wikitexte"], height=520)
    with col2:
        st.subheader("À vérifier")
        if res["remarques_ia"]:
            st.info(res["remarques_ia"])
        for r in res["remarques"]:
            st.write("• " + r)
        st.download_button("⬇️ Télécharger (.txt)", wikitexte,
                           file_name=f"{titre or 'fiche'}.txt", mime="text/plain")
        if titre:
            lien = f"{WIKI_BASE}/index.php?title={quote(titre.replace(' ', '_'))}&action=edit"
            st.link_button("✏️ Ouvrir la page sur le wiki", lien)
            st.caption("Copie le wikitexte, ouvre la page, colle-le en mode « Modifier le wikicode », publie.")
