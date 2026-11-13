"""Extraction du texte des documents fournis (PDF, Word .docx et .doc, texte) ou d'un lien web."""
import io
import re
from html.parser import HTMLParser
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


# ---------------------------------------------------------------- lien web
ENTETES_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


class _TexteHTML(HTMLParser):
    """Garde le texte visible d'une page web (sans menus, scripts, styles)."""
    IGNORES = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button"}
    BLOCS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "td"}

    def __init__(self):
        super().__init__()
        self.morceaux, self.ignore, self.titre, self.dans_titre = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORES:
            self.ignore += 1
        elif tag == "title":
            self.dans_titre = True
        elif tag in self.BLOCS:
            self.morceaux.append("\n")
        if tag == "li":
            self.morceaux.append("- ")

    def handle_endtag(self, tag):
        if tag in self.IGNORES and self.ignore:
            self.ignore -= 1
        elif tag == "title":
            self.dans_titre = False

    def handle_data(self, data):
        if self.dans_titre:
            self.titre += data
        elif not self.ignore:
            self.morceaux.append(data)

    def texte(self):
        t = "".join(self.morceaux)
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n\n", t)
        return (f"Titre de la page : {self.titre.strip()}\n\n" if self.titre.strip() else "") + t.strip()


def texte_depuis_url(url):
    import requests
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=ENTETES_WEB, timeout=30)
        r.raise_for_status()
    except Exception as e:
        raise ValueError(f"Lien illisible ({e}). Enregistre la page en PDF et dépose-la comme document.")
    type_contenu = r.headers.get("content-type", "").lower()
    if "pdf" in type_contenu or url.lower().endswith(".pdf"):
        return texte_depuis_fichier("lien.pdf", r.content)
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
    p = _TexteHTML()
    p.feed(r.text)
    return p.texte()
