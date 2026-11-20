"""Managed document writers. Tool input is content, never executable code or a host path."""
import asyncio
import csv
import io
import json
import mimetypes
import re
from xml.sax.saxutils import escape

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font
from pptx import Presentation
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate
from starlette.datastructures import Headers, UploadFile


FORMATS = ('docx', 'xlsx', 'pdf', 'pptx')


def render(kind, title, content):
    if kind not in FORMATS or not (0 < len(title.strip()) <= 120 and 0 < len(content.strip()) <= 100_000):
        raise ValueError('Choose a supported format, a title up to 120 characters and content up to 100,000 characters.')
    out = io.BytesIO()
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if kind == 'xlsx':
        book = Workbook()
        sheet = book.active
        for r, row in enumerate(csv.reader(io.StringIO(content), strict=True), 1):
            if r > 5000 or len(row) > 256:
                raise ValueError('The worksheet limit is 5,000 rows and 256 columns.')
            for c, text in enumerate(row, 1):
                cell = sheet.cell(r, c)
                if re.fullmatch(r'-?(?:0|[1-9]\d{0,12})(?:\.\d{1,8})?', text):
                    cell.value = float(text) if '.' in text else int(text)
                else:
                    cell.value = text
                    cell.data_type = 's'  # Keep formula-like user data literal.
                if r == 1:
                    cell.font = Font(bold=True)
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        book.save(out)
    elif kind == 'docx':
        doc = Document()
        doc.add_heading(title, 0)
        for line in lines:
            if line.startswith('#'):
                doc.add_heading(line.lstrip('# '), level=2 if line.startswith('##') else 1)
            else:
                if line.startswith('- '):
                    doc.add_paragraph(line[2:], style='List Bullet')
                else:
                    doc.add_paragraph(line)
        doc.save(out)
    elif kind == 'pdf':
        styles = getSampleStyleSheet()
        flow = [Paragraph(escape(title), styles['Title'])]
        for line in lines:
            flow.append(Paragraph(escape(line.lstrip('# ') if line.startswith('#') else line),
                                  styles['Heading2' if line.startswith('#') else 'BodyText']))
        SimpleDocTemplate(out, title=title).build(flow)
    else:
        if sum(line.startswith('#') for line in lines) + int(not lines[0].startswith('#')) > 80:
            raise ValueError('A presentation can contain up to 80 slides.')
        slides = Presentation()
        slide = None
        for line in lines:
            if slide is None or line.startswith('#'):
                slide = slides.slides.add_slide(slides.slide_layouts[1])
                slide.shapes.title.text = line.lstrip('# ') if line.startswith('#') else title
                body = slide.placeholders[1].text_frame
                if line.startswith('#'):
                    continue
            paragraph = body.add_paragraph() if body.text else body.paragraphs[0]
            paragraph.text = line.removeprefix('- ')
        slides.save(out)
    out.seek(0)
    return out


def document_tool(request, params):
    from open_webui.models.chats import Chats
    from open_webui.models.files import Files
    from open_webui.models.users import UserModel
    from open_webui.routers.files import upload_file_handler

    async def create_document(format: str, title: str, content: str):
        buf = await asyncio.to_thread(render, format, title, content)
        name = (re.sub(r'[^\w .-]', '_', title)[:80].strip(' .') or 'Document') + '.' + format
        with buf:
            upload = UploadFile(buf, filename=name, headers=Headers({'content-type': mimetypes.guess_type(name)[0]}))
            file = await upload_file_handler(request, upload, metadata={}, process=False, user=UserModel(**params['__user__']))
        # Native file tools can read this text on reattachment without re-extracting the binary.
        await Files.update_file_data_by_id(file.id, {'content': content, 'status': 'completed'})
        entry = {'type': 'file', 'id': file.id, 'name': name, 'url': f'/api/v1/files/{file.id}/content',
                 'size': file.meta['size'], 'content_type': file.meta['content_type']}
        chat, message = params.get('__chat_id__'), params.get('__message_id__')
        attachments = [entry]
        if chat and message and await Chats.get_chat_by_id_and_user_id(chat, params['__user__']['id']):
            attachments = await Chats.add_message_files_by_id_and_message_id(chat, message, attachments) or attachments
        if emit := params.get('__event_emitter__'):
            await emit({'type': 'chat:message:files', 'data': {'files': attachments}})
        return json.dumps({'filename': name, 'download_url': entry['url']})

    return {'tool_id': 'builtin:create_document', 'type': 'builtin', 'callable': create_document,
            'spec': {'name': 'create_document', 'description': 'Create and attach a downloadable Word document, Excel spreadsheet, PDF or PowerPoint to this reply. Use for requested files; link the returned download_url.',
                     'parameters': {'type': 'object', 'required': ['format', 'title', 'content'], 'properties': {
                         'format': {'type': 'string', 'enum': list(FORMATS)}, 'title': {'type': 'string'},
                         'content': {'type': 'string', 'description': 'Excel: CSV including a header, literal values. Word/PDF: paragraphs on separate lines, # section headings. PowerPoint: # starts each slide, followed by short bullet lines.'}}}}}
