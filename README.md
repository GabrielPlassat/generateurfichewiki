# Générateur de fiches pour le wiki XD

Appli Streamlit : on choisit un type de fiche (pour l'instant **Projet**), on dépose le document
qui décrit le projet (PDF ou Word), et l'IA rédige la fiche en wikitexte au format du modèle
`{{Project}}` du wiki [wikixd.fabmob.io](https://wikixd.fabmob.io).

L'appli **ne se connecte pas au wiki** : on relit la fiche, puis on la colle sur le wiki.

## Ce que fait l'appli

1. Lit le document (PDF texte, Word .docx avec ses tableaux, ancien Word .doc).
2. Demande à l'IA (Albert ou Claude) de remplir les champs « à rédiger » du modèle.
3. Ajoute les valeurs par défaut (référent, challenge, forum…), modifiables dans l'interface.
4. Calcule les coordonnées géographiques à partir du lieu (service public de l'IGN).
5. Affiche la fiche (modifiable), une liste « À vérifier », un bouton de téléchargement et un
   lien qui ouvre la page sur le wiki.

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
| `geo.py` | coordonnées géographiques (IGN / Base Adresse Nationale) |
| `packages.txt` | outil `antiword` pour lire les anciens .doc |

## Limites

- PDF scannés (images) : pas de texte lisible → l'appli le signale.
- Les noms de véhicules et d'acteurs sont repris tels qu'écrits dans le document : vérifier qu'ils
  correspondent aux noms des pages du wiki.
