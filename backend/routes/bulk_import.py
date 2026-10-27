"""RC#1 pipe-delimited imports. Each line commits or rolls back independently."""
import re
import secrets

import mysql.connector
from flask import Blueprint, g, jsonify, request

from accounts import AccountError, clean_profile, create_user
from audit import log_audit
from auth import require_role
from db import transaction
from points import PointsError, change_points

bp = Blueprint('bulk_import', __name__, url_prefix='/api/bulk-import')


def parse_line(text, role):
    # Pipes are literal separators, not CSV quoting/escaping. Preserve empty columns.
    fields = text.removesuffix('\r').split('|')
    kind = fields[0]
    if kind not in ('O', 'D', 'S'):
        raise AccountError('Record type must be O, D, or S (no header row).')
    if kind == 'O':
        if role != 'admin':
            raise AccountError('Only administrators can import organizations.')
        if len(fields) < 2 or len(fields) > 7 or any(fields[2:]):
            raise AccountError('Organization records must contain O|organization name only.')
        name = fields[1].strip()
        if not name or len(name) > 100:
            raise AccountError('Organization name is required and must fit the existing 100-character field.')
        return {'kind': kind, 'organization': name, 'warnings': []}
    if not 5 <= len(fields) <= 7:
        raise AccountError('Expected type|organization|first name|last name|email[|points|reason].')
    fields += [''] * (7 - len(fields))
    _, org, first, last, email, points, reason = fields
    warnings = []
    if role == 'sponsor' and org:
        warnings.append('Organization field must be empty; its value was ignored. Your organization was used.')
    if role == 'admin' and not org.strip():
        raise AccountError('Organization name is required for administrator imports.')
    delta = None
    if kind == 'S':
        if points or reason:
            warnings.append('Sponsor users cannot receive points; points and reason were ignored.')
    elif points.strip():
        if not re.fullmatch(r'[+-]?[0-9]+', points.strip()):
            raise AccountError('Points must be a whole number.')
        if len(points.strip().lstrip('+-')) > 19:
            raise AccountError('Points exceed the supported balance range.')
        delta = int(points)
        if not -9223372036854775808 <= delta <= 9223372036854775807:
            raise AccountError('Points exceed the supported balance range.')
        if not reason.strip():
            raise AccountError('A reason is required whenever points are supplied.')
        if len(reason.strip()) > 500:
            raise AccountError('Reason must fit the existing 500-character field.')
    first, last, email, _ = clean_profile(first, last, email, None)
    return dict(kind=kind, organization=org.strip(), first=first, last=last, email=email,
                points=delta, reason=reason.strip(), warnings=warnings)


def apply_record(cur, row, actor):
    if row['kind'] == 'O':
        cur.execute('SELECT sponsor_id FROM SPONSOR_ORGANIZATION WHERE sponsor_name = %s FOR UPDATE',
                    (row['organization'],))
        existing = cur.fetchall()
        if existing:
            raise AccountError('An organization with that name already exists.')
        cur.execute("INSERT INTO SPONSOR_ORGANIZATION (sponsor_name, status, point_dollar_rate) VALUES (%s, 'ACTIVE', 0.01)",
                    (row['organization'],))
        sid = cur.lastrowid
        log_audit(cur, 'ACCOUNT', True, actor_user_id=actor['user_id'], sponsor_id=sid,
                  entity_type='SPONSOR_ORGANIZATION', entity_id=sid, details='Organization created by RC#1 bulk import')
        return {'message': 'Organization created (1 point = $0.01).'}

    if actor['role'] == 'sponsor':
        cur.execute('SELECT sponsor_id, status FROM SPONSOR_ORGANIZATION WHERE sponsor_id = %s FOR UPDATE',
                    (actor['sponsor_id'],))
    else:
        cur.execute('SELECT sponsor_id, status FROM SPONSOR_ORGANIZATION WHERE sponsor_name = %s FOR UPDATE',
                    (row['organization'],))
    orgs = cur.fetchall()
    if len(orgs) != 1:
        raise AccountError('Organization must exist uniquely before this line; create it with an earlier O record.')
    if orgs[0]['status'] != 'ACTIVE':
        raise AccountError('Organization is not active.')
    sid = orgs[0]['sponsor_id']
    cur.execute('''SELECT u.user_id, u.username, u.account_status, d.driver_id, su.sponsor_user_id,
                   su.sponsor_id, a.admin_id FROM USER_ACCOUNT u
                   LEFT JOIN DRIVER d ON d.driver_id = u.user_id
                   LEFT JOIN SPONSOR_USER su ON su.sponsor_user_id = u.user_id
                   LEFT JOIN ADMIN a ON a.admin_id = u.user_id
                   WHERE u.email = %s FOR UPDATE''', (row['email'],))
    user = cur.fetchone()
    result = {}
    if user:
        if user['account_status'] != 'ACTIVE':
            raise AccountError('Existing account is locked or inactive; an administrator must review it.')
        if user['admin_id'] or (row['kind'] == 'D' and not user['driver_id']) or (row['kind'] == 'S' and not user['sponsor_user_id']):
            raise AccountError('Email belongs to a different account role; no changes made.')
        if row['kind'] == 'S' and user['sponsor_id'] != sid:
            raise AccountError('Existing sponsor user belongs to another organization; no changes made.')
        uid = user['user_id']
        result['message'] = 'Existing user processed; login and profile unchanged.'
    else:
        username = 'import_' + secrets.token_hex(10)
        password = 'Aa1!' + secrets.token_urlsafe(18)
        uid = create_user(cur, 'driver' if row['kind'] == 'D' else 'sponsor', username=username,
                          password=password, first_name=row['first'], last_name=row['last'], email=row['email'],
                          sponsor_id=sid, created_by=actor['user_id'])
        result.update(message='User created.', username=username, initial_password=password, email=row['email'])
    if row['kind'] == 'D':
        cur.execute('''INSERT INTO DRIVER_SPONSOR (driver_id, sponsor_id, participation_status)
                       VALUES (%s, %s, 'ACTIVE') ON DUPLICATE KEY UPDATE participation_status = 'ACTIVE' ''', (uid, sid))
        cur.execute('''UPDATE DRIVER_APPLICATION SET status = 'APPROVED', decision_at = CURRENT_TIMESTAMP,
                       decided_by_user_id = %s, reason = 'Accepted by bulk import'
                       WHERE driver_id = %s AND sponsor_id = %s AND status = 'PENDING' ''', (actor['user_id'], uid, sid))
        if row['points']:
            result.update(change_points(cur, uid, sid, row['points'], row['reason'], performed_by=actor['user_id']))
        result['message'] += ' Driver is active in this organization.'
    log_audit(cur, 'ACCOUNT', True, actor_user_id=actor['user_id'], sponsor_id=sid,
              driver_id=uid if row['kind'] == 'D' else None, entity_type='USER_ACCOUNT', entity_id=uid,
              details='User processed by RC#1 bulk import')
    return result


@bp.post('')
@require_role('admin', 'sponsor')
def import_lines():
    # The browser streams the file into small batches, with no total-file limit.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Provide a batch of numbered lines.'), 400
    lines = data.get('lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 20 or any(
        not isinstance(r, dict) or type(r.get('number')) is not int or r['number'] < 1
        or not isinstance(r.get('text'), str) or '\n' in r['text'] for r in lines
    ):
        return jsonify(error='Provide 1–20 records with a positive line number and text.'), 400
    results = []
    for line in lines:
        result = {'line': line['number'], 'warnings': []}
        try:
            row = parse_line(line['text'].lstrip('\ufeff') if line['number'] == 1 else line['text'], g.user['role'])
            result['warnings'] = row['warnings']
            with transaction() as cur:
                applied = apply_record(cur, row, g.user)
            result.update(applied, status='warning' if row['warnings'] else 'success')
        except (AccountError, PointsError) as error:
            result.update(status='error', message=str(error))
        except (mysql.connector.IntegrityError, mysql.connector.DataError):
            result.update(status='error', message='Record conflicts with existing data or exceeds a database field. No changes made to this line.')
        results.append(result)
    response = jsonify(results=results)
    response.headers['Cache-Control'] = 'no-store'
    return response
