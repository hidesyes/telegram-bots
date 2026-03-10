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
                # section 파일 찾기 (경로 패턴이 버전마다 다를 수 있음)
                section_files = [
                    n for n in sorted(zf.namelist())
                    if "section" in n.lower() and n.endswith(".xml")
                ]
                for entry in section_files:
                    with zf.open(entry) as f:
                        root = ET.fromstring(f.read())
                        for elem in root.iter():
                            # 네임스페이스 제거 후 태그명 확인
                            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                            if tag == "t" and elem.text and elem.text.strip():
                                text_parts.append(elem.text.strip())
        except Exception:
            return ""
        return "\n".join(text_parts)

    return ""
