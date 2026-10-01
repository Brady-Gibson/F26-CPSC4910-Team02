# TigerTruck UI Design (Draft)

Team 02 · Good Driver Incentive Program

Open `ui-prototype.html` in a browser for the clickable draft. Use the Driver / Sponsor / Admin switch to preview each role, and turn on **Show data sources** to see which tables each screen reads and writes. Sample data mirrors `seed_test_data.sql`, and changes reset on reload.

## Visual direction

The look borrows from US interstate signage, since the users spend their day reading it.

| Token | Value | Use |
|---|---|---|
| Interstate green | `#00694B` | Primary brand, active nav, point balance sign |
| Hi-vis amber | `#FFB81C` | Primary actions, counts, focus ring |
| Asphalt | `#24292E` | Sidebar, text, secondary buttons |
| Concrete | `#EDEFEA` | Page background |
| Warning red | `#B42318` | Deductions, rejections, destructive actions |

Typeface is **Overpass** (Google Fonts), which is based on the Highway Gothic signage face. Numbers use tabular figures so point columns line up. Light and dark themes are both defined.

The driver's point balance is drawn as a green highway sign with an amber "exit tab" showing their next scheduled award. It's the one loud element; everything else stays quiet.

## Routes and data

### Driver
| Route | Screen | Tables |
|---|---|---|
| `/driver` | Dashboard: balance sign, recent activity, open orders | `DRIVER`, `POINT_TRANSACTION`, `RECURRING_POINT_SCHEDULE`, `CUSTOMER_ORDER` |
| `/driver/catalog` | Sponsor catalog with search and category filter | `CATALOG_ITEM`, `PRODUCT`, `SHOPPING_CART`, `CART_ITEM` |
| `/driver/cart` | Cart with balance-after check, place order | `CART_ITEM`, `CUSTOMER_ORDER`, `ORDER_ITEM`, `POINT_TRANSACTION` |
| `/driver/orders` | Order history, cancel while `PLACED` (refunds points) | `CUSTOMER_ORDER`, `ORDER_ITEM`, `POINT_TRANSACTION` |
| `/driver/points` | Full point history with running balance | `POINT_TRANSACTION` |
| `/driver/sponsor` | Current sponsor, apply to a sponsor, application status | `DRIVER`, `DRIVER_APPLICATION`, `SPONSOR_ORGANIZATION` |
| `/driver/alerts` | Notifications and alert settings | `NOTIFICATION`, `ALERT_PREFERENCE` |
| `/driver/profile` | Profile and password | `USER_ACCOUNT`, `AUDIT_EVENT` |

### Sponsor
| Route | Screen | Tables |
|---|---|---|
| `/sponsor/drivers` | Driver roster, adjust points, drop driver | `DRIVER`, `POINT_TRANSACTION`, `NOTIFICATION`, `AUDIT_EVENT` |
| `/sponsor/applications` | Accept or reject applications with a reason | `DRIVER_APPLICATION`, `DRIVER`, `NOTIFICATION`, `AUDIT_EVENT` |
| `/sponsor/schedules` | Recurring point awards | `RECURRING_POINT_SCHEDULE` |
| `/sponsor/catalog` | Pick products from the API feed and set point prices | `PRODUCT`, `CATALOG_ITEM` |
| `/sponsor/orders` | Orders from their drivers | `CUSTOMER_ORDER`, `ORDER_ITEM` |
| `/sponsor/reports` | Points awarded, deducted, redeemed | `POINT_TRANSACTION`, `CUSTOMER_ORDER`, `AUDIT_EVENT` |
| `/sponsor/org` | Point value, contact info, sponsor team | `SPONSOR_ORGANIZATION`, `SPONSOR_USER` |

### Admin
| Route | Screen | Tables |
|---|---|---|
| `/admin/users` | All accounts, filter by role, lock and unlock | `USER_ACCOUNT`, `ADMIN`, `SPONSOR_USER`, `DRIVER` |
| `/admin/sponsors` | Organizations, activate and deactivate | `SPONSOR_ORGANIZATION`, `DRIVER`, `SPONSOR_USER` |
| `/admin/audit` | Audit log filtered by category and result | `AUDIT_EVENT` |
| `/admin/reports` | Sales by sponsor for invoicing | `CUSTOMER_ORDER`, `ORDER_ITEM` |
| `/admin/about` | Release info for the public about page | `ABOUT_RELEASE` |

## Rules the UI enforces

- Every point change writes a `POINT_TRANSACTION` row with `balance_after`, updates `DRIVER.current_points`, and logs an `AUDIT_EVENT`. A notification is sent only if the driver's `point_change_enabled` is on.
- Balances can't go below zero; the cart disables **Place order** and says how many points are missing.
- Cart and order lines store the point price at the time they were added (`point_price_snapshot`, `unit_point_price`), so later catalog price changes don't affect them.
- Catalog point price defaults to `ceil(dollar_price / point_dollar_rate)` and the sponsor can override it.
- Cancelling an order writes a refund transaction. Dropping a driver forfeits their balance with a transaction.
- A driver can only have one pending application at a time. `drop_alert_enabled` is always on.

## Connecting to the database

The prototype's sample data is a stand-in for the API, not something to wire to MySQL. A browser can't open a MySQL connection, and DB credentials must never ship in front-end code. The real flow is React page → API (Express or Lambda) → RDS. Table names are case-sensitive on RDS, so queries must use `DRIVER`, not `driver`.

## Carrying this into React

Each screen maps to one page component under `src/pages/<role>/`. Shared pieces: `PointSign`, `TxTable`, `StatusBadge`, `OrderCard`, `AdjustPointsDialog`, `Toast`. Move the CSS custom properties into `src/styles/tokens.css` so the homepage and app share them.
