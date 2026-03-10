def parse_file(file_bytes: bytes, filename: str) -> str:
    """
    txt / docx / pdf 파일을 받아 텍스트 문자열로 반환.
    지원하지 않는 형식이면 빈 문자열 반환.
    """
    name = filename.lower()

    if name.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace")

    elif name.endswith(".docx"):
        import io
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    elif name.endswith(".pdf"):
        import io
        import pdfplumber
        pages = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)

    elif name.endswith(".hwpx") or name.endswith(".hwp"):
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        text_parts = []
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                for entry in sorted(zf.namelist()):
                    if "BodyText/Section" in entry and entry.endswith(".xml"):
                        with zf.open(entry) as f:
                            root = ET.parse(f).getroot()
                            for elem in root.iter():
                                if elem.text and elem.text.strip():
                                    text_parts.append(elem.text.strip())
        except Exception:
            return ""
        return "\n".join(text_parts)

    return ""
