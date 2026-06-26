# Skill CoaNIMM — Version adaptée (expurgée / abrégée) d'un document

Ce skill produit, à partir d'un document existant (PDF, Word, EPUB, page web
enregistrée, image scannée…), une **version adaptée aux enfants** : les scènes
violentes, sexuelles, d'horreur ou le langage grossier sont retirés ou adoucis,
l'histoire est préservée, et le résultat est un **document accessible** (EPUB,
Word, PDF…) avec titres, langue déclarée et images décrites.

Il n'ajoute aucun code à NIMM : il **enchaîne trois outils CoaNIMM existants** —
`nimm_extract_text` (lire le document), `nimm_expurgate` (adapter le texte) et
`nimm_make_document` (régénérer un document accessible).

---

## 1. La façon simple : demander en langage naturel

Dans le panneau CoaNIMM, on peut simplement écrire une consigne comme :

> Crée une version adaptée aux enfants de ce livre : `C:\Users\moi\Documents\roman.pdf`,
> au format EPUB. Retire les scènes difficiles mais garde l'intrigue.

CoaNIMM génère et lance le script tout seul. Pour un **texte court**, cela suffit.

---

## 2. La façon robuste : pour un long document

Un livre entier dépasse la quantité de texte qu'un modèle peut traiter d'un coup.
Le script ci-dessous **découpe** le document en morceaux, adapte chaque morceau,
puis **réassemble** le tout. C'est la méthode à privilégier pour un vrai livre.

Coller ce script dans la zone de code de CoaNIMM, ajuster les 4 lignes du haut,
puis exécuter :

```python
# --- À adapter ---------------------------------------------------------------
SOURCE = r"C:\Users\moi\Documents\roman.pdf"   # le document de départ
FORMAT = "epub"                                # epub, docx, pdf, html ou txt
TITRE  = "Roman — version adaptée"             # titre du document produit
CONSIGNE = "Pour des enfants de 8 à 10 ans. Abrège un peu. Garde l'intrigue principale."
# -----------------------------------------------------------------------------

# 1) Lire le texte du document (PDF, Word, EPUB, HTML, image avec OCR…)
texte = nimm_extract_text(SOURCE)

# 2) Découper en morceaux raisonnables (sans couper au milieu d'un paragraphe)
def decouper(t, taille=6000):
    morceaux, courant = [], ""
    for para in t.split("\n\n"):
        if courant and len(courant) + len(para) > taille:
            morceaux.append(courant)
            courant = ""
        courant += para + "\n\n"
    if courant.strip():
        morceaux.append(courant)
    return morceaux

morceaux = decouper(texte)
print(f"{len(morceaux)} morceau(x) à adapter.")

# 3) Adapter chaque morceau, puis l'ajouter comme une section du document
sections = []
for i, m in enumerate(morceaux, 1):
    adapte = nimm_expurgate(m, CONSIGNE)
    sections.append({"titre": f"Partie {i}", "texte": adapte})
    print(f"Partie {i} adaptée.")

# 4) Produire le document accessible final
chemin = nimm_make_document(TITRE, sections, fmt=FORMAT)
print("Document créé :", chemin)
```

Le fichier produit arrive dans l'espace de travail de CoaNIMM. S'il est en
`html`, le bouton **« Copier (mise en forme) »** permet de le coller ailleurs.

---

## 3. En faire un skill réutilisable

Après une exécution réussie, dans le panneau de validation, cocher
**« Aussi mémoriser la méthode comme skill réutilisable »**. La prochaine fois
qu'une demande ressemblera (« adapte ce livre pour enfants »), CoaNIMM
retrouvera la méthode et la réappliquera, sans repartir de zéro.

---

## Notes

- Les outils `extract_text`, `expurgate` et `make_document` doivent être
  **activés** dans le panneau « Outils de CoaNIMM ».
- Le format `pptx` nécessite la bibliothèque `python-pptx` (voir `requirements.txt`).
- `nimm_expurgate` adoucit le contenu sensible ; il reste prudent de **relire**
  le résultat avant de le donner à un enfant.
