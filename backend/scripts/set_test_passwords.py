"""Give the seeded test accounts a real password so /api/login works.

The seed file stores 'TEST_HASH_ONLY' as a placeholder, which can't be logged into.
Run from the backend folder:

    python scripts/set_test_passwords.py              # sets Password123!
    python scripts/set_test_passwords.py MyPass!99    # or pick your own
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from werkzeug.security import generate_password_hash

from db import transaction

if os.getenv("APP_ENV") == "production":
    sys.exit("Refusing to run with APP_ENV=production.")

password = sys.argv[1] if len(sys.argv) > 1 else "Password123!"
with transaction() as cur:
    cur.execute("SELECT user_id FROM USER_ACCOUNT WHERE password_hash = 'TEST_HASH_ONLY'")
    ids = [r["user_id"] for r in cur.fetchall()]
    for uid in ids:
        cur.execute("UPDATE USER_ACCOUNT SET password_hash = %s WHERE user_id = %s",
                    (generate_password_hash(password), uid))
print(f"Updated {len(ids)} account(s). Password: {password}")
