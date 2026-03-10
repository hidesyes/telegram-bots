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

    return ""
