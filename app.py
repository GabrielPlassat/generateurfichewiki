"""Générateur de fiches pour le wiki XD (wikixd.fabmob.io).
Lancer en local :  streamlit run app.py
"""
import streamlit as st

import wiki_api
from extraction import texte_depuis_fichier
from generateur import charger_modeles, generer_fiche

st.set_page_config(page_title="Générateur de fiches wiki XD", page_icon="📝", layout="wide")


def secret(nom, defaut=""):
    try:
        return st.secrets.get(nom, defaut)
    except Exception:
        return defaut


wiki_api.WIKI_API = secret("WIKI_API", wiki_api.WIKI_API)


# ------------------------------------------------------------ lecture du wiki (mise en cache 1 h)
@st.cache_data(ttl=3600, show_spinner="Lecture du modèle sur le wiki…")
def infos_du_wiki(modele_wiki, formulaire_wiki, categories):
    infos = {"listes": {}, "erreurs": []}
    try:
        infos["source_modele"] = wiki_api.lire_page(f"Modèle:{modele_wiki}")
        infos["parametres"] = wiki_api.parametres_du_modele(infos["source_modele"])
        if formulaire_wiki:
            infos["source_formulaire"] = wiki_api.lire_page(f"Formulaire:{formulaire_wiki}")
    except Exception as e:
        infos["erreurs"].append(f"Modèle:{modele_wiki} illisible ({e})")
    for cat in categories:
        try:
            infos["listes"][cat] = wiki_api.membres_categorie(cat)
        except Exception as e:
            infos["erreurs"].append(f"Catégorie:{cat} illisible ({e})")
    return infos


# ------------------------------------------------------------ barre latérale : IA
st.sidebar.header("Moteur d'IA")
fournisseurs = [f for f, k in (("Albert", "ALBERT_API_KEY"), ("Claude", "ANTHROPIC_API_KEY")) if secret(k)]
if not fournisseurs:
    st.sidebar.error("Aucune clé d'API dans les secrets (ALBERT_API_KEY ou ANTHROPIC_API_KEY).")
    st.stop()
fournisseur = st.sidebar.radio("Fournisseur", fournisseurs)
if fournisseur == "Albert":
    cle, modele_ia = secret("ALBERT_API_KEY"), secret("ALBERT_MODEL", "albert-large")
else:
    cle, modele_ia = secret("ANTHROPIC_API_KEY"), secret("CLAUDE_MODEL", "claude-sonnet-5-5")
modele_ia = st.sidebar.text_input("Modèle", modele_ia)

# ------------------------------------------------------------ page principale
st.title("📝 Générateur de fiches pour le wiki XD")
st.caption("Choisis un modèle de fiche, dépose tes documents : l'IA rédige la fiche "
           "en respectant le modèle du wiki. Tu relis, puis tu colles sur le wiki.")

modeles = charger_modeles()
choix = st.selectbox("Type de fiche", list(modeles))
conf = modeles[choix]

categories = [c["liste_wiki"] for c in conf["champs"] if c.get("liste_wiki")]
infos = infos_du_wiki(conf["modele_wiki"], conf.get("formulaire_wiki", ""), tuple(categories))
for err in infos["erreurs"]:
    st.warning(f"⚠️ {err} — la fiche sera générée sans cette information.")

with st.expander("Valeurs par défaut (modifiables)"):
    defauts = {}
    for c in conf["champs"]:
        if c["source"] == "defaut":
            defauts[c["nom"]] = st.text_input(c["nom"], c.get("valeur", ""), key=f"{choix}-{c['nom']}")

with st.expander("Ce que l'appli a lu sur le wiki"):
    st.write(f"**Paramètres de Modèle:{conf['modele_wiki']}** :",
             ", ".join(infos.get("parametres", [])) or "—")
    for cat, noms in infos["listes"].items():
        st.write(f"**Catégorie:{cat}** : {len(noms)} pages")

fichiers = st.file_uploader("Documents source (PDF, Word .docx, texte)",
                            type=["pdf", "docx", "txt", "md", "doc"], accept_multiple_files=True)

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
                 "il faudrait un PDF avec du texte sélectionnable.")
        st.stop()
    with st.spinner("L'IA rédige la fiche…"):
        try:
            st.session_state["resultat"] = generer_fiche(conf, texte_docs, infos, defauts,
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
        try:
            if titre and wiki_api.page_existe(titre):
                st.warning(f"Une page « {titre} » existe déjà sur le wiki.")
        except Exception:
            pass
        st.download_button("⬇️ Télécharger (.txt)", wikitexte,
                           file_name=f"{titre or 'fiche'}.txt", mime="text/plain")
        if titre:
            st.link_button("✏️ Ouvrir la page sur le wiki", wiki_api.lien_creation(titre))
            st.caption("Copie le wikitexte, ouvre la page, colle-le en mode « Modifier le wikicode », publie.")
