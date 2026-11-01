"""Opens one untrusted document in its own process, with capped memory and CPU time:

    python lecteur.py analyse <file> <extension>   -> JSON on stdout
    python lecteur.py page <file> <number> <side>  -> JPEG of the page, longest side in pixels

A refused document exits with code 3 and {"error": message for the user} on stdout.
"""
import json
import re
import resource
import sys
import unicodedata

MAX_PAGES = 60
SIDES = (1600, 2400)
# Code is sent to Qwen in a fenced block with its language; other text files as they are.
CODE = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'tsx', '.jsx': 'jsx', '.rs': 'rust', '.go': 'go',
        '.java': 'java', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.cs': 'csharp', '.php': 'php', '.rb': 'ruby', '.sh': 'sh',
        '.sql': 'sql', '.css': 'css', '.scss': 'scss', '.html': 'html', '.xml': 'xml', '.json': 'json', '.yaml': 'yaml',
        '.yml': 'yaml', '.toml': 'toml', '.ini': 'ini', '.tex': 'latex'}
TEXT = {'.txt', '.md', '.markdown', '.csv', '.tsv', '.log', '.srt', *CODE}
# Word: the Title style becomes a heading, like Heading 1, 2, 3.
WORD_STYLES = "p[style-name='Title'] => h1:fresh\np[style-name='Titre'] => h1:fresh"


class Refused(Exception):
    pass


def kind(path: str, extension: str) -> str:
    with open(path, 'rb') as file:
        head = file.read(8192)
    if head.startswith(b'%PDF'):
        return 'pdf'
    if extension == '.docx' and head.startswith(b'PK'):
        return 'docx'
    if extension in {'.xlsx', '.xls', '.pptx', '.ppt'}:
        raise Refused('Excel et PowerPoint ne sont pas encore pris en charge : enregistre le fichier en PDF.')
    if extension in {'.doc', '.odt', '.rtf', '.pages'}:
        raise Refused('Ce format n’est pas pris en charge : enregistre le document en .docx ou en PDF.')
    if extension in TEXT and b'\0' not in head:
        return 'text'
    raise Refused('Format non pris en charge. Envoie un PDF, un document Word (.docx) ou un fichier texte '
                  '(texte, Markdown, CSV, JSON, code).')


def invisible_layer(page) -> bool:
    """Scanned page with, under the image, the invisible text that scanners add (often wrong)."""
    import pypdfium2.raw as raw
    width, height = page.get_size()
    full_image, texts, invisible = False, 0, 0
    for item in page.get_objects(max_depth=4):
        if item.type == raw.FPDF_PAGEOBJ_IMAGE:
            left, bottom, right, top = item.get_bounds()
            full_image |= (right - left) * (top - bottom) >= 0.7 * width * height
        elif item.type == raw.FPDF_PAGEOBJ_TEXT:
            texts += 1
            invisible += raw.FPDFTextObj_GetTextRenderMode(item.raw) == raw.FPDF_TEXTRENDERMODE_INVISIBLE
    return full_image and texts > 0 and invisible * 2 >= texts


def unreadable(text: str) -> float:
    """Share of characters that well extracted text does not contain: broken font encoding."""
    useful = sum(1 for c in text if not c.isspace())
    if not useful:
        return 0.0
    bad = sum(1 for c in text if c == '�' or '' <= c <= '' or (unicodedata.category(c) == 'Cc' and not c.isspace()))
    # UTF-8 read as Latin-1 (« Ã© » for « é »), glyphs without a Unicode mapping.
    bad += 3 * len(re.findall('Ã[\u0080-¿]|Â[ -¿]|â€', text))
    bad += 6 * len(re.findall(r'GLYPH<|\(cid:\d+\)', text))
    return bad / useful


def image_reason(text: str, layer: bool) -> str | None:
    """Why the page must be read on its image rather than from its text; None when the text is good."""
    if len(text.strip()) < 30:
        return 'sans texte'
    if layer:
        return 'texte invisible de scanner'
    if unreadable(text) > 0.05:
        return 'texte illisible'
    return None


def segment(words: list) -> list:
    """Words of a page (l, t, r, b, text; origin top left) grouped into segments: the words of one
    line, split where the gap is clearly wider than a space (table columns)."""
    rows = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        height = max(1, word[3] - word[1])
        if rows and abs(rows[-1][0][1] - word[1]) < height * 0.5:
            rows[-1].append(word)
        else:
            rows.append([word])
    segments = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        current = [row[0]]
        for previous, word in zip(row, row[1:]):
            if word[0] - previous[2] > 0.7 * max(word[3] - word[1], previous[3] - previous[1]):
                segments.append(current)
                current = []
            current.append(word)
        segments.append(current)
    return [[round(s[0][0]), round(s[0][1]), ' '.join(w[4] for w in s)] for s in segments]


def cells(path: str, unit: str) -> list:
    """Text cells of each page from Docling's PDF reader, without its models."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import NativePdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.native_pdf_pipeline import NativePdfPipeline
    options = NativePdfPipelineOptions(generate_page_images=False, generate_picture_images=False, text_cell_unit=unit)
    document = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={InputFormat.PDF: PdfFormatOption(
        pipeline_cls=NativePdfPipeline, pipeline_options=options)}).convert(path).document
    pages = {number: [] for number in document.pages}
    for item, _ in document.iterate_items():
        if getattr(item, 'text', '') and item.prov:
            prov = item.prov[0]
            box = prov.bbox.to_top_left_origin(document.pages[prov.page_no].size.height)
            pages[prov.page_no].append((box.l, box.t, box.r, box.b, item.text))
    return [pages[number] for number in sorted(pages)]


def analyse_pdf(path: str) -> dict:
    import logging
    import pypdfium2 as pdfium
    logging.disable(logging.WARNING)
    try:
        pdf = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as error:
        raise Refused('Ce PDF est protégé par un mot de passe.' if 'password' in str(error).lower() else 'Ce PDF est illisible ou abîmé.')
    count = len(pdf)
    if not count:
        raise Refused('Ce PDF ne contient aucune page.')
    if count > MAX_PAGES:
        raise Refused(f'Ce PDF a {count} pages : {MAX_PAGES} au maximum pour l’instant.')
    reasons = []
    for page in pdf:
        text = page.get_textpage()
        reasons.append(image_reason(text.get_text_bounded(), invisible_layer(page)))
        text.close(); page.close()
    pdf.close()
    words, lines = cells(path, 'word'), cells(path, 'line')
    if len(words) != count or len(lines) != count:
        raise Refused('Ce PDF est illisible ou abîmé.')
    return {'kind': 'pdf', 'pages': [{'image': reason, 'segments': segment(page_words), 'text': '\n'.join(c[4] for c in page_lines)}
                                     for reason, page_words, page_lines in zip(reasons, words, lines)]}


def retouch(markdown: str) -> str:
    """MarkItDown fixes: images (useless to Qwen, sometimes in base64) and Word tables without a
    header, rendered with an empty first row."""
    markdown = re.sub(r'!\[([^\]]*)\]\([^)]*\)', lambda m: f'[image : {m[1].strip()}]' if m[1].strip() else '[image]', markdown)
    return re.sub(r'^(\|(?: *\|)+)\n(\|(?: *:?-+:? *\|)+)\n(\|.*)$', r'\3\n\2', markdown, flags=re.M)


def analyse_docx(path: str) -> dict:
    from markitdown import MarkItDown
    return {'kind': 'docx', 'markdown': retouch(MarkItDown(enable_plugins=False).convert(path, style_map=WORD_STYLES).text_content).strip()}


def analyse_text(path: str, extension: str) -> dict:
    from charset_normalizer import from_path
    best = from_path(path).best()
    if best is None:
        raise Refused('Ce fichier texte n’a pas pu être décodé.')
    text = str(best).strip()
    if extension in CODE:
        fence = '`' * max(3, max((len(run) for run in re.findall('`+', text)), default=0) + 1)
        text = f'{fence}{CODE[extension]}\n{text}\n{fence}'
    return {'kind': 'text', 'markdown': text}


def analyse(path: str, extension: str) -> dict:
    found = kind(path, extension)
    result = analyse_pdf(path) if found == 'pdf' else analyse_docx(path) if found == 'docx' else analyse_text(path, extension)
    if result.get('markdown') == '' or result.get('pages') == []:
        raise Refused('Ce document ne contient aucun texte.')
    return result


def page(path: str, number: int, side: int) -> bytes:
    import io
    import pypdfium2 as pdfium
    if side not in SIDES:
        raise Refused('Définition non proposée.')
    pdf = pdfium.PdfDocument(path)
    if not 1 <= number <= len(pdf):
        raise Refused('Page inexistante.')
    item = pdf[number - 1]
    image = item.render(scale=side / max(item.get_size())).to_pil().convert('RGB')
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=90)
    return output.getvalue()


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_AS, (1536 << 20, 1536 << 20))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    try:
        if sys.argv[1] == 'analyse':
            json.dump(analyse(sys.argv[2], sys.argv[3]), sys.stdout, ensure_ascii=False)
        else:
            sys.stdout.buffer.write(page(sys.argv[2], int(sys.argv[3]), int(sys.argv[4])))
    except Refused as error:
        json.dump({'error': str(error)}, sys.stdout, ensure_ascii=False)
        sys.exit(3)
