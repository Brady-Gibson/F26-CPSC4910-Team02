"""RC#1 imports exercised against the isolated MySQL test database."""
import pytest
from werkzeug.security import check_password_hash
from test_driver_applications import login, one


def upload(client, *lines):
    r = client.post('/api/bulk-import', json={'lines': [dict(number=i+1, text=s) for i,s in enumerate(lines)]})
    assert r.status_code == 200
    assert r.headers['Cache-Control'] == 'no-store'
    return r.get_json()['results']


def test_admin_ordered_creation_credentials_and_acceptance(client, db):
    login(client, 'testadmin')
    rows = upload(client, 'D|New Fleet|Too|Soon|early@example.com', 'O|New Fleet',
                  'D|New Fleet|Jane|Driver|jane@example.com|25|Safe driving',
                  'S|New Fleet|Jim|Sponsor|jim@example.com|100|Ignored')
    assert [r['status'] for r in rows] == ['error','success','success','warning']
    assert not one(db, "SELECT user_id FROM USER_ACCOUNT WHERE email='early@example.com'")
    u = one(db, "SELECT * FROM USER_ACCOUNT WHERE email='jane@example.com'")
    assert check_password_hash(u['password_hash'], rows[2]['initial_password'])
    assert u['username'] == rows[2]['username']
    membership = one(db, 'SELECT * FROM DRIVER_SPONSOR WHERE driver_id=%s', u['user_id'])
    assert membership['participation_status'] == 'ACTIVE' and membership['current_points'] == 25
    assert 'initial_password' in rows[3]
    assert not one(db, "SELECT point_transaction_id FROM POINT_TRANSACTION WHERE reason='Ignored'")


def test_sponsor_scope_and_ignored_fields(client, db):
    login(client, 'testsponsor')
    rows=upload(client, 'O|Forbidden', 'D|Second Test Freight|New|Driver|bulk@example.com|10|Bonus',
                'S||Team|Member|member@example.com|not-a-number|',
                'S||Second|Sponsor|second@example.com')
    assert [r['status'] for r in rows] == ['error','warning','warning','error']
    u=one(db,"SELECT user_id FROM USER_ACCOUNT WHERE email='bulk@example.com'")
    m=one(db,'SELECT * FROM DRIVER_SPONSOR WHERE driver_id=%s',u['user_id'])
    assert m['sponsor_id']==900001 and m['current_points']==10
    assert not one(db,"SELECT sponsor_id FROM SPONSOR_ORGANIZATION WHERE sponsor_name='Forbidden'")
    assert one(db,'SELECT sponsor_id FROM SPONSOR_USER WHERE sponsor_user_id=900005')['sponsor_id']==900002


def test_existing_driver_additive_and_other_membership_unchanged(client, db):
    login(client,'testsponsor')
    before=one(db,'SELECT password_hash FROM USER_ACCOUNT WHERE user_id=900003')['password_hash']
    rows=upload(client,'D||Test|Driver|testdriver@example.com|25|Bonus',
                'D||Test|Driver|testdriver@example.com|-10|Correction')
    assert all(r['status']=='success' and 'initial_password' not in r for r in rows)
    assert one(db,'SELECT current_points FROM DRIVER_SPONSOR WHERE driver_id=900003 AND sponsor_id=900001')['current_points']==515
    assert one(db,'SELECT current_points FROM DRIVER_SPONSOR WHERE driver_id=900003 AND sponsor_id=900010')['current_points']==200
    assert one(db,'SELECT password_hash FROM USER_ACCOUNT WHERE user_id=900003')['password_hash']==before


def test_new_membership_accepts_pending_application(client, db):
    login(client,'secondsponsor')
    cur=db.cursor();cur.execute("INSERT INTO DRIVER_APPLICATION (driver_id,sponsor_id,status) VALUES (900003,900002,'PENDING')")
    rows=upload(client,'D||Test|Driver|testdriver@example.com|5|Welcome')
    assert rows[0]['status']=='success'
    assert one(db,'SELECT current_points FROM DRIVER_SPONSOR WHERE driver_id=900003 AND sponsor_id=900002')['current_points']==5
    assert one(db,'SELECT status FROM DRIVER_APPLICATION WHERE driver_id=900003 AND sponsor_id=900002')['status']=='APPROVED'


def test_bad_lines_rollback_and_continue(client, db):
    login(client,'testsponsor')
    rows=upload(client,'X||A|B|bad@example.com', 'D||A|B|missing@example.com|10',
                'D||A|B|negative@example.com|-1|Penalty', 'D||A|B|valid@example.com|0|Starting',
                'D||Test|Admin|testadmin@example.com', 'D||A|B|extra@example.com|1|reason|extra')
    assert [r['status'] for r in rows]==['error','error','error','success','error','error']
    assert not one(db,"SELECT user_id FROM USER_ACCOUNT WHERE email='negative@example.com'")
    assert one(db,"SELECT user_id FROM USER_ACCOUNT WHERE email='valid@example.com'")


def test_bom_unicode_and_optional_fields(client, db):
    login(client,'testsponsor')
    rows=upload(client,'\ufeffD||Zoë|O’Neil|zoe@example.com||\r','D||Jill|Smith|jill@example.com')
    assert all(r['status']=='success' for r in rows)
    assert one(db,"SELECT first_name FROM USER_ACCOUNT WHERE email='zoe@example.com'")['first_name']=='Zoë'


def test_roles_and_view_as_cannot_write(client):
    assert client.post('/api/bulk-import',json={'lines':[]}).status_code==401
    login(client,'testdriver')
    assert client.post('/api/bulk-import',json={'lines':[]}).status_code==403
    login(client,'testadmin')
    assert client.post('/api/view-as',json={'user_id':900002}).status_code==200
    assert client.post('/api/bulk-import',json={'lines':[]}).status_code==403


@pytest.mark.parametrize('payload',[None,[],{'lines':[]},{'lines':[{'number':0,'text':'O|x'}]},
                                   {'lines':[{'number':1,'text':'O|x\nO|y'}]}])
def test_invalid_batch_shape(client,payload):
    login(client,'testadmin')
    assert client.post('/api/bulk-import',json=payload).status_code==400


def test_duplicate_org_and_inactive_org(client,db):
    login(client,'testadmin')
    cur=db.cursor();cur.execute("UPDATE SPONSOR_ORGANIZATION SET status='INACTIVE' WHERE sponsor_id=900002")
    rows=upload(client,'O|Tiger Test Trucking','D|Second Test Freight|A|B|inactive@example.com',
                'D|Missing|A|B|missing@example.com')
    assert all(r['status']=='error' for r in rows)
