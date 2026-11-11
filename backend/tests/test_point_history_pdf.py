"""PDF rendering and HTTP access checks with no database required."""
from datetime import datetime
from io import BytesIO
import unittest
from unittest.mock import patch

from flask import Flask, g
from pypdf import PdfReader

from point_history_pdf import build_point_history_pdf
from routes.driver_commerce import bp


class PointHistoryPdfTests(unittest.TestCase):
    def setUp(self):
        self.user = dict(user_id=10, role='driver', sponsor_id=20,
                         first_name='Jamie', last_name='Rivera', sponsor_name='Freight & Co <North>')
        self.rows = [dict(created_at=datetime(2026, 11, 11, 12, 0), reason='Safe driving <bonus> & award',
                          points_delta=100, balance_after=100)]
        app = Flask(__name__)
        app.register_blueprint(bp)
        app.testing = True
        self.client = app.test_client()

    def current_user(self):
        g.user = self.user
        g.viewed_by = None
        return self.user

    def test_download_scopes_query_to_authenticated_driver_and_sponsor(self):
        with patch('auth.current_user', side_effect=self.current_user), \
                patch('routes.driver_commerce.query', return_value=self.rows) as query:
            response = self.client.get('/api/driver/points/export.pdf?driver_id=999&sponsor_id=999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(query.call_args.args[1], (10, 20))
        self.assertIn('driver_id = %s AND sponsor_id = %s', query.call_args.args[0])
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        text = PdfReader(BytesIO(response.data)).pages[0].extract_text()
        for expected in ['Jamie Rivera', 'Freight & Co <North>', 'Safe driving <bonus> & award', '+100']:
            self.assertIn(expected, text)

    def test_rejects_anonymous_and_other_roles(self):
        with patch('auth.current_user', return_value=None):
            self.assertEqual(self.client.get('/api/driver/points/export.pdf').status_code, 401)
        for role in ['sponsor', 'admin']:
            self.user['role'] = role
            with patch('auth.current_user', side_effect=self.current_user):
                self.assertEqual(self.client.get('/api/driver/points/export.pdf').status_code, 403)

    def test_no_selected_sponsor(self):
        self.user['sponsor_id'] = None
        with patch('auth.current_user', side_effect=self.current_user), \
                patch('routes.driver_commerce.query') as query:
            self.assertEqual(self.client.get('/api/driver/points/export.pdf').status_code, 400)
            query.assert_not_called()

    def test_empty_history(self):
        pdf = PdfReader(build_point_history_pdf(self.user, []))
        self.assertIn('No point transactions', pdf.pages[0].extract_text())

    def test_pagination_and_long_reasons(self):
        rows = [dict(self.rows[0], reason=f'Record {i}: ' + 'Long reason ' * 40,
                     points_delta=-10, balance_after=1000 - i * 10) for i in range(60)]
        pdf = PdfReader(build_point_history_pdf(self.user, rows))
        self.assertGreater(len(pdf.pages), 1)
        text = '\n'.join(page.extract_text() for page in pdf.pages)
        for i in range(60):
            self.assertIn(f'Record {i}:', text)
        for number, page in enumerate(pdf.pages, 1):
            self.assertIn('Date / time*', page.extract_text())
            self.assertIn(f'Page {number}', page.extract_text())

    def test_reason_with_many_line_breaks_can_split_across_pages(self):
        row = dict(self.rows[0], reason='x\n' * 249)
        pdf = PdfReader(build_point_history_pdf(self.user, [row]))
        self.assertGreater(len(pdf.pages), 1)
