"""Printable, paginated point history for one driver's selected sponsor."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


# Embed ReportLab's bundled font so the PDF is independent of server fonts.
pdfmetrics.registerFont(TTFont('History', str(Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf')))


def build_point_history_pdf(user, transactions):
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=letter, rightMargin=36, leftMargin=36,
                                 topMargin=36, bottomMargin=40, title='Point history')
    body = ParagraphStyle('body', fontName='History', fontSize=9, leading=13)
    title = ParagraphStyle('title', parent=body, fontSize=22, leading=28,
                           textColor=colors.HexColor('#18344f'))

    def paragraph(value):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), body)

    generated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    content = [Paragraph('Point history', title), Spacer(1, 12),
               paragraph(f"Driver: {user['first_name']} {user['last_name']}"),
               paragraph(f"Sponsor: {user['sponsor_name']}"),
               paragraph(f'Generated: {generated}'),
               paragraph(f'Transactions: {len(transactions)} | Newest first'), Spacer(1, 16)]
    if transactions:
        rows = [['Date / time*', 'Reason', 'Points change', 'Balance after']]
        for item in transactions:
            rows.append([paragraph(item['created_at'].strftime('%Y-%m-%d\n%H:%M:%S')),
                         paragraph(item['reason']),
                         paragraph(f"{item['points_delta']:+,}"),
                         paragraph(f"{item['balance_after']:,}")])
        table = LongTable(rows, colWidths=[100, 250, 95, 95], repeatRows=1,
                          splitInRow=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'History'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#18344f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        content.extend([table, Spacer(1, 10), paragraph('*Transaction times are shown as recorded by the server.')])
    else:
        content.append(paragraph('No point transactions with this sponsor.'))

    def footer(canvas, doc):
        canvas.setFont('History', 8)
        canvas.setFillColor(colors.HexColor('#526171'))
        canvas.drawString(36, 22, 'Tiger Trucking | Point history')
        canvas.drawRightString(576, 22, f'Page {doc.page}')

    document.build(content, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
