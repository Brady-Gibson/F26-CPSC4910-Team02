"""Real MySQL checks for the database-only RC#2 contract.

RC2_TEST_SOCKET must point to an isolated local test server. Each test creates
and removes its own uniquely named database; it never loads backend/.env.
"""
import os
from pathlib import Path
import uuid

import mysql.connector
import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_sql(conn, path):
    """Support mysql-client DELIMITER directives, including migration routines."""
    delimiter = ';'
    pending = []
    with conn.cursor() as cur:
        for line in Path(path).read_text().splitlines():
            text = line.strip()
            if not text or text.startswith('--') or text.upper().startswith('USE '):
                continue
            if text.upper().startswith('DELIMITER '):
                assert not pending
                delimiter = text.split()[1]
                continue
            pending.append(line)
            if text.endswith(delimiter):
                sql = '\n'.join(pending).rstrip()[:-len(delimiter)]
                cur.execute(sql)
                while cur.nextset():
                    pass
                pending = []
        assert not pending, f'Unterminated SQL in {path}'


@pytest.fixture
def conn():
    socket = os.environ.get('RC2_TEST_SOCKET')
    host = os.environ.get('RC2_TEST_HOST')
    if not socket and not host:
        pytest.skip('Set RC2_TEST_SOCKET or RC2_TEST_HOST for isolated local MySQL')
    if host and host not in ('localhost', '127.0.0.1', '::1'):
        pytest.fail('RC2 tests only accept a local server')
    address = {'unix_socket': socket} if socket else {'host': host, 'port': int(os.environ.get('RC2_TEST_PORT', '3306'))}
    name = 'rc2_test_' + uuid.uuid4().hex
    db = mysql.connector.connect(**address,
                                 user=os.environ.get('RC2_TEST_USER', 'root'),
                                 password=os.environ.get('RC2_TEST_PASSWORD', ''),
                                 autocommit=True)
    with db.cursor() as cur:
        cur.execute(f'CREATE DATABASE `{name}`')
        cur.execute(f'USE `{name}`')
    try:
        yield db
    finally:
        with db.cursor() as cur:
            cur.execute(f'DROP DATABASE `{name}`')
        db.close()


def execute(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.with_rows else None


def fresh(conn):
    run_sql(conn, ROOT / 'schema.sql')
    run_sql(conn, ROOT / 'seed_test_data.sql')


def legacy(conn):
    run_sql(conn, ROOT / 'tests/fixtures/legacy_schema.sql')
    run_sql(conn, ROOT / 'tests/fixtures/legacy_seed.sql')
    run_sql(conn, ROOT / 'migrations/001_driver_application_details.sql')


def migrate(conn):
    run_sql(conn, ROOT / 'migrations/002_multiple_sponsors.sql')


def test_fresh_balances_are_separate(conn):
    fresh(conn)
    assert execute(conn, 'SELECT sponsor_id,current_points FROM DRIVER_SPONSOR ORDER BY sponsor_id') == [(900001, 500), (900010, 200)]
    # The application must use an atomic conditional debit for the selected pair.
    execute(conn, 'UPDATE DRIVER_SPONSOR SET current_points=current_points-600 WHERE driver_id=900003 AND sponsor_id=900001 AND current_points>=600')
    assert execute(conn, 'SELECT current_points FROM DRIVER_SPONSOR ORDER BY sponsor_id') == [(500,), (200,)]
    execute(conn, 'UPDATE DRIVER_SPONSOR SET current_points=current_points-100 WHERE driver_id=900003 AND sponsor_id=900001 AND current_points>=100')
    assert execute(conn, 'SELECT current_points FROM DRIVER_SPONSOR ORDER BY sponsor_id') == [(400,), (200,)]
    with pytest.raises(mysql.connector.Error):
        execute(conn, 'UPDATE DRIVER_SPONSOR SET current_points=-1 WHERE driver_id=900003 AND sponsor_id=900001')


def test_membership_uniqueness_and_foreign_keys(conn):
    fresh(conn)
    for driver, sponsor in [(900003, 900001), (999999, 900001), (900003, 999999)]:
        with pytest.raises(mysql.connector.IntegrityError):
            execute(conn, "INSERT INTO DRIVER_SPONSOR(driver_id,sponsor_id,participation_status) VALUES(%s,%s,'ACTIVE')", (driver, sponsor))


def test_applications_independent_and_pending_unique(conn):
    fresh(conn)
    for sid in (900001, 900010):
        execute(conn, "INSERT INTO DRIVER_APPLICATION(driver_id,sponsor_id,status) VALUES(900003,%s,'PENDING')", (sid,))
    with pytest.raises(mysql.connector.IntegrityError):
        execute(conn, "INSERT INTO DRIVER_APPLICATION(driver_id,sponsor_id,status) VALUES(900003,900010,'PENDING')")
    execute(conn, "UPDATE DRIVER_APPLICATION SET status='REJECTED' WHERE driver_id=900003 AND sponsor_id=900001 AND status='PENDING'")
    execute(conn, "INSERT INTO DRIVER_APPLICATION(driver_id,sponsor_id,status) VALUES(900003,900001,'PENDING')")
    assert execute(conn, "SELECT COUNT(*) FROM DRIVER_APPLICATION WHERE sponsor_id=900010 AND status='PENDING'") == [(1,)]
    assert execute(conn, 'SELECT current_points FROM DRIVER_SPONSOR ORDER BY sponsor_id') == [(500,), (200,)]


def test_carts_and_order_items_cannot_mix_sponsors(conn):
    fresh(conn)
    for sql in [
        'INSERT INTO CART_ITEM VALUES(900001,900010,900001,1,250)',
        'INSERT INTO ORDER_ITEM VALUES(900001,2,900010,900001,1,250,5.00)',
        "INSERT INTO SHOPPING_CART(driver_id,sponsor_id,status) VALUES(900003,900010,'ACTIVE')",
    ]:
        with pytest.raises(mysql.connector.IntegrityError):
            execute(conn, sql)
    # One active cart per sponsor is valid for the same driver.
    execute(conn, "INSERT INTO SHOPPING_CART(driver_id,sponsor_id,status) VALUES(900003,900001,'ACTIVE')")
    assert execute(conn, "SELECT COUNT(*) FROM SHOPPING_CART WHERE driver_id=900003 AND status='ACTIVE'") == [(2,)]


def test_financial_rows_require_membership_and_history_survives_drop(conn):
    fresh(conn)
    execute(conn, "INSERT INTO SPONSOR_ORGANIZATION(sponsor_id,sponsor_name,status,point_dollar_rate) VALUES(900020,'Unjoined','ACTIVE',0.01)")
    for sql in [
        "INSERT INTO POINT_TRANSACTION(driver_id,sponsor_id,points_delta,balance_after,reason) VALUES(900003,900020,10,10,'x')",
        "INSERT INTO RECURRING_POINT_SCHEDULE(driver_id,sponsor_id,created_by_user_id,points_amount,frequency) VALUES(900003,900020,900001,10,'MONTHLY')",
        "INSERT INTO SHOPPING_CART(driver_id,sponsor_id,status) VALUES(900003,900020,'ACTIVE')",
        "INSERT INTO CUSTOMER_ORDER(driver_id,sponsor_id,placed_by_user_id,status,total_points) VALUES(900003,900020,900003,'PLACED',10)",
    ]:
        with pytest.raises(mysql.connector.IntegrityError):
            execute(conn, sql)
    execute(conn, "UPDATE DRIVER_SPONSOR SET participation_status='DROPPED' WHERE driver_id=900003 AND sponsor_id=900001")
    assert execute(conn, 'SELECT participation_status,current_points FROM DRIVER_SPONSOR WHERE sponsor_id=900010') == [('ACTIVE', 200)]
    with pytest.raises(mysql.connector.IntegrityError):
        execute(conn, 'DELETE FROM DRIVER_SPONSOR WHERE driver_id=900003 AND sponsor_id=900001')


def test_migration_preserves_data_and_rejects_replay(conn):
    legacy(conn)
    # Preserve a dropped membership and a driver without a sponsor as well.
    execute(conn, "UPDATE DRIVER SET participation_status='DROPPED',joined_at='2020-01-02' WHERE driver_id=900003")
    execute(conn, "INSERT INTO USER_ACCOUNT(user_id,username,password_hash,first_name,last_name,email,account_status) VALUES(900004,'applicant','placeholder','A','B','a@b.test','ACTIVE')")
    execute(conn, "INSERT INTO DRIVER(driver_id,participation_status) VALUES(900004,'APPLICANT')")
    before = execute(conn, 'SELECT driver_id,sponsor_id,current_points,participation_status,joined_at FROM DRIVER WHERE sponsor_id IS NOT NULL')
    ledger = execute(conn, 'SELECT * FROM POINT_TRANSACTION ORDER BY point_transaction_id')
    migrate(conn)
    assert execute(conn, 'SELECT driver_id,sponsor_id,current_points,participation_status,joined_at FROM DRIVER_SPONSOR') == before
    assert execute(conn, 'SELECT * FROM POINT_TRANSACTION ORDER BY point_transaction_id') == ledger
    assert execute(conn, 'SELECT * FROM DRIVER_SPONSOR WHERE driver_id=900004') == []
    with pytest.raises(mysql.connector.Error, match='already applied'):
        migrate(conn)
    assert execute(conn, 'SELECT current_points FROM DRIVER_SPONSOR') == [(500,)]


@pytest.mark.parametrize('conflict', ['duplicate_application', 'duplicate_cart', 'cross_cart', 'cross_order', 'history', 'negative', 'unassigned'])
def test_preflight_stops_before_schema_changes(conn, conflict):
    legacy(conn)
    if conflict == 'duplicate_application':
        execute(conn, "INSERT INTO DRIVER_APPLICATION(driver_id,sponsor_id,status) VALUES(900003,900001,'PENDING'),(900003,900001,'PENDING')")
    elif conflict == 'duplicate_cart':
        execute(conn, "INSERT INTO SHOPPING_CART(driver_id,sponsor_id,status) VALUES(900003,900001,'ACTIVE'),(900003,900001,'ACTIVE')")
    elif conflict in ('cross_cart', 'cross_order', 'history'):
        execute(conn, "INSERT INTO SPONSOR_ORGANIZATION(sponsor_id,sponsor_name,status,point_dollar_rate) VALUES(900010,'Other','ACTIVE',0.01)")
        execute(conn, 'INSERT INTO CATALOG_ITEM(sponsor_id,product_id,point_price) VALUES(900010,900001,100)')
        if conflict == 'cross_cart':
            execute(conn, 'UPDATE CART_ITEM SET sponsor_id=900010 WHERE cart_id=900001')
        elif conflict == 'cross_order':
            execute(conn, 'UPDATE ORDER_ITEM SET sponsor_id=900010 WHERE order_id=900001')
        else:
            execute(conn, "INSERT INTO POINT_TRANSACTION(driver_id,sponsor_id,points_delta,balance_after,reason) VALUES(900003,900010,100,100,'Historical')")
    elif conflict == 'negative':
        execute(conn, 'UPDATE DRIVER SET current_points=-1 WHERE driver_id=900003')
    else:
        execute(conn, 'UPDATE DRIVER SET sponsor_id=NULL WHERE driver_id=900003')
    with pytest.raises(mysql.connector.Error):
        migrate(conn)
    assert execute(conn, "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='DRIVER_SPONSOR'") == [(0,)]


def test_migrated_schema_matches_fresh_schema(conn):
    legacy(conn)
    migrate(conn)
    def contract():
        columns = execute(conn, "SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,GENERATION_EXPRESSION FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION")
        keys = execute(conn, "SELECT TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION")
        return columns, keys
    migrated = contract()
    # These are only the tables created inside this test's unique database.
    execute(conn, 'SET FOREIGN_KEY_CHECKS=0')
    for (table,) in execute(conn, 'SHOW TABLES'):
        execute(conn, f'DROP TABLE `{table}`')
    execute(conn, 'SET FOREIGN_KEY_CHECKS=1')
    run_sql(conn, ROOT / 'schema.sql')
    assert contract() == migrated
