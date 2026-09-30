# Nordic Wonen — Serverless Event-Driven Webshop (PoC)

**🔗 Live demo:** [webshop-aws-python.kabulter.click](https://webshop-aws-python.kabulter.click)

> **Architectural & QA Automation Proof of Concept.** Dit is een portfolioproject dat een
> serverless, event-driven webshop-architectuur op AWS demonstreert: schone Python-code,
> Infrastructure as Code met Terraform, een single-table DynamoDB-datamodel, ontkoppeling via
> EventBridge + SQS, en een tweelaagse geautomatiseerde teststrategie (pytest/moto +
> Playwright E2E).

**Disclaimer:** dit project is **niet gelieerd aan IKEA®** en niet bedoeld voor commercieel
gebruik. De lay-out is in IKEA-stijl en de productfoto's zijn **hotlinked** vanaf
`ikea.com` (`bureaulampen-20502`) — ze worden dus rechtstreeks vanaf IKEA's eigen CDN
geladen door de browser van de bezoeker, en nooit gedownload, gekopieerd of opnieuw gehost.
De producttitels/codenamen (bijv. "VINDLYS", "BJORKVIK") zijn **verzonnen** en komen niet
overeen met de echte IKEA-productnamen, om hergebruik van handelsmerken te vermijden.

## Inhoudsopgave

1. [Architectuuroverzicht](#architectuuroverzicht)
2. [Projectstructuur](#projectstructuur)
3. [DynamoDB single-table design](#dynamodb-single-table-design)
4. [Event-driven architectuur: waarom EventBridge + SQS in plaats van SNS](#event-driven-architectuur-waarom-eventbridge--sqs-in-plaats-van-sns)
5. [OWASP Top 10 (2025) — beveiligingsmaatregelen](#owasp-top-10-2025--beveiligingsmaatregelen)
6. [Lokaal draaien](#lokaal-draaien)
7. [Testen](#testen)
8. [Infrastructure as Code (Terraform)](#infrastructure-as-code-terraform)
9. [Deployment naar AWS](#deployment-naar-aws)
10. [GitHub Actions (CI/CD)](#github-actions-cicd)
11. [Verwachte AWS-kosten (± 100 API-calls/dag)](#verwachte-aws-kosten--100-api-callsdag)
12. [Scope en beperkingen](#scope-en-beperkingen)

## Architectuuroverzicht

```
Browser (HTMX + Tailwind CDN)
        │  HTTPS
        ▼
webshop-aws-python.kabulter.click  (Route53 alias + ACM-cert, regionaal)
        │
        ▼
API Gateway (HTTP API)
        │  AWS_PROXY
        ▼
Lambda: webshop-main-app  (Flask via Mangum/ASGI, server-side rendered HTML-fragmenten)
        │
        ├── DynamoDB: WebshopTable  (producten, winkelwagens, orders)
        │
        └── EventBridge custom bus: webshop-event-bus
                 │  PutEvents("OrderPlaced")
                 ├── Rule payment-rule      ──► SQS payment-service-queue      ──► Lambda webshop-payment-service
                 ├── Rule inventory-rule    ──► SQS inventory-service-queue    ──► Lambda webshop-inventory-service
                 └── Rule notification-rule ──► SQS notification-service-queue ──► Lambda webshop-notification-service
                       (elke queue heeft een eigen DLQ voor fault isolation)
```

**Tech stack**

| Laag | Keuze |
|---|---|
| Frontend | HTMX (CDN, met SRI-hash) + Tailwind CSS Play CDN (CDN, gepinde versie-URL; geen SRI mogelijk, zie A03) |
| Backend | Python, Flask, gerenderd via `asgiref` + Mangum op AWS Lambda |
| Data | Amazon DynamoDB, single-table design |
| Events | Amazon EventBridge (custom bus) → fan-out naar 3 Amazon SQS-queues |
| IaC | Terraform (modules per component, incl. custom domain + GitHub OIDC) |
| Tests | pytest + moto (integratie), Playwright (Python, E2E) |
| Tooling | [uv](https://docs.astral.sh/uv/) voor Python-versie- én dependency-beheer (`pyproject.toml` + `uv.lock`) |
| CI/CD | GitHub Actions: tests op elke push/PR, handmatige code-only deploy via OIDC (geen AWS-sleutels in GitHub) |

De Flask-app is bewust **niet** ASGI-native geschreven (Flask is WSGI); `asgiref.wsgi.WsgiToAsgi`
verpakt de WSGI-app zodat Mangum — dat zelf een ASGI-adapter is — hem op Lambda kan draaien.

## Projectstructuur

```
webshop-aws-python/
├── pyproject.toml + uv.lock    # dependencies, dev-tools en het gepinde uv-lockbestand
├── .python-version             # pint de Python-versie (3.13) die `uv` gebruikt
├── docs/owasp-top-10.md        # uitgebreide risico-uitleg per OWASP-categorie
├── .github/workflows/
│   ├── tests.yml                # integratie + E2E tests, op elke push/PR
│   └── deploy.yml                # handmatige, code-only deploy naar AWS (OIDC, geen secrets)
├── terraform/                 # IaC: root config + modules/{dynamodb,eventbridge,sqs,lambda,
│                               #      api_gateway,custom_domain,github_oidc}
│   └── backend.env.example     # template voor terraform/backend.env (gitignored)
├── app/                       # Flask-applicatie (main app Lambda)
│   ├── main.py                 # Flask app + security headers + Mangum handler
│   ├── aws_clients.py          # boto3-clients, endpoint-url-aware (voor lokale moto-tests)
│   ├── models/                 # Product, CartItem, Order/OrderLine (dataclasses)
│   ├── repositories/           # single_table.py: alle DynamoDB-toegang
│   ├── routes/                 # catalog, cart, checkout (Flask blueprints)
│   ├── events/                 # publisher.py: OrderPlaced naar EventBridge
│   ├── templates/               # Jinja2 + HTMX-fragmenten
│   └── seed/products.json      # 22 lampen (uit ikea.com/nl/nl/cat/bureaulampen-20502)
├── consumers/                  # 3 losse consumer-Lambda's (payment/inventory/notification)
├── scripts/
│   ├── bootstrap_local_infra.py  # lokaal (moto) alleen: tabel + event bus/queues/rules aanmaken
│   ├── seed_products.py          # laadt products.json in een al-bestaande tabel (lokaal óf echt AWS)
│   └── bootstrap_terraform_backend.sh  # eenmalige, idempotente backend-setup (S3 + DynamoDB)
└── tests/
    ├── conftest.py              # ThreadedMotoServer + tabel/bus/queues bootstrap
    ├── integration/             # pytest + moto
    └── e2e/                     # Playwright tegen een echte `flask run` + moto
```

## DynamoDB single-table design

Eén tabel, `WebshopTable`, met samengestelde sleutel `PK`/`SK` en één GSI voor
prijsgesorteerde catalogusqueries.

| Entiteit | PK | SK | Belangrijkste attributen |
|---|---|---|---|
| Product | `PRODUCT#<id>` | `METADATA` | title, price_cents, image_url, colors[], rating |
| Winkelwagenregel | `CART#<cart_id>` | `ITEM#<product_id>` | quantity, price_cents (snapshot), color |
| Order | `ORDER#<order_id>` | `METADATA` | status, total_cents, created_at |
| Orderregel | `ORDER#<order_id>` | `ITEM#<product_id>` | quantity, price_cents (snapshot), color |

**GSI1** (`CATEGORY#PRICE-index`) ondersteunt "toon alle bureaulampen, gesorteerd op
prijs":

- `GSI1PK = "CATEGORY#DESK_LAMPS"`
- `GSI1SK = "PRICE#<price_cents, zero-padded naar 8 cijfers>"`

De zero-padding is bewust: zonder padding sorteren prijzen als strings lexicografisch
(`"999" < "1299"` klopt toevallig, maar `"1999" > "19999"` niet), wat tot een stille,
foute sortering leidt. Sorteerrichting wordt bepaald door `ScanIndexForward`
(`True` = laag→hoog, `False` = hoog→laag). Kleurfilter gebeurt met een
`FilterExpression` (`Attr("colors").contains(color)`) bovenop de GSI-query — voor de
schaal van deze PoC-catalogus (22 items) is dat prima; bij een grotere catalogus zou een
aparte `GSI2` per kleur nodig zijn.

## Event-driven architectuur: waarom EventBridge + SQS in plaats van SNS

Bij het plaatsen van een order publiceert de main-app-Lambda **één** `OrderPlaced`-event op
een custom EventBridge-bus. Drie regels routeren dat ene event naar drie losse
SQS-queues, die elk hun eigen consumer-Lambda triggeren via een **native SQS
event-source mapping** (dus SQS polling, niet EventBridge die de Lambda's rechtstreeks
aanroept — dat houdt de queues, en daarmee de retry/DLQ-semantiek, in de architectuur).

**Waarom EventBridge (+ SQS) in plaats van Amazon SNS (+ SQS)?** Beide kunnen fan-out naar
SQS. Het verschil zit in wat je er verder mee kan:

1. **Content-based routing.** SNS filtert op *message attributes* die je apart moet
   meesturen naast de payload. EventBridge filtert direct op de JSON-structuur van het
   event zelf (`source`, `detail-type`, en willekeurige velden onder `detail`). In dit
   project matcht de `notification-rule` bijvoorbeeld op `detail.notify: true` — een
   inhoudelijke conditie op het event, niet op een los attribuut.
2. **Schema Registry & Discovery.** EventBridge kan automatisch een schema afleiden uit
   binnenkomende events en dat registreren, inclusief gegenereerde code-bindings. SNS
   heeft dat concept niet.
3. **Archive & Replay.** EventBridge kan een bus-archief bijhouden en events opnieuw
   afspelen (bijv. na een bug in een consumer). Bij SNS moet je dat zelf bouwen (SNS →
   S3/Firehose → replay-tooling).
4. **Ontkoppeling / fault isolation.** Elke queue heeft hier een eigen DLQ
   (`maxReceiveCount = 3`). Eén tragere of stuk-gaande consumer (bijv. de
   notification-service) beïnvloedt de andere twee niet — berichten stapelen zich alleen
   op in *die* queue en DLQ.

**Eerlijke tegenkant:** SNS is goedkoper en heeft een lagere latency voor eenvoudige
fan-out zonder inhoudelijke filtering. Voor een simpele "stuur dit naar drie plekken"
use case zonder routeringslogica is SNS + SQS vaak de pragmatischere keuze. EventBridge
verdient zich hier terug zodra je routering op basis van de *inhoud* van het event nodig
hebt, of events wil kunnen archiveren/replayen — wat in een groeiend microservices-
landschap typisch sneller gebeurt dan je vooraf denkt.

**Silent-failure-valkuilen die expliciet in de Terraform zijn afgedekt:**

- Een `aws_cloudwatch_event_target` geeft de rule **geen** impliciete
  `sqs:SendMessage`-rechten — elke queue heeft een `aws_sqs_queue_policy` die
  `events.amazonaws.com` toegang geeft, met een `aws:SourceArn`-conditie die scoped is
  op de specifieke rule-ARN (niet op de hele bus).
- Zonder DLQ zou een falende consumer stilletjes berichten laten verdwijnen na de
  standaard retry-policy van SQS; hier is dat zichtbaar via de gedeelde DLQ.

## OWASP Top 10 (2025) — beveiligingsmaatregelen

> Deze tabel is een beknopt overzicht. Voor een uitgebreide uitleg per categorie — wat het
> risico concreet inhoudt en hoe de architectuur/code zich er specifiek tegen beschermt —
> zie [`docs/owasp-top-10.md`](docs/owasp-top-10.md).

| # | Categorie | Maatregel in dit project |
|---|---|---|
| A01 | Broken Access Control | Cart-id komt uitsluitend uit de signed session-cookie, nooit uit request-body/query; order-id's zijn UUID's (niet te raden); elke Lambda heeft een eigen least-privilege IAM-rol (main app: alleen tabel-RW + `events:PutEvents`; elke consumer: alleen `sqs:ReceiveMessage`/`DeleteMessage` op zijn **eigen** queue) |
| A02 | Security Misconfiguration | `PROPAGATE_EXCEPTIONS = False` zodat fouten altijd via de eigen error handlers lopen; `Content-Security-Policy` scoped op de exacte CDN-origins (geen `*`); geen enkele IAM policy-statement gebruikt `Resource: "*"` |
| A03 | Software Supply Chain Failures | Python-dependencies zijn exact gepind in `pyproject.toml` en vastgelegd (inclusief hashes) in `uv.lock`, dat bewust **niet** gitignored is; de HTMX-CDN-script-tag heeft een `integrity`-attribuut (SRI); de Tailwind Play CDN-script-tag kan dat **niet** hebben (zie kanttekening hieronder) maar is wel op een exacte versie-URL gepind; `terraform/.terraform.lock.hcl` is eveneens **niet** gitignored en pint providerversies |
| A04 | Cryptographic Failures | `SECRET_KEY` komt uit een environment variable (nooit hardcoded in code of git); sessioncookie heeft `HttpOnly`, `SameSite=Lax`, `Secure` buiten lokale dev; de Payment-Lambda simuleert alleen — er wordt nooit echte betaalinformatie verwerkt of opgeslagen. **Eerlijke kanttekening:** in deze PoC staat `SECRET_KEY` als plain Lambda-environment-variabele (zichtbaar in de console/state) — prima voor een lokaal-geverifieerde demo, maar een echte productie-deploy zou hem uit AWS Secrets Manager of SSM Parameter Store (`SecureString`) laden bij cold start in plaats van via Terraform als platte env var mee te geven |
| A05 | Injection | Alle DynamoDB-toegang loopt via boto3 `Key`/`Attr`-expression builders (nooit string-concatenatie); Jinja2-autoescape staat overal aan, nergens `\|safe` op gebruikersinvoer |
| A06 | Insecure Design | Checkout hervalideert server-side: kleur moet in de actuele `colors[]` van het product zitten, hoeveelheid wordt geclamped (1–10), en het totaalbedrag wordt herberekend uit de actuele `price_cents` — nooit vertrouwd vanuit de client of zelfs vanuit de opgeslagen cart-regel |
| A07 | Authentication Failures | Buiten scope: dit is een gast-winkelwagen zonder login. Een echte uitbreiding zou Cognito gebruiken in plaats van een zelfgebouwd auth-schema |
| A08 | Software/Data Integrity Failures | Elk `OrderPlaced`-event bevat een `schema_version`-veld; consumers parsen uitsluitend met `json.loads` (nooit `pickle`/`eval`) en rapporteren onleesbare berichten als batch item failure in plaats van te crashen |
| A09 | Logging & Alerting Failures | Gestructureerde JSON-logging in de Flask-app en alle consumer-Lambda's; nooit PII of betaalgegevens in logs; elke Lambda's CloudWatch Log Group heeft een expliciete `retention_in_days` |
| A10 | Mishandling of Exceptional Conditions | Onverwachte fouten geven altijd een generieke Nederlandstalige foutmelding terug (nooit een stacktrace) — een aparte fragment-variant voor HTMX-requests en een volledige pagina voor normale requests; SQS event-source mappings gebruiken `function_response_types = ["ReportBatchItemFailures"]` zodat één kapot bericht niet de hele batch blokkeert |

## Lokaal draaien

Dit project gebruikt [uv](https://docs.astral.sh/uv/) voor dependency- en
Python-versiebeheer — geen handmatige `venv`/`pip`-stappen nodig. `uv sync` leest
`pyproject.toml` + `uv.lock`, installeert automatisch Python 3.13 (gepind via
`.python-version`) als die nog niet aanwezig is, en zet een `.venv` op met exact de
gelockte dependency-versies.

```bash
uv sync
uv run playwright install chromium

export SECRET_KEY="dev-secret-key"
export FLASK_APP="app.main:app"
export FLASK_DEBUG=1   # niet FLASK_ENV -- Flask 3.x leest die niet meer; FLASK_DEBUG=1
                        # zet zowel de auto-reloader (template-/code-wijzigingen worden
                        # opgepikt zonder herstart) als de niet-Secure sessiecookie aan
export TABLE_NAME="WebshopTableLocal"
export EVENT_BUS_NAME="webshop-event-bus-local"

# start een lokale AWS-mock (DynamoDB + EventBridge + SQS) met moto
uv run python -m moto.server -p 5001 &

export DYNAMODB_ENDPOINT_URL="http://localhost:5001"
export EVENTS_ENDPOINT_URL="http://localhost:5001"
export SQS_ENDPOINT_URL="http://localhost:5001"

uv run python -m scripts.bootstrap_local_infra   # maakt de tabel + GSI + event bus/queues/rules aan (idempotent)
uv run python -m scripts.seed_products           # seedt de 22 producten in die tabel
uv run flask run
```

> **Let op:** gebruik `python -m scripts.<naam>`, niet `python scripts/<naam>.py`. Bij een
> direct scriptpad zet Python de map van het script zelf (`scripts/`) vooraan in `sys.path`
> in plaats van de projectroot, waardoor `import app` faalt met `ModuleNotFoundError`. Met
> `-m` (uitgevoerd vanuit de projectroot) staat de projectroot wél op `sys.path`. Dit is
> standaard Python-gedrag, geen uv-quirk.

Twee losse scripts met een bewust smalle naam, om niet dezelfde verwarring te herhalen als
een eerdere versie van dit project had (één `seed_local_table.py`-script dat zowel lokaal
als tegen echte AWS werd gebruikt): `bootstrap_local_infra.py` mag **uitsluitend** tegen de
lokale moto-mock draaien — hij maakt tabel/bus/queues/rules aan zonder de instellingen
(bijv. DLQ-redrive-policies) die Terraform er in het echt wél aan geeft, en zou daar dus op
botsen. `seed_products.py` raakt geen infrastructuur aan en is generiek: die kun je zowel
lokaal als tegen een al door Terraform geprovisionede live omgeving draaien (zie
[Deployment naar AWS](#deployment-naar-aws)).

`bootstrap_local_infra` maakt naast de tabel ook de EventBridge-bus, de drie SQS-queues en
de fan-out rules aan (idempotent, zelfde patroon als `terraform/main.tf`) — Afrekenen
publiceert dus ook lokaal een echt `OrderPlaced`-event dat je met de AWS CLI tegen de
moto-endpoint kunt bekijken (`aws --endpoint-url http://localhost:5001 sqs receive-message
--queue-url <url>`). Mocht je die bootstrap-stap overslaan of de moto-server herstarten
zonder opnieuw te seeden, dan blijft checkout gewoon werken: `publish_order_placed` vangt een
ontbrekende bus af, logt de fout (zie A10) en laat de bestelling gewoon slagen.

## Testen

```bash
# Integratietests: volledig gemockt met moto (DynamoDB, EventBridge, SQS) — geen AWS nodig
uv run pytest tests/integration -v

# End-to-end: Playwright tegen een echte `flask run`-server + dezelfde moto-mock
uv run pytest tests/e2e -v

# Alles
uv run pytest

# Lint/format-check (zelfde als de CI zou draaien)
uv run ruff check app consumers scripts tests
uv run black --check app consumers scripts tests
```

De E2E-suite start zelf een `flask run`-subprocess (géén `sam local`/Docker) en een
`ThreadedMotoServer`, en automatiseert de volledige flow: browsen → filteren op kleur
(HTMX DOM-swap) → lamp toevoegen aan winkelwagen (out-of-band badge-update) → afrekenen →
orderbevestiging.

## Infrastructure as Code (Terraform)

De IaC bestaat uit een root-config plus modules per component:

| Module | Verantwoordelijkheid |
|---|---|
| `dynamodb` | De single-table + GSI1 |
| `eventbridge` | Custom bus + de 3 fan-out rules |
| `sqs` | De 3 queues + gedeelde DLQ |
| `lambda` | Herbruikbaar (4×): bouwt zijn eigen deploy-package, rol, log group |
| `api_gateway` | HTTP API + integratie + route + `$default`-stage |
| `custom_domain` | ACM-cert (DNS-validatie) + Route53-alias + API-mapping naar `webshop-aws-python.kabulter.click` |
| `github_oidc` | OIDC-provider + least-privilege deploy-rol voor GitHub Actions |

`terraform fmt`/`validate` blijven credential-vrij (geen `local-exec`, geen echte
data-source-lookups):

```bash
cd terraform
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
```

`terraform plan`/`apply` provisionen nu wél een echte, live demo — zie
[Deployment naar AWS](#deployment-naar-aws) hieronder voor de volledige procedure.

Elke Lambda-module bouwt zijn eigen deploy-package via een `null_resource` (local-exec naar
`modules/lambda/scripts/build.sh`) die de benodigde broncode kopieert en, alleen voor de
main-app, de runtime-dependencies meebundelt door `uv export` (op basis van `uv.lock`) te
piped'en naar `uv pip install --target --python-platform x86_64-manylinux2014` (matcht
Lambda's eigen runtime-platform, niet het platform waarop je toevallig `apply` draait) — de
drie consumer-Lambda's hebben alleen `boto3` nodig, dat al in de Lambda-runtime zit. `uv`
moet dus geïnstalleerd zijn op elke machine (lokaal én CI) die `terraform apply` uitvoert.

## Deployment naar AWS

**Eenmalige voorbereiding** (met je eigen, persoonlijke AWS-credentials, bijv. via
`aws configure`):

1. **Controleer de gedeelde Route53-zone** — puur ter geruststelling, dit voert geen
   wijziging uit: bevestig dat er nog geen record bestaat op de naam die we zo aanmaken,
   in plaats van dat er alleen over te *redeneren*.
   ```bash
   ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name kabulter.click. \
     --query "HostedZones[0].Id" --output text)
   aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
     --query "ResourceRecordSets[?contains(Name, 'webshop-aws-python')]"
   ```
   Dit moet een lege lijst teruggeven. `kabulter.click` zelf wordt door deze Terraform
   **nooit** aangemaakt, gewijzigd of verwijderd — alleen als `data`-bron opgezocht; alle
   `resource`-blocks voegen uitsluitend records toe voor `webshop-aws-python.kabulter.click`
   en de bijbehorende ACM-validatie-CNAME(s).

2. **Terraform-backend bootstrappen** via `scripts/bootstrap_terraform_backend.sh`
   (idempotent — veilig om opnieuw te draaien):
   ```bash
   cp terraform/backend.env.example terraform/backend.env
   # vul terraform/backend.env in (gitignored) -- de meegeleverde defaults verwijzen al
   # naar de bestaande, gedeelde bucket edwinbulter-terraform-state en tabel
   # terraform-locks; alleen TF_STATE_KEY hoeft uniek te zijn per app
   ./scripts/bootstrap_terraform_backend.sh
   ```
   Dit script maakt de S3-bucket/DynamoDB-tabel **alleen aan als ze nog niet bestaan** —
   `edwinbulter-terraform-state` bestaat al (state van andere projecten erin) en wordt dus
   ongewijzigd hergebruikt; `terraform-locks` is één gedeelde lock-tabel voor alle apps
   (Terraform leidt de lock-key zelf af uit bucket+key, dus er is geen aparte
   "lock toevoegen"-stap per app nodig). Als het script de bucket wél zelf aanmaakt, zet het
   ook meteen versioning, SSE-encryptie en block-public-access aan — niet optioneel: het
   Flask-secret komt zo dadelijk via een `data`-bron in de state terecht, dus de state zelf
   moet net zo goed beveiligd zijn als een secret.

3. **Flask-secret in SSM zetten** (eenmalig; Terraform *leest* deze alleen, en beheert 'm
   nooit, zodat een lokale `apply` en een CI-`apply` altijd exact dezelfde waarde gebruiken
   in plaats van twee losse kopieën die uit elkaar kunnen lopen). Gebruik dezelfde regio als
   in `terraform/backend.env` — een mismatch hier is precies waarom Terraform straks de
   parameter niet kan vinden:
   ```bash
   source terraform/backend.env
   aws ssm put-parameter --name /webshop-aws-python/flask-secret-key \
     --type SecureString --value "$(openssl rand -hex 32)" --region "$AWS_REGION"
   ```

**Eerste, echte `apply`:**

Gebruik de `terraform init`- en `terraform apply`-aanroepen die het bootstrap-script
hierboven aan het eind uitprint (die bevatten exact de waarden uit `terraform/backend.env`,
inclusief `export TF_VAR_aws_region=...`).

`aws_region` heeft in `terraform/variables.tf` **bewust geen default** — de enige plek waar
de regio wordt gedefinieerd is `terraform/backend.env`; overal elders (dit README, de
GitHub-Actions-workflows, de bootstrap-script-output) wordt 'm van daaruit doorgegeven, nooit
opnieuw hardcoded. Zonder `TF_VAR_aws_region` (of `-var="aws_region=..."`) geëxporteerd zal
`terraform apply` er expliciet om vragen in plaats van stilzwijgend de verkeerde regio te
gebruiken.

(`tf_state_bucket_name`/`tf_state_key`/`tf_state_lock_table_name` hebben defaults die al
overeenkomen met `terraform/backend.env.example` — pas ze alleen aan met `-var` als je
`backend.env` van de defaults hebt laten afwijken.)

Dit maakt in één keer alles aan: de tabel, bus, queues, 4 Lambda's, de API, het ACM-cert +
Route53-records voor `webshop-aws-python.kabulter.click`, én de GitHub OIDC-rol voor CI. De
`aws_acm_certificate_validation`-stap **wacht een paar minuten** op DNS-propagatie in de
gedeelde zone — dat is normaal, geen hang. Na afloop toont `terraform output live_url` de
demo-URL en `terraform output github_deploy_role_arn` de rol-ARN voor de volgende sectie.

**Let op:** `terraform apply` maakt de tabel wel aan, maar seedt 'm niet — Terraform beheert
alleen infrastructuur, geen data. Zonder deze stap toont de live demo een lege catalogus.
Seed de 22 producten met hetzelfde `scripts/seed_products.py` als lokaal (zie
[Lokaal draaien](#lokaal-draaien)), maar nu tegen de echte tabel: laat
`DYNAMODB_ENDPOINT_URL`/`EVENTS_ENDPOINT_URL`/`SQS_ENDPOINT_URL` ongezet (dan gaat boto3 naar
echt AWS) en zet de regio expliciet:

```bash
export AWS_REGION="$(grep -oP '(?<=^AWS_REGION=).*' terraform/backend.env)"
uv run python -m scripts.seed_products
```

Veilig om opnieuw te draaien: producten worden overschreven op hun eigen id, nooit
gedupliceerd. Gebruik hier bewust **niet** `scripts/bootstrap_local_infra.py` — dat script is
alleen voor de lokale moto-mock en zou tegen de al-door-Terraform-aangemaakte queues
(die een DLQ-redrive-policy hebben die dit script niet meegeeft) een fout geven.

**Destroy-veiligheid:** `terraform destroy` kan uitsluitend de 2–3 records verwijderen die
déze state heeft aangemaakt (de ACM-validatie-CNAME(s) en de alias A-record) — de zone zelf
is nooit meer dan een `data`-bron zonder Terraform-lifecycle, en geen enkel record van een
ander project staat ergens in deze state.

**Belangrijk voor toekomstige lokale `apply`'s:** doe altijd eerst `git pull`. Een
ongetargete lokale `apply` vanaf een verouderde checkout zou de Lambda-code die de
`deploy.yml`-workflow als laatste heeft uitgerold, stilletjes terugdraaien.

## GitHub Actions (CI/CD)

**`.github/workflows/tests.yml`** — draait op elke push naar `main`, elke pull request, en
handmatig. Geen AWS nodig: dezelfde moto-gemockte integratietests en de Playwright-E2E-suite
tegen een echte lokale `flask run`, exact zoals hierboven bij [Testen](#testen).

**`.github/workflows/deploy.yml`** — **uitsluitend handmatig** (`workflow_dispatch`), en
rolt alléén de 4 Lambda-functies opnieuw uit (`terraform apply -target=...` op precies die
4 resources) — nooit de tabel, bus, queues, DNS of IAM. Er is geen AWS-sleutel in GitHub
nodig: authenticatie loopt via **GitHub OIDC** naar de `github_oidc`-Terraform-module, die
een rol aanmaakt met precies genoeg rechten om Lambda-code te updaten (en verder niets — een
poging om iets anders te wijzigen zou AWS met `AccessDenied` afwijzen, ongeacht wat de
workflow of zijn `-target`-lijst ooit zouden proberen). De `-target`-vlaggen zelf zijn
vooral voor overzicht/blast-radius in de plan-output; de IAM-policy op de rol is de
daadwerkelijke grens.

**Eenmalige GitHub-configuratie** (na de eerste `terraform apply` hierboven):

1. **Environment aanmaken**: repo → Settings → Environments → New environment → naam
   `production`. Voeg jezelf toe als *required reviewer* — dat maakt van "alleen handmatig
   te starten" ook "alleen handmatig te starten én goed te keuren", voor een productie-Lambda
   een zinvolle extra stap.
2. **Repo Variables** (Settings → Secrets and variables → Actions → Variables — **geen
   Secrets nodig**, dit zijn allemaal niet-gevoelige waarden):

   | Variable | Waarde |
   |---|---|
   | `AWS_DEPLOY_ROLE_ARN` | output `github_deploy_role_arn` van de eerste `apply` |
   | `AWS_REGION` | zelfde waarde als `AWS_REGION` in `terraform/backend.env` |
   | `TF_STATE_BUCKET` | zelfde waarde als `TF_STATE_BUCKET` in `terraform/backend.env` |
   | `TF_STATE_KEY` | zelfde waarde als `TF_STATE_KEY` in `terraform/backend.env` |
   | `TF_STATE_LOCK_TABLE` | zelfde waarde als `TF_STATE_LOCK_TABLE` in `terraform/backend.env` |

   Deze vier komen dus letterlijk over uit je eigen (gitignored) `terraform/backend.env` —
   dat bestand blijft de enige plek waar de regio en backend-namen gedefinieerd staan; deze
   repo Variables zijn slechts de manier om diezelfde waarden ook aan CI door te geven.

Daarna: code-wijziging maken, mergen naar `main`, en de `deploy.yml`-workflow handmatig
starten vanuit het Actions-tabblad ("Run workflow") om 'm live te zetten.

## Verwachte AWS-kosten (± 100 API-calls/dag)

Realistische kosteninschatting voor de live demo bij **±100 API-calls per dag
(~3.000/maand)**. Cijfers zijn opgezocht op de officiële AWS-pricingpagina's (regio
us-east-1, peildatum 2026-09-30) — de daadwerkelijke regio staat in `terraform/backend.env`;
EU-regio's liggen doorgaans een fractie hoger, wat op dit volume niets uitmaakt.

**Aannames:** van de 3.000 requests/maand is ~5% (150) een checkout die de
`OrderPlaced`-fan-out triggert (1 EventBridge-event → 3 SQS-berichten → 3
consumer-Lambda-invocaties); gemiddeld ~3 DynamoDB-requests per API-call (browsen,
winkelwagen, checkout samen) → ~9.000 DynamoDB-requests/maand.

| Service | Verbruik/maand | Prijs | Gratis laag | Geschatte kosten |
|---|---|---|---|---|
| Lambda (4 functies) | ~3.450 requests, ~250 GB-seconden | $0,20/1M requests + $0,0000166667/GB-s | **Always Free**: 1.000.000 requests + 400.000 GB-s/maand | $0,00 |
| API Gateway (HTTP API) | 3.000 requests | $1,00/1M requests | 1.000.000/maand, maar **alleen eerste 12 maanden** na account-aanmaak | < $0,01 |
| DynamoDB (on-demand) | ~5.400 reads, ~3.600 writes, < 1 GB opslag | $0,125/1M reads + $0,625/1M writes | 25 GB opslag **Always Free**; on-demand read/write-requests hebben géén gratis laag | < $0,01 |
| EventBridge (custom bus) | 150 PutEvents | $1,00/1M events | geen gratis laag voor custom events | < $0,01 |
| SQS (3 queues + DLQ) | ~1.350 requests (send + receive + delete) | $0,40/1M requests | **Always Free**: 1.000.000/maand | $0,00 |
| CloudWatch Logs | enkele MB | $0,50/GB ingest + $0,03/GB/maand opslag | **Always Free**: 5 GB/maand | $0,00 |
| Data transfer out | enkele tientallen MB | — | **Always Free**: 100 GB/maand | $0,00 |
| Route53 | DNS-queries op de 2–3 records die dit project toevoegt aan de bestaande zone | $0,40/1M queries | geen (maar geen nieuwe hosted-zone-huur: de zone bestond al) | $0,00 |
| ACM-certificaat | 1 cert, DNS-gevalideerd | gratis | — | $0,00 |
| **Totaal** | | | | **ruim onder $0,05/maand** |

Op dit volume blijft praktisch alles binnen AWS's "Always Free"-laag (Lambda, DynamoDB-opslag,
SQS, CloudWatch, data transfer); alleen API Gateway-requests (na het eerste jaar),
DynamoDB on-demand request units en EventBridge-events hebben geen blijvende gratis laag,
maar zijn op 3.000 requests/maand nog steeds fracties van een cent. Dat is precies het punt
van een serverless architectuur: de kosten schalen met daadwerkelijk gebruik in plaats van
met vooraf gereserveerde capaciteit — zelfs bij 10× of 100× dit volume (1.000–10.000
calls/dag) blijft de rekening in de centen-tot-lage-dollars per maand.

**Niet meegerekend** (niet in deze Terraform geprovisioned): NAT Gateway/VPC (deze Lambda's
draaien buiten een VPC, dus geen NAT-kosten) en de S3-bucket + DynamoDB-tabel voor de
Terraform-backend zelf (state-opslag; verwaarloosbaar op dit volume, typisch < $0,01/maand).
Nieuwe AWS-accounts krijgen bovendien tot $200 aan credits voor de eerste 6 maanden, wat dit
soort volumes sowieso ruimschoots dekt.

**Kanttekening bij EventBridge:** AWS introduceerde in september 2026 naast het bestaande
per-event-model ("classic") ook een nieuw per-GB-model voor custom event buses ("enhanced").
Bovenstaande rekent met het classic per-event-model ($1,00/miljoen events); op dit volume is
het verschil met het enhanced-model verwaarloosbaar. Check bij het aanmaken van een bus welk
model van toepassing is.

> Prijzen wijzigen; controleer de actuele tarieven op de officiële AWS-pricingpagina's of via
> de [AWS Pricing Calculator](https://calculator.aws) voordat je hierop een productiebeslissing
> baseert.

## Scope en beperkingen

- Geen echte betaalverwerking, voorraadbeheer of e-mailverzending — de drie
  consumer-Lambda's zijn bewuste PoC-stubs die loggen en een statusveld op de order
  bijwerken.
- Geen gebruikersaccounts/login (gast-winkelwagen via signed cookie).
- Eén omgeving (geen staging/prod-scheiding) — passend bij een single-demo portfolioproject,
  niet bij een meerdere-omgevingen-opzet.
- Productfoto's zijn hotlinked vanaf `ikea.com`; als IKEA die URL's wijzigt, breken de
  afbeeldingen in deze demo (bewuste trade-off, zie de disclaimer bovenaan).
