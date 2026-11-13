# Générateur de fiches pour le wiki XD

Appli Streamlit : on choisit un type de fiche (Projet, puis bientôt Évènement, Acteur, Véhicule),
on dépose des documents (PDF, Word .docx, texte), et l'IA rédige la fiche en wikitexte
en respectant le modèle du wiki [wikixd.fabmob.io](https://wikixd.fabmob.io).

## Ce que fait l'appli

1. **Lit le wiki** au démarrage (mis en cache 1 h) : le code de `Modèle:Project`, le `Formulaire:Projet`,
   et les listes des pages des catégories `Vehicule` et `Acteur`.
2. **Lit les documents** déposés (PDF texte, .docx avec ses tableaux, .txt/.md).
3. **Demande à l'IA** (Albert ou Claude) de remplir les champs « à rédiger », en lui donnant le modèle
   du wiki et les noms exacts des véhicules et acteurs.
4. **Post-traite** :
   - valeurs par défaut (référent, challenge, forum…) imposées, modifiables dans l'interface ;
   - noms de véhicules et d'acteurs **corrigés selon l'orthographe du wiki**, et les noms inconnus signalés ;
   - **coordonnées géographiques calculées** par le service public de l'IGN à partir du lieu trouvé par l'IA
     (l'IA n'invente pas les coordonnées).
5. **Affiche la fiche** (modifiable), une liste « À vérifier », un bouton de téléchargement et un lien
   qui ouvre la page sur le wiki pour coller la fiche.

## Mise en ligne sur Streamlit Cloud

1. Mettre ce dossier dans un dépôt GitHub.
2. Sur share.streamlit.io : *New app* → choisir le dépôt → fichier principal `app.py`.
3. *Settings → Secrets* : coller le contenu de `.streamlit/secrets.toml.example` avec ta clé Albert
   (ou Claude).

## Ajouter un modèle (Évènement, Acteur, Véhicule)

Pas de code à écrire : copier `modeles/projet.yaml` en `modeles/evenement.yaml`, puis changer :
- `nom_affiche` (ce qui apparaît dans le menu), `modele_wiki` (ex. `Event`), `formulaire_wiki` ;
- la liste `champs` : pour chacun, `source: ia` (rédigé par l'IA, avec une `consigne`),
  `source: defaut` (valeur fixe), `source: geo` (lieu → coordonnées), et `liste_wiki: Acteur`
  si les noms doivent exister dans une catégorie du wiki.

Le nouveau type apparaît automatiquement dans le menu.

## Fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | l'interface Streamlit |
| `modeles/*.yaml` | un fichier par type de fiche : champs, consignes, valeurs par défaut |
| `generateur.py` | le moteur : prépare la demande à l'IA et assemble la fiche |
| `wiki_api.py` | lecture du wiki (modèles, catégories, existence d'une page) |
| `extraction.py` | lecture des PDF / Word |
| `ia.py` | appel à Albert ou Claude |
| `geo.py` | géocodage (IGN / Base Adresse Nationale) |

## Limites connues

- PDF scannés (images) : pas de texte lisible → l'appli le signale.
- Ancien format `.doc` : à réenregistrer en `.docx`.
- La fiche n'est pas publiée automatiquement sur le wiki : on la relit puis on la colle
  (publication directe possible plus tard avec un compte robot du wiki).
