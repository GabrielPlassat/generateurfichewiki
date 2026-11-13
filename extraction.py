"""Extraction du texte des documents fournis (PDF, Word, texte)."""
import io


def texte_depuis_fichier(nom, contenu: bytes) -> str:
    ext = nom.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        from pypdf import PdfReader
        lecteur = PdfReader(io.BytesIO(contenu))
        return "\n".join((p.extract_text() or "") for p in lecteur.pages)
    if ext == "docx":
        import docx
        d = docx.Document(io.BytesIO(contenu))
        lignes = [p.text for p in d.paragraphs]
        for table in d.tables:  # les tableaux contiennent souvent des infos utiles
            for row in table.rows:
                lignes.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(lignes)
    if ext in ("txt", "md"):
        return contenu.decode("utf-8", errors="replace")
    if ext == "doc":
        raise ValueError(f"{nom} : l'ancien format .doc n'est pas lu. "
                         "Ouvre-le dans Word et enregistre-le en .docx.")
    raise ValueError(f"{nom} : format non pris en charge.")
