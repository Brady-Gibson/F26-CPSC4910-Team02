# Backend (Flask)

Flask serves the pages in `../frontend` **and** the API, so everything runs from one address: http://localhost:5000

## Setup (once)
```
cd backend
python -m venv venv
venv\Scripts\activate              # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # Mac/Linux: cp .env.example .env
```
Fill in `.env` with the RDS credentials and a `SECRET_KEY` (the file says how to make one). Never commit `.env`.

Then give the seeded test accounts a real password (the seed only has a placeholder):
```
python scripts/set_test_passwords.py          # sets Password123! for testdriver, testsponsor, testadmin
```

## Run
```
python application.py
```
Open http://localhost:5000. Check http://localhost:5000/api/health first: it should say `"ok": true`.

## Files
| File | What it does |
|---|---|
| `application.py` | Creates the app, serves `../frontend`, registers the routes. Keep the name: Elastic Beanstalk expects `application.py` / `application`. |
| `db.py` | `query()` for reads, `transaction()` for writes. Use these, don't open your own connections. |
| `auth.py` | `/api/login`, `/api/logout`, `/api/me`, and `@require_role(...)`. Locks an account after 5 failed logins in a row. |
| `points.py` | `change_points()`: the only way points change. Updates the balance, writes the transaction, audit log, and notification together. |
| `audit.py` | `log_audit()` and `notify()` helpers. |
| `routes/driver.py` `routes/sponsor.py` `routes/admin.py` | One file per role. Add your endpoints to your role's file. |
| `routes/dev.py` | `/api/bootstrap`, dev only. Lets unconverted pages show real data. Delete when every page is converted. |

## Converting a page (the workflow for each teammate)
`frontend/driver/dashboard.html` + `GET /api/driver/dashboard` is the finished example. For your page:

1. **Add the endpoint** in your role's file:
   ```python
   @bp.get("/orders")
   @require_role("driver")
   def orders():
       rows = query("SELECT ... FROM CUSTOMER_ORDER WHERE driver_id = %s", (g.user["user_id"],))
       return jsonify(orders=rows)
   ```
2. **Change the page's view** to fetch it:
   ```js
   VIEWS.driver.orders = async () => {
     const { orders } = LIVE ? await App.api("/api/driver/orders") : mockOrders();
     ...build HTML from `orders`, not from DB
   };
   ```
3. **Saves** go through `App.api(path, { method: "POST", body: {...} })`, then `App.refresh()`. On the server, wrap writes in `with transaction() as cur:`. Anything touching points calls `change_points(cur, ...)`.

## Rules
- Always use `%s` placeholders. **Never** put user input into SQL with f-strings.
- Never select `password_hash` in anything sent to the browser.
- Sponsor routes filter by `g.user["sponsor_id"]` so sponsors only see their own drivers.
- Table names are UPPERCASE (case-sensitive on RDS).
