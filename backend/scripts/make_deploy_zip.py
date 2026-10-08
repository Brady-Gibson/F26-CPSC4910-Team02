"""Build deploy.zip for Elastic Beanstalk (upload it in the EB console).

Run from the backend folder:   python scripts/make_deploy_zip.py   (works from any folder; CI runs it on Linux)

Puts the backend files at the root of the zip and the pages in frontend/.
Leaves out .env (secrets go in EB environment properties), venv, caches, scripts, and tests.
"""
import os
import zipfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(BACKEND, "..", "frontend")
OUT = os.path.join(BACKEND, "deploy.zip")
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".pytest_cache", ".git", "scripts", "tests"}
SKIP_FILES = {".env", "deploy.zip"}


def add_tree(z, src, prefix=""):
    count = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES or f.endswith(".pyc"):
                continue
            full = os.path.join(root, f)
            arc = os.path.join(prefix, os.path.relpath(full, src)).replace("\\", "/")
            z.write(full, arc)
            count += 1
    return count


if not os.path.isdir(FRONTEND):
    raise SystemExit(f"Can't find the frontend folder at {os.path.abspath(FRONTEND)}")
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    n = add_tree(z, BACKEND) + add_tree(z, FRONTEND, "frontend")
    names = z.namelist()
for required in ("application.py", "requirements.txt", "Procfile", "frontend/login.html"):
    assert required in names, f"{required} missing from zip"
assert ".env" not in names
print(f"Created {OUT} ({n} files). Upload it in Elastic Beanstalk.")
