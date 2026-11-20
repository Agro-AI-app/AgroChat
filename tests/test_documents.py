import unittest

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from agrochat.documents import render


class DocumentTests(unittest.TestCase):
    def test_spreadsheet_preserves_data_types(self):
        sheet = load_workbook(render('xlsx', 'Field data', 'Code,Yield,Note\n007,12.5,"=literal, text"')).active
        self.assertEqual([cell.value for cell in sheet[2]], ['007', 12.5, '=literal, text'])
        self.assertEqual(sheet['C2'].data_type, 's')

    def test_report_formats_can_be_reopened(self):
        content = '# Results\nYield < forecast\n# Notes\n- Check moisture'
        doc = Document(render('docx', 'Trial', content))
        self.assertIn('Yield < forecast', [p.text for p in doc.paragraphs])
        pdf = PdfReader(render('pdf', 'Trial', content))
        self.assertIn('Yield < forecast', pdf.pages[0].extract_text())
        deck = Presentation(render('pptx', 'Trial', content))
        self.assertEqual([s.shapes.title.text for s in deck.slides], ['Results', 'Notes'])
