# Customer accounts, Cognito auth, RBAC, and admin backoffice

## Context

The webshop PoC (`webshop-aws-python`) is fully built, deployed, and live at
`webshop-aws-python.kabulter.click`. Today it has **no authentication at all** — the only
identity concept is an anonymous `cart_id` UUID in a signed session cookie
(`app/session_cart.py`), scoping a guest's cart. Orders (`app/models/order.py`) have no
customer association whatsoever, and `docs/owasp-top-10.md`'s A07 row already states the
intended extension path verbatim: *"een echte uitbreiding zou Cognito gebruiken"* — this
plan fulfills that pre-written recommendation.

The user wants real user accounts on top of this: two strictly separated roles (registered
customers vs. a single fixed admin), AWS Cognito as the identity provider (driven via
`boto3`, **not** the Hosted UI/OAuth-redirect flow — this is a server-rendered Flask app, not
an SPA), a customer-facing account area (profile, order history, order detail with
conditional cancel/return actions), and an admin backoffice (dashboard, orders & logistics,
product/inventory, customer/CRM). **Planning only — no code changes in this session.**

A Plan-subagent produced a grounded, code-level design (reading the actual repo) that this
plan is built from; its judgment calls are adopted below and flagged where they're a
deliberate scope decision rather than a requirement restatement.

## Architecture overview

New code, following the existing `app/routes/<feature>.py` Blueprint-per-feature convention:

```
app/
  auth/
    __init__.py
    cognito.py          # boto3 cognito-idp calls, SECRET_HASH computation
    session.py          # SESSION# item CRUD, g.current_user resolution
    decorators.py       # @login_required / @admin_required for one-off routes
  routes/
    auth.py             # /register /confirm /login /logout /forgot-password /reset-password
    account.py          # /account, /account/orders, /account/orders/<id>, cancel, return
    admin.py            # /admin, /admin/orders, /admin/products, /admin/customers
  models/
    user.py             # UserProfile dataclass
    return_request.py   # Return dataclass
  templates/
    auth/ ... account/ ... admin/ ...
```

Routing: `/`, `/products`, `/cart*`, `/checkout` stay guest-accessible, unchanged. New:
`/register|/confirm|/login|/logout|/forgot-password|/reset-password` (public, `auth.bp`);
`/account*` (`account.bp`, login-gated); `/admin/*` (`admin.bp`, `url_prefix="/admin"`,
admin-gated). `app/main.py` registers the three new blueprints, adds an app-level
`before_request` resolving `g.current_user`, and a `context_processor` exposing it to all
templates (needed for nav-bar login/logout state).

**New dependency**: none required beyond `boto3` (already present) — see Testing section for
why no JWT library is needed. `app/aws_clients.py` gets one addition following its existing
factory pattern exactly:
```python
def cognito_idp_client():
    return boto3.client("cognito-idp", region_name=AWS_REGION,
                         endpoint_url=_endpoint_url("COGNITO_IDP_ENDPOINT_URL"))
```

## AWS Cognito configuration (new `terraform/modules/cognito`)

- `aws_cognito_user_pool.this`: `username_attributes = ["email"]`,
  `auto_verified_attributes = ["email"]`, explicit password policy (don't rely on AWS
  defaults — matches this project's "no implicit config" habit, e.g. `PROPAGATE_EXCEPTIONS =
  False`), `mfa_configuration = "OFF"` (stated PoC-scope caveat in the OWASP doc, not silent).
- `aws_cognito_user_pool_client.this`: `generate_secret = true` (**confidential client** —
  every Cognito call happens server-side in Lambda, so a kept secret is correct here, unlike
  the SPA/mobile public-client pattern); `explicit_auth_flows =
  ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]` (both are **off by default**,
  easy to silently miss); `prevent_user_existence_errors = "ENABLED"` (so `InitiateAuth`/
  `ForgotPassword` never leak whether an email is registered).
- `aws_cognito_user_group.admins`: name `Admins`. **No `Customers` group is created** —
  absence of group membership is the customer default. This is a deliberate simplification
  matching "1 vaste administrator": one real group to manage, not two.
- The one fixed admin user is created **out-of-band** (documented `aws cognito-idp
  admin-create-user` + `admin-add-user-to-group` CLI commands in the README), the same
  pattern already used for `SECRET_KEY`'s SSM parameter — not Terraform-managed, to avoid a
  password ending up in state.
- Outputs: `user_pool_id`, `user_pool_arn`, `client_id`, `client_secret` (sensitive). Wired
  into `module.lambda_main_app.environment_variables` as `COGNITO_USER_POOL_ID`,
  `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET` — same honest "visible in Lambda
  console/state" caveat already written for `SECRET_KEY` applies here too (A04 doc update).
- `modules/github_oidc`'s `ReadOnlyForPlan` IAM statement needs
  `cognito-idp:DescribeUserPool`, `DescribeUserPoolClient`, `ListGroups`,
  `ListTagsForResource` added, or CI's `terraform plan` breaks against the new module.

**Main Lambda IAM additions** — deliberately narrow: the user-facing Cognito calls
(`SignUp`, `ConfirmSignUp`, `InitiateAuth`, `ForgotPassword`, `ConfirmForgotPassword`,
`GetUser`, `GlobalSignOut`, …) are authorized by the app client id/secret and the caller's
own token, **not by IAM** — they need no policy entry at all. Only the `Admin*`/`List*`
calls are IAM-gated:
```hcl
{
  actions   = ["cognito-idp:AdminListGroupsForUser", "cognito-idp:AdminGetUser",
               "cognito-idp:AdminUpdateUserAttributes", "cognito-idp:ListUsers"]
  resources = [module.cognito.user_pool_arn]
}
```
`AdminListGroupsForUser` is called right after login to populate `groups` in the session
(see below — the app never decodes a JWT, so this is the only way to learn group
membership). `ListUsers`/`AdminGetUser` serve the admin CRM screen.
**Verify this list empirically against real AWS early** (step 1/2 below) rather than
trusting it blind — a wrong IAM guess here means every login breaks.

## DynamoDB schema extension (single table, existing conventions)

All within `WebshopTable`. **One new GSI (GSI2) is required** — reasoning below the table.

| Entity | PK | SK | Notes |
|---|---|---|---|
| User profile | `USER#<sub>` | `PROFILE` | `sub` = Cognito UUID. Point lookup. `email, given_name, family_name, shipping_address{}, billing_address{}` — embedded maps (the requirement is one fixed pair per profile, not an address book). |
| Order (extended) | `ORDER#<id>` | `METADATA` | Add `user_sub` (absent for guest orders), `GSI1PK=USER#<sub>` + `GSI1SK=ORDER#<created_at>#<id>` **only when `user_sub` is present** (sparse index — guest orders never populate it). Add `GSI2PK="ORDER"` + `GSI2SK=<created_at>#<id>` for the admin order list. Replace the free-string `status` with a canonical enum. |
| Order line | `ORDER#<id>` | `ITEM#<product_id>` | Unchanged. |
| Return | `ORDER#<id>` | `RETURN` | One per order (matches the requirement's single button/single reason field). `PutItem` with `ConditionExpression="attribute_not_exists(SK)"` — idempotent double-submit guard *and* the "one return per order" rule, enforced at the key level. `GSI2PK="RETURN"` + `GSI2SK=<reported_at>#<id>` for an admin returns queue. |
| Product variant | `PRODUCT#<id>` | `VARIANT#<color>` | New. `stock_qty` (Number). |
| Session | `SESSION#<session_id>` | `METADATA` | See Security section. `expires_at` (epoch seconds) + table-level TTL on that attribute. |

**Why GSI2, not everything in GSI1**: a single item can only carry one `GSI1PK` value, and
GSI1 on Order is already needed for "this customer's orders." A denormalized shadow item for
the admin view would need to stay in sync on every status change — exactly the kind of drift
risk this project's index design has otherwise avoided. GSI2 with a single-partition bucket
(`GSI2PK="ORDER"`) reuses the *same* trade-off already accepted for
`GSI1PK="CATEGORY#DESK_LAMPS"` on products — not a new risk, just the same one applied
again, with the bonus that status changes never touch GSI2's keys (status filtering is a
`FilterExpression`, same mechanism as the existing color filter).

**Required bug-fix as part of this step, not optional**: `single_table.get_order()`
currently does `if item["SK"] != "METADATA"` to collect order lines — the moment a `RETURN`
sibling item exists under the same `PK`, this mis-parses it as an `OrderLine` and raises
`KeyError`. Must become `item["SK"].startswith("ITEM#")`.

**Status enum**: define one canonical lifecycle in `app/config.py` —
`AWAITING_PAYMENT, IN_PROGRESS, SHIPPED, DELIVERED, CANCELLED, RETURN_REPORTED` — with a
Dutch display-label map. Add `single_table.set_order_status(order_id, new_status,
allowed_from: set[str])` using a `ConditionExpression` on current status, so a concurrent
cancel-attempt and a status-updating consumer can't race. This wraps, not replaces, the
existing `set_order_status_field` (consumers still stamp their own sub-fields independently).

**Scope decision — stock auto-decrement is out of scope for this phase.** `list_products`
filters on the Product METADATA item's `colors: list[str]`, which would need to stay in sync
with the new `VARIANT#<color>` stock items — two sources of truth. Doing this transactionally
on checkout would need `dynamodb:TransactWriteItems` (not in any IAM policy today) *and* a
larger change to the `OrderPlaced` event (which carries no line items today, only
`order_id/total_cents/item_count/notify`) and the inventory consumer's schema. **Admin
inventory management is a manual stock-editing screen only** in this phase; automatic
decrement-on-order is a documented future extension. Flag this explicitly for approval since
it narrows "Voorraadbeheer" relative to how it could be read literally.

`scripts/bootstrap_local_infra.py` and `terraform/modules/dynamodb/main.tf` both need the
GSI2 attributes/index and the TTL config added, in lockstep (the script's stated purpose is
already to mirror Terraform's shapes for local/moto parity).

## Security strategy — RBAC enforcement

**Session design** (replaces nothing — extends the existing `cart_id` pattern to
authenticated state): the Flask session cookie stays signed-but-not-encrypted and
client-visible, so raw Cognito tokens never go in it. Instead, exactly like `cart_id` today,
the cookie holds one opaque `session_id` (generated with `secrets.token_urlsafe(32)` — a
credential, unlike a cart id, so not `uuid4()`); the real session data lives server-side in
a `SESSION#<id>` item: `{cognito_sub, email, groups, cart_id, csrf_token, expires_at}`.

- **No refresh token is stored** — a deliberate simplification. Sessions are fixed-length
  (e.g. 8h), no silent refresh. This keeps nothing in DynamoDB that's a reusable credential
  and drops `REFRESH_TOKEN_AUTH`/token-rotation out of scope entirely. Documented future
  extension if 8h proves too short in practice.
- `before_request` resolves `g.current_user` via one `get_item`; DynamoDB TTL deletion is
  best-effort/delayed, so the app enforces `expires_at` itself — TTL is storage hygiene, not
  a security control.
- Rotate the session id on login (new item, discard the pre-auth one) — session-fixation
  defense. **Carry the pre-login `cart_id` forward into the new session item** so a guest's
  cart isn't silently dropped on login (no cart-merge logic needed, same `cart_id` either way).
- Group membership is cached at login via `AdminListGroupsForUser` (the app never decodes a
  JWT anywhere — see Testing). This creates a staleness window (revoking admin access doesn't
  take effect until the session expires) — negligible with one fixed admin, stated as a
  caveat, not hidden.
- Session storage over a cookie-held token is also what makes **true server-side logout**
  possible at all (delete the item, the session is dead everywhere) — a signed/encrypted
  cookie alone cannot do that.

**Gate mechanism — blueprint-level `before_request`, not per-route decorators as the primary
defense** (a decorator can be forgotten on route fourteen; a blueprint hook structurally
can't be skipped per-route):
```python
# app/routes/admin.py
@bp.before_request
def require_admin():
    if g.current_user is None or "Admins" not in g.current_user.groups:
        abort(404)   # not 403 -- see below
```
`@login_required`/`@admin_required` decorators still exist in `app/auth/decorators.py` for
one-off routes outside these two blueprints.

**404, never 403, on an existence check — and identical on both failure branches**:
```python
order = single_table.get_order(order_id)
if order is None or order.user_sub != g.current_user.sub:
    abort(404)   # byte-identical for "doesn't exist" and "not yours"
```
This is the same principle `docs/owasp-top-10.md`'s A01 row already documents for `cart_id`
— extended here with its own doc row: *"een orderdetail-request voor een order die niet
bestaat, of van iemand anders is, is niet te onderscheiden (404) — de route vertakt nooit op
bestaan vóór de eigendomscheck."* Admin order detail is a **separate route**
(`/admin/orders/<id>`), never an `if is_admin or owns_it` branch merged into the customer
route — merged authorization branches are exactly where this class of bug hides. The same
ownership + 404 check must be repeated on the cancel/return **POST** handlers, not just the
GET detail view.

**Server-side precondition enforcement, not just disabled buttons** — same story as
checkout's existing price revalidation: cancel/return eligibility is re-checked on the POST
using a `ConditionExpression` on current status (atomic, race-safe), and the 14-day return
window is computed server-side from the stored timestamp against a configurable
`RETURN_WINDOW_DAYS` constant.

**CSRF — newly in-scope, must be an explicit decision, not silence.** The guest cart's
`SameSite=Lax` cookie already blocks cross-site POSTs, a defensible existing posture, but
once authenticated state-changing actions exist (profile edit, cancel, admin status change)
a reviewer will ask. Decision: a per-session CSRF token stored in the `SESSION#<id>` item,
rendered as a hidden field (or via `hx-headers` for HTMX requests), validated on every POST
in the two gated blueprints. No new dependency needed (no Flask-WTF).

**Verify with a test, not just by writing the hook once**: a test enumerating
`app.url_map.iter_rules()` asserting every `/admin/*` endpoint rejects both an anonymous
session and an authenticated-customer session — written in the same build step as the gate
itself (step 8), against a single stub route, before any real admin screen exists.

## Testing implications

Because every Cognito call happens server-side and group membership comes from
`AdminListGroupsForUser` rather than decoding a token, **the app never parses a JWT it
didn't receive directly from Cognito over a server-side call** — no JWKS verification
anywhere, which also eliminates the single worst moto-compatibility risk (mocked User Pools'
JWKS endpoints are not reliably moto-compatible across versions). Worth its own line in the
OWASP doc.

Remaining concrete gotchas:
- moto may not validate `SECRET_HASH` correctness — a broken hash function could pass the
  whole suite and only fail against real AWS. Mitigate independently: a unit test asserting
  the hash function's output against a hand-computed expected Base64 string for a fixed
  `(client_id, client_secret, username)` triple.
- Verify moto's confirmation-code behavior empirically against the pinned
  `moto[server]==5.0.24` (accepts any code vs. requires an exact one varies by version); keep
  the expected code as one named test constant.
- Pool id/client id/secret are generated **at runtime** by moto (unlike the queue names,
  which are fixed constants) — a new `tests/conftest.py` fixture must create the pool/client
  and export them as `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID`/`COGNITO_CLIENT_SECRET`, and
  must run *before* `tests/e2e/conftest.py::live_server_url` (which copies `os.environ` for
  the `flask run` subprocess) — add it to that fixture's parameter list to force ordering.
  Also add `COGNITO_IDP_ENDPOINT_URL` to the existing `aws_endpoints` fixture.
- Don't try to test DynamoDB TTL deletion itself (slow, eventually-consistent even against
  real AWS) — test the application-level expiry check by writing a `SESSION#<id>` item with
  a past `expires_at` directly and asserting `resolve_current_user()` treats it as absent.
- E2E: create test users via boto3 directly in a fixture for most scenarios (fast,
  deterministic); keep exactly one Playwright test driving the real registration form
  end-to-end to cover the UI itself.

## Build order (each step independently testable before the next begins)

1. **Terraform only** — User Pool, app client+secret, `Admins` group, GSI2 + TTL on the
   table, new IAM statements, new env vars. No app code yet. Deploy and empirically verify
   the IAM action list against a real login flow before writing app code against it.
2. `app/auth/cognito.py` — boto3 wrapper + `SECRET_HASH` + its hand-computed unit test +
   moto fixtures. No routes, no UI — retires the two biggest unknowns (hash correctness,
   moto behavior) before anything depends on them.
3. `app/auth/session.py` — SESSION item CRUD + `before_request`/`g.current_user` + context
   processor. Testable directly against table items, still no UI.
4. Auth routes + templates (register/confirm/login/logout/forgot-password) + nav bar update.
5. Customer profile (`USER#<sub>`/`PROFILE`) view/edit.
6. Order↔user link: add `user_sub`/GSI1 keys to Order, **fix `get_order`'s SK filter**,
   customer order list + detail with 404-on-foreign-order. No backfill needed — existing
   orders are all guest orders and simply have no `user_sub`.
7. Status enum + cancel + return-reporting, with `ConditionExpression`-guarded transitions
   and server-side 14-day-window enforcement.
8. **Admin gate**: blueprint `before_request` + the `url_map`-enumeration test, proven
   against one stub `/admin/ping` route first — cheaper to prove once than retrofit later.
9. Admin dashboard (stats + activity) — needs order/customer data, so sequenced after 6–8.
10. Admin Orders & Logistics + returns queue (reads GSI2).
11. Admin Products/Inventory/variants — deliberately **second-to-last**: the only step
    touching the already-working catalog read path, highest regression risk.
12. Admin Customer management (CRM) — only `ListUsers`/`AdminGetUser`, no new schema.

Deliberately avoided as starting points: the admin dashboard (depends on everything else),
product/variant management (touches working catalog code), and any UI-first step (would
defer the two genuinely risky unknowns — hash correctness, moto's Cognito behavior — to the
end, where a failure is most expensive to unwind).

## README changes

**Rewrite the opening to lead with functionality, not architecture framing.** Today's
README opens with `# Nordic Wonen — Serverless Event-Driven Webshop (PoC)`, the live-demo
link, then immediately a blockquote framing the project as an "Architectural & QA Automation
Proof of Concept" — a reader has to infer what the app actually *does* from the architecture
description. Insert a new, short "Wat doet deze applicatie?" section **between the live-demo
link and that blockquote**, so the functional picture comes first and the portfolio framing
follows it, not the other way round. Proposed text (Dutch, matching existing tone):

> ## Wat doet deze applicatie?
>
> Nordic Wonen is een webshop voor bureaulampen. Bezoekers bladeren door de catalogus,
> sorteren op prijs en filteren op kleur, voegen lampen toe aan hun winkelwagen en rekenen af
> — als gast, of als geregistreerde klant. Geregistreerde klanten loggen in via een eigen
> account (AWS Cognito) en krijgen een persoonlijke omgeving: profiel- en adresgegevens
> beheren, eerdere bestellingen inzien, en — zolang de status het toelaat — een bestelling
> annuleren of een retour melden. Een aparte, afgeschermde beheeromgeving geeft de
> winkelbeheerder (1 vaste admin-account) een dashboard met kerncijfers, orderbeheer
> inclusief retourverwerking, product-/voorraadbeheer, en klantenbeheer.
>
> Onder de motorkap draait dit volledig serverless op AWS (Lambda, DynamoDB, EventBridge,
> SQS, Cognito); de rest van dit document behandelt die architectuur, de
> beveiligingsmaatregelen en de teststrategie in detail.

The existing `> **Architectural & QA Automation Proof of Concept.** ...` blockquote stays,
immediately after this, unchanged — it's still the right portfolio-angle framing, just no
longer the *first* thing a reader sees.

**Content updates elsewhere in the README, each landing alongside the build-order step that
makes it true** (not deferred as one disconnected doc pass at the end):

- **Inhoudsopgave**: add entries for the new sections below, in document order.
- **DynamoDB single-table design** table: add rows for User profile, Return, Product
  variant, and Session (step 6/7 territory) — same table format as today, same column style.
- **New "Gebruikersrollen & authenticatie" section** (after the single-table section): the
  two-role model, the deliberate "no `Customers` group, absence = customer" decision, the
  confidential-client/`SECRET_HASH` note, and the session design (opaque `session_id` →
  `SESSION#<id>` item, no refresh token stored, fixed 8h lifetime) — written with the same
  concrete, code-referencing style as the EventBridge-vs-SNS section (link to
  `app/auth/session.py`, `app/auth/cognito.py`).
- **New "Klantomgeving" and "Admin-backoffice" sections**: short, route-table style listing
  (path → wat het doet → wie mag het) rather than prose, mirroring how routes are already
  summarized elsewhere.
- **OWASP Top 10 table + `docs/owasp-top-10.md`**: A01 gets the order-ownership 404 row; A04
  gets the Cognito client-secret-in-Lambda-env caveat (same pattern as the existing
  `SECRET_KEY` caveat); A07 is a full rewrite (no longer "buiten scope: gast-winkelwagen
  zonder login"); add a CSRF line (new, not an existing row — note which category it best
  fits, likely still A01 or a new explicit mention).
- **Infrastructure as Code / Deployment naar AWS**: document the new `cognito` module and the
  one-off `aws cognito-idp admin-create-user` bootstrap command for the fixed admin account,
  in the same style as the existing SSM-parameter bootstrap step.
- **Scope en beperkingen**: add the stock-auto-decrement-out-of-scope line, MFA-off, and
  no-refresh-token/8h-session caveats here, so they're visible in one place, not just buried
  in prose above.
- **Projectstructuur** tree: add `app/auth/`, the 3 new route modules, new templates dirs.

Treat this as **step 13** in the build order: a final consolidation pass once steps 1–12 are
done, to catch anything the incremental per-step doc edits missed — but each step above
should still update its own relevant section as it lands, not leave all documentation to the
end.

## Critical files

- `app/repositories/single_table.py` — `get_order()` bug-fix, new `set_order_status`, new
  session/user/return/variant CRUD functions, following its existing `Key`/`Attr` style.
- `app/models/order.py` — add `user_sub`, replace free-string status with the enum.
- `app/main.py` — register 3 new blueprints, `before_request`, `context_processor`.
- `app/session_cart.py` — pattern to extend, not replace, for `session_id`.
- `app/aws_clients.py` — add `cognito_idp_client()`.
- `terraform/main.tf`, `terraform/modules/dynamodb/main.tf` — GSI2/TTL, new module wiring,
  IAM additions.
- `scripts/bootstrap_local_infra.py` — mirror schema/TTL changes for local parity.
- `tests/conftest.py`, `tests/e2e/conftest.py` — new Cognito fixture, ordering constraint.
- `docs/owasp-top-10.md` — A01 (order-ownership 404 row), A04 (Cognito secret caveat), A07
  (full rewrite — no longer "out of scope"), new CSRF row.
- `README.md` — new opening "Wat doet deze applicatie?" section, updated TOC, DynamoDB table
  additions, new role/auth/klantomgeving/admin sections, OWASP table updates, deployment
  bootstrap step for the fixed admin user, Scope-en-beperkingen additions, updated
  Projectstructuur tree (see README changes section above for exact detail).

## Verification

- `uv run pytest` stays green throughout — each build-order step above should land with its
  own tests (hash unit test, session-expiry test, `url_map`-enumeration admin-gate test,
  ownership-404 tests for both "doesn't exist" and "not mine") before the next step starts.
- `terraform fmt -check -recursive` + `terraform validate` after the Terraform step.
- Manual check after step 1: real login flow against the deployed User Pool to confirm the
  IAM action list is actually sufficient (catches a wrong guess immediately, not after
  building on top of it).
- Playwright E2E: one full registration-through-order-cancel journey, one full
  admin-login-through-status-change journey, plus the existing guest checkout flow
  unaffected (regression check — guest orders must keep working exactly as today).
- Step 13 (README): read the rewritten opening paragraph fresh, as if seeing the project for
  the first time — it should answer "what does this app do" in the first few lines, before
  any architecture/portfolio framing; confirm every new section's code references
  (`app/auth/...`, route paths) actually match what was built.
