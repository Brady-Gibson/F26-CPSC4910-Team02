"""Create an admin account from the command line. Use this for the FIRST real admin
(after that, admins can create each other on the site).

Run from the backend folder with the venv active:

    python scripts/create_admin.py

It asks for the details and the password (the password isn't shown as you type).
Works against whatever database your .env points to, so it creates the admin in RDS.
"""
import os
import sys
from getpass import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from accounts import AccountError, check_password, create_user
from db import transaction


def ask(label):
    value = input(f"{label}: ").strip()
    while not value:
        value = input(f"{label} (required): ").strip()
    return value


def main():
    print(f"Creating an admin in {os.getenv('DB_NAME')} on {os.getenv('DB_HOST')}\n")
    username = ask("Username")
    first = ask("First name")
    last = ask("Last name")
    email = ask("Email")
    while True:
        password = getpass("Password: ")
        try:
            check_password(password)
        except AccountError as e:
            print(e)
            continue
        if getpass("Confirm password: ") == password:
            break
        print("Passwords don't match. Try again.")
    try:
        with transaction() as cur:
            user_id = create_user(cur, "admin", username=username, password=password,
                                  first_name=first, last_name=last, email=email)
    except AccountError as e:
        sys.exit(f"Not created: {e}")
    print(f"\nCreated admin '{username}' (user_id {user_id}). Sign in at /login.html.")


if __name__ == "__main__":
    main()
