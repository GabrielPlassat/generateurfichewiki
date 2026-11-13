# Générateur de fiches pour le wiki XD

Appli Streamlit : on choisit un type de fiche (pour l'instant **Projet**), on dépose le document
qui décrit le projet (PDF ou Word), et l'IA rédige la fiche en wikitexte au format du modèle
`{{Project}}` du wiki [wikixd.fabmob.io](https://wikixd.fabmob.io).

L'appli **ne se connecte pas au wiki** : on relit la fiche, puis on la colle sur le wiki.

## Ce que fait l'appli

1. Demande le **titre de la page wiki** (sans apostrophe) et lit le document
   (PDF texte, Word .docx avec ses tableaux, ancien Word .doc).
2. Demande à l'IA (Albert ou Claude) de remplir les champs « à rédiger » du modèle.
3. Ajoute les valeurs par défaut (référent, challenge, forum…), modifiables dans l'interface.
4. Calcule les coordonnées géographiques à partir du lieu (service public de l'IGN).
5. Affiche la fiche (modifiable), une liste « À vérifier », un bouton de téléchargement et un
   lien qui ouvre la page sur le wiki.

## Listes des véhicules et des acteurs du wiki

Les champs `vehicule_equipe`, `from` et `to` n'acceptent **que** des noms de pages existant sur le wiki
(catégories `Vehicule` et `Acteur`), avec leur orthographe exacte. Les autres noms sont écartés et
signalés dans « À vérifier ».

L'appli essaie de lire ces listes en direct sur le wiki ; si le wiki refuse (erreur 402/403),
elle utilise les fichiers `donnees_wiki/Categorie_Vehicule.txt` et `donnees_wiki/Categorie_Acteur.txt`.

**Mettre à jour les listes** : ouvrir `rafraichir_listes_wiki.ipynb` dans Google Colab, tout exécuter,
puis déposer les fichiers téléchargés dans le dossier `donnees_wiki/` du dépôt GitHub
(*Add file → Upload files*). On peut aussi modifier ces fichiers à la main sur GitHub : un nom par ligne.

## Mise en ligne sur Streamlit Cloud

1. Sur share.streamlit.io : *Create app* → dépôt `generateurfichewiki`, branche `main`, fichier `app.py`.
2. *Advanced settings → Secrets* : coller le contenu de `.streamlit/secrets.toml.example` avec ta clé.

## Modifier ou ajouter un modèle

Tout est dans `modeles/projet.yaml` : la liste des champs dans l'ordre du modèle wiki, et pour chacun :
- `source: ia` + `consigne` : rédigé par l'IA à partir du document ;
- `source: defaut` + `valeur` : valeur fixe ;
- `source: geo` : coordonnées calculées à partir du champ `lieu_depuis` ;
- `source: vide` : laissé vide.

Pour un nouveau type (Évènement, Acteur, Véhicule) : copier `projet.yaml`, adapter `nom_affiche`,
`modele_wiki` et les champs. Il apparaît automatiquement dans le menu.

## Fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | l'interface Streamlit |
| `modeles/*.yaml` | un fichier par type de fiche : champs, consignes, valeurs par défaut |
| `generateur.py` | prépare la demande à l'IA et assemble la fiche |
| `extraction.py` | lecture des PDF / Word |
| `ia.py` | appel à Albert ou Claude |
| `listes_wiki.py` | listes des véhicules / acteurs du wiki (en direct ou fichiers `donnees_wiki/`) |
| `rafraichir_listes_wiki.ipynb` | notebook Colab qui met à jour les fichiers `donnees_wiki/` |
| `geo.py` | coordonnées géographiques (IGN / Base Adresse Nationale) |
| `packages.txt` | outil `antiword` pour lire les anciens .doc |

## Limites

- PDF scannés (images) : pas de texte lisible → l'appli le signale.
- Un véhicule ou un acteur sans page sur le wiki est écarté : créer sa page, puis l'ajouter à la main.
