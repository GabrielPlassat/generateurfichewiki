"""Extraction du texte des documents fournis (PDF, Word .docx et .doc, texte)."""
import io
import subprocess
import tempfile


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
    if ext == "doc":
        # ancien format Word : lu avec l'outil antiword (installé via packages.txt)
        with tempfile.NamedTemporaryFile(suffix=".doc") as f:
            f.write(contenu)
            f.flush()
            try:
                return subprocess.run(["antiword", "-w", "0", f.name], capture_output=True,
                                      text=True, check=True, timeout=60).stdout
            except Exception:
                raise ValueError(f"{nom} : lecture du .doc impossible. "
                                 "Ouvre-le dans Word et enregistre-le en .docx ou en PDF.")
    if ext in ("txt", "md"):
        return contenu.decode("utf-8", errors="replace")
    raise ValueError(f"{nom} : format non pris en charge.")
