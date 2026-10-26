"""Audit CSV and listing tests use the disposable test database only."""
import csv
import io

import pytest


def login(client, username="testadmin"):
    response = client.post('/api/login', json={'username':username, 'password':'Password123!'})
    assert response.status_code == 200


def seed(client, db):
    login(client)
    with db.cursor() as cur:
        cur.execute('DELETE FROM AUDIT_EVENT')
        cur.executemany('''INSERT INTO AUDIT_EVENT
            (audit_event_id, category, success, sponsor_id, subject_username, reason_or_details, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''', [
                (101, 'LOGIN', 1, 900001, 'alice', 'Signed in', '2026-10-01 00:00:00'),
                (102, 'LOGIN', 0, 900002, 'bob', 'Failed', '2026-10-02 12:00:00'),
                (103, 'LOGIN', 0, 900001, 'Zoë', 'Comma, "quotes"\nand newline', '2026-10-02 23:59:59'),
                (104, 'POINT_CHANGE', 1, 900001, None, None, '2026-10-03 00:00:00'),
                (105, 'ACCOUNT', 1, None, '=1+1', '\t=HYPERLINK("x")', '2026-10-02 23:59:59'),
            ])


def csv_rows(response):
    assert response.status_code == 200
    return list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))


def test_combined_filters_match_table_and_csv(client, db):
    seed(client, db)
    filters = '?category=LOGIN&success=0&sponsor_id=900001&start_date=2026-10-01&end_date=2026-10-02'
    listing = client.get('/api/admin/audit'+filters).get_json()
    exported = csv_rows(client.get('/api/admin/audit/export.csv'+filters))
    assert [r['audit_event_id'] for r in listing['entries']] == [103]
    assert [int(r['Event ID']) for r in exported] == [103]
    assert exported[0]['Subject username'] == 'Zoë'
    assert exported[0]['Details'] == 'Comma, "quotes"\nand newline'
    assert exported[0]['Result'] == 'Failed'
    assert listing['categories'] == ['ACCOUNT','LOGIN','POINT_CHANGE']


def test_date_boundaries_and_deterministic_order(client, db):
    seed(client, db)
    rows = csv_rows(client.get('/api/admin/audit/export.csv?start_date=2026-10-01&end_date=2026-10-02'))
    assert [int(r['Event ID']) for r in rows] == [105,103,102,101]


def test_export_headers_and_formula_safety(client, db):
    seed(client, db)
    response = client.get('/api/admin/audit/export.csv')
    rows = csv_rows(response)
    assert response.mimetype == 'text/csv'
    assert response.data.startswith(b'\xef\xbb\xbf')
    assert 'attachment; filename="audit-log-' in response.headers['Content-Disposition']
    assert response.headers['Cache-Control'] == 'no-store'
    row = next(r for r in rows if r['Event ID']=='105')
    assert row['Subject username'] == "'=1+1"
    assert row['Details'].startswith("'\t=")
    assert row['Sponsor'] == '' and row['Actor ID'] == ''


@pytest.mark.parametrize('query', ['success=maybe','sponsor_id=abc','sponsor_id=-1',
    'start_date=2026-02-30','end_date=20261020',
    'start_date=2026-10-03&end_date=2026-10-01'])
def test_invalid_filters_rejected_on_both_endpoints(client, query):
    login(client)
    for endpoint in ('', '/export.csv'):
        response = client.get('/api/admin/audit'+endpoint+'?'+query)
        assert response.status_code == 400
        assert 'error' in response.get_json()


@pytest.mark.parametrize('username', [None, 'testdriver', 'testsponsor'])
def test_only_admin_can_read_or_export(client, username):
    if username:
        login(client, username)
    for endpoint in ('', '/export.csv'):
        assert client.get('/api/admin/audit'+endpoint).status_code == (403 if username else 401)


def test_empty_export_still_has_headers(client, db):
    seed(client, db)
    response = client.get('/api/admin/audit/export.csv?category=NOT_PRESENT')
    assert csv_rows(response) == []
    assert 'Event ID' in response.data.decode('utf-8-sig')


def test_export_has_no_page_limit(client, db):
    seed(client, db)
    with db.cursor() as cur:
        cur.executemany("INSERT INTO AUDIT_EVENT (category,success) VALUES (%s,%s)", [('BULK',1)]*250)
    assert len(csv_rows(client.get('/api/admin/audit/export.csv?category=BULK'))) == 250


def test_production_does_not_require_bootstrap(client, db, monkeypatch):
    seed(client, db)
    monkeypatch.setenv('APP_ENV', 'production')
    assert client.get('/api/bootstrap').status_code == 404
    assert client.get('/api/admin/audit').status_code == 200
    assert len(csv_rows(client.get('/api/admin/audit/export.csv'))) == 5
