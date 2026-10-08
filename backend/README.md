# Backend (Flask)

Serves the API under `/api/...` and the pages in `../frontend`.

## Run locally (Windows, PowerShell)
```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python application.py          # http://localhost:5000, check /api/health
```
`backend/.env` holds the database credentials, `SECRET_KEY`, and `APP_ENV=development`. Ask a teammate for the values. It is gitignored; never commit it.

## Tests
The tests build their own throwaway database (`Team02_TEST`) on any MySQL server you can create databases on. **Never point them at RDS.** The easiest server is Docker:
```
docker run -d --name t02-test-mysql -p 3306:3306 -e MYSQL_ROOT_PASSWORD=pw mysql:8.4
pip install -r requirements-dev.txt
$env:TEST_DB_HOST="127.0.0.1"; $env:TEST_DB_USER="root"; $env:TEST_DB_PASSWORD="pw"
python -m pytest tests -v
```
Without `TEST_DB_HOST` set, the database tests are skipped. GitHub Actions runs the same tests on every pull request into `main`.

## Deploying
**Deploys are automatic.** When a pull request is merged into `main`, GitHub Actions (`.github/workflows/deploy.yml`):
1. runs the tests (must pass),
2. builds `deploy.zip` with `scripts/make_deploy_zip.py`,
3. uploads it to S3 and creates a Beanstalk application version labeled with the short commit SHA,
4. deploys it to **Team02-gdip-env** (app `team02-gdip`, us-east-1), waits for the update to finish, and checks `/api/health`.

Watch it on GitHub → **Actions** → **Test and deploy**. A red run means the deploy failed (the log shows the Beanstalk events). To redeploy without a new commit: Actions → Test and deploy → **Run workflow** on `main`.

**Before merging code that needs a new migration** (`database/migrations/NNN_*.sql`), run the migration on RDS in Workbench. The workflow does not run migrations.

### Manual fallback
Only if Actions can't deploy (for example, it's down, or you need to ship something that isn't on `main`):
```
python scripts/make_deploy_zip.py
```
Then Beanstalk console → Team02-gdip-env → **Upload and deploy** → choose `backend/deploy.zip` with a new version label.

Secrets (database credentials, `SECRET_KEY`) live in the Beanstalk environment properties, not in the zip or the repo. The workflow never changes them.
