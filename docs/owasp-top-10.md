# OWASP Top 10 (2025) — risico's en maatregelen in detail

De tabel in de hoofdmap [README.md](../README.md#owasp-top-10-2025--beveiligingsmaatregelen)
geeft per OWASP-categorie in één zin de genomen maatregel. Dit document legt per categorie
uit **wat het risico concreet inhoudt** en **hoe de architectuur en code van dit project
zich er specifiek tegen beschermen** — voor lezers die niet dagelijks met OWASP werken.

## A01 — Broken Access Control

**Wat is het risico?** Een gebruiker (of aanvaller) kan bij gegevens of acties die niet van
hem zijn, omdat de applicatie identiteit niet goed afdwingt. Klassiek voorbeeld: een
webshop leest de winkelwagen-ID uit een query-parameter (`?cart_id=123`) — een aanvaller
verandert die waarde en ziet ineens de winkelwagen van iemand anders, of erger, plaatst een
order namens iemand anders.

**Hoe dit project dit voorkomt:**
- De winkelwagen-ID komt **uitsluitend** uit de server-side signed session-cookie
  (`app/session_cart.py`, `get_or_create_cart_id()`), nooit uit een request-body of
  query-parameter die de client kan aanpassen. Zelfs als een aanvaller een andere
  `cart_id`-waarde probeert te raden of te verzinnen, wordt die genegeerd — de route-handlers
  in `app/routes/cart.py` en `app/routes/checkout.py` lezen de cart-ID nooit uit
  gebruikersinvoer.
- Order-ID's zijn UUID's (`uuid.uuid4()` in `app/routes/checkout.py`), niet oplopende
  nummers. Oplopende ID's (`ORDER#1`, `ORDER#2`, …) zouden een aanvaller in staat stellen
  simpelweg te "tellen" en bestellingen van anderen te bekijken.
- Elke Lambda-functie heeft in Terraform (`terraform/modules/lambda`) een **eigen**,
  krap toegesneden IAM-rol: de main-app-Lambda mag alleen bij de DynamoDB-tabel en
  `events:PutEvents`; elke consumer-Lambda mag alleen `sqs:ReceiveMessage`/`DeleteMessage`
  op **zijn eigen** queue. Zelfs als één functie gecompromitteerd zou raken, kan die niet
  bij de queues of resources van de andere functies.

## A02 — Security Misconfiguration

**Wat is het risico?** Een applicatie lekt onbedoeld informatie of staat onbedoeld méér toe
dan nodig door verkeerd ingestelde standaardwaarden: debug-modus aan in productie
(stacktraces zichtbaar voor bezoekers), een IAM-policy die per ongeluk `Resource: "*"`
gebruikt (toegang tot *alle* resources in plaats van de bedoelde ene tabel), of een
Content-Security-Policy die alles toestaat (`script-src *`) waardoor XSS-bescherming
zinloos wordt.

**Hoe dit project dit voorkomt:**
- `app/main.py` zet `PROPAGATE_EXCEPTIONS = False` **expliciet**, ook al zou Flask's
  `TESTING`/`DEBUG`-modus dat anders automatisch overschrijven. Zo lopen fouten altijd via
  de eigen, veilige error handlers — nooit via Flask's ingebouwde debugger die interne
  code en variabelen zou tonen.
- De `Content-Security-Policy`-header (ingesteld via `after_request` in `app/main.py`)
  noemt de CDN-origins (`cdn.jsdelivr.net`, `cdn.tailwindcss.com`) met naam, in plaats van
  een wildcard. Een script van een andere, kwaadwillende bron kan hierdoor niet laden, zelfs
  niet als die via een XSS-kwetsbaarheid zou worden geïnjecteerd.
- In de volledige Terraform-configuratie (`terraform/main.tf` en alle modules) komt
  **nergens** `Resource: "*"` voor in een IAM policy-statement — elke rechten-toekenning is
  gescoped op de exacte ARN van de tabel, bus of queue die de functie nodig heeft.

## A03 — Software Supply Chain Failures

**Wat is het risico?** Je applicatie is net zo veilig als de externe code die ze inlaadt.
Een niet-gepinde dependency (`flask>=3.0`) kan zonder dat je het merkt een nieuwe, kwetsbare
of zelfs gecompromitteerde versie ophalen bij de volgende install. Hetzelfde geldt voor een
extern CDN-script: als de host van `cdn.example.com` wordt gehackt en het script wordt
vervangen, laadt de browser van elke bezoeker straks kwaadaardige JavaScript — zonder dat de
applicatiecode zelf is aangepast.

**Hoe dit project dit voorkomt:**
- `requirements.txt` en `requirements-dev.txt` pinnen elke dependency op een **exacte**
  versie (`flask==3.1.0`, niet `flask>=3.1.0`). Een nieuwe, ongeteste versie van een
  dependency kan dus nooit stilzwijgend meekomen bij een herinstallatie.
- De HTMX- en Tailwind-`<script>`-tags in `app/templates/base.html` hebben een
  `integrity="sha384-…"`-attribuut (Subresource Integrity). De browser berekent zelf de
  hash van het gedownloade script en vergelijkt die met de verwachte waarde; komt die niet
  overeen (bijv. omdat de CDN gehackt is en een ander bestand serveert), dan **weigert de
  browser het script uit te voeren** — dit is dus een technische garantie, geen belofte.
- `terraform/.terraform.lock.hcl` is bewust **niet** opgenomen in `.gitignore` en pint de
  exacte versies van de Terraform-providers (`hashicorp/aws`, `hashicorp/archive`,
  `hashicorp/null`), zodat `terraform init` altijd dezelfde, geverifieerde providercode
  ophaalt.

## A04 — Cryptographic Failures

**Wat is het risico?** Gevoelige gegevens (wachtwoorden, sessies, betaalgegevens) worden
onvoldoende beschermd — bijvoorbeeld een hardcoded secret in de broncode (zichtbaar voor
iedereen met leestoegang tot de git-historie), een sessiecookie zonder beveiligingsvlaggen
(leesbaar door JavaScript of over een onversleutelde verbinding), of het onnodig opslaan van
gevoelige data zoals creditcardnummers.

**Hoe dit project dit voorkomt:**
- `app/main.py` leest `SECRET_KEY` (waarmee Flask de sessiecookie ondertekent) uit een
  environment variable via `os.environ["SECRET_KEY"]` — er staat bewust **geen** fallback-
  waarde in de code, dus de app start niet op zonder dat de sleutel expliciet is meegegeven.
  Er staat dus nooit een sleutel in de git-historie.
- De sessiecookie krijgt `HttpOnly` (onleesbaar voor JavaScript, dus niet te stelen via een
  XSS-injectie), `SameSite=Lax` (wordt niet meegestuurd bij cross-site requests, een
  CSRF-verdedigingslaag) en `Secure` buiten lokale ontwikkeling (wordt alleen over HTTPS
  verstuurd).
- De Payment-Lambda (`consumers/payment_service/handler.py`) is een bewuste PoC-stub: hij
  *simuleert* een betaling en werkt alleen een statusveld bij. Er wordt nergens een
  creditcardnummer, IBAN of ander betaalmiddel verwerkt of opgeslagen — data die je niet
  opslaat, kan ook niet lekken.
- **Eerlijke kanttekening:** `SECRET_KEY` wordt in de Terraform-configuratie als platte
  Lambda-environment-variabele doorgegeven (zichtbaar in de AWS-console en in de Terraform
  state). Voor deze lokaal-geverifieerde PoC is dat een bewuste, gedocumenteerde
  vereenvoudiging; een echte productiedeploy zou de sleutel bij het opstarten ophalen uit
  AWS Secrets Manager of SSM Parameter Store (`SecureString`).

## A05 — Injection

**Wat is het risico?** Gebruikersinvoer wordt zonder scheiding tussen "code" en "data"
doorgegeven aan een interpreter — het klassieke voorbeeld is SQL-injectie
(`"SELECT * FROM users WHERE id = " + user_input`), maar hetzelfde principe geldt voor
NoSQL-databases (een handgebouwde DynamoDB-expressie) en voor HTML (ongefilterde
gebruikersinvoer die direct in een pagina wordt gerenderd, oftewel XSS).

**Hoe dit project dit voorkomt:**
- Alle DynamoDB-toegang in `app/repositories/single_table.py` gebruikt boto3's
  `Key`/`Attr`-expression builders (bijv. `Key("GSI1PK").eq(...)`,
  `Attr("colors").contains(color)`). Deze bouwen de `KeyConditionExpression`/
  `FilterExpression` op met correct geëscapete placeholders
  (`ExpressionAttributeValues`) — nergens wordt een string met gebruikersinvoer
  samengeplakt tot een expressie.
- Jinja2 (de templating-engine achter Flask) heeft **autoescape** overal aan staan — elke
  variabele die in een `.html`-bestand wordt getoond, wordt automatisch HTML-geëscapet.
  Nergens in `app/templates/` staat een `|safe`-filter op gebruikersinvoer, wat die
  bescherming zou uitschakelen.

## A06 — Insecure Design

**Wat is het risico?** De applicatielogica zelf vertrouwt impliciet gegevens die een
aanvaller kan beïnvloeden — ook al is er geen "bug" in de klassieke zin. Bijvoorbeeld: de
prijs van een product wordt als verborgen veld in het bestelformulier meegestuurd, en de
server rekent daarmee af in plaats van de prijs zelf op te zoeken. Een aanvaller past dat
verborgen veld simpelweg aan met de browser-devtools en koopt een lamp van €39,99 voor
€0,01.

**Hoe dit project dit voorkomt:**
- De checkout-route (`app/routes/checkout.py`) vertrouwt **nooit** een prijs, kleur of
  aantal die van de client komt. Voor elke regel in de winkelwagen wordt het actuele
  product opnieuw opgezocht in DynamoDB, wordt gecontroleerd of de gekozen kleur nog steeds
  in `product.colors` voorkomt, wordt het aantal geclamped tussen `MIN_ITEM_QUANTITY` en
  `MAX_ITEM_QUANTITY`, en wordt het totaalbedrag herberekend uit de **actuele**
  `product.price_cents` — nooit uit de waarde die al in de winkelwagen-regel stond.
  Dit gebeurt zelfs als iemand rechtstreeks (buiten de UI om) een winkelwagen-regel met een
  ongeldige kleur of een absurd hoog aantal in de tabel zou weten te zetten (zie
  `tests/integration/test_checkout_and_events.py::test_checkout_rejects_cart_item_with_stale_color`
  en `::test_checkout_clamps_a_tampered_quantity_to_the_max`, die dit scenario expliciet
  simuleren en verifiëren).
- Dezelfde server-side validatie zit al bij het toevoegen aan de winkelwagen
  (`app/routes/cart.py::add_to_cart`): een onbekende kleur voor het product levert een
  `400`-fout op in plaats van stilzwijgend te worden geaccepteerd.

## A07 — Authentication Failures

**Wat is het risico?** Zwakke of zelfgebouwde authenticatie — bijvoorbeeld eigen
wachtwoord-hashing, voorspelbare sessie-ID's, of het ontbreken van rate-limiting op een
inlogpoging — waardoor accounts overgenomen kunnen worden.

**Hoe dit project dit voorkomt:** Deze PoC heeft **bewust geen gebruikersaccounts of login**
— het is een gast-winkelwagen, geïdentificeerd via de signed session-cookie (zie A01/A04).
Er is dus geen zelfgebouwd authenticatiesysteem dat kwetsbaar zou kunnen zijn. Mocht dit
project uitgebreid worden met accounts, dan is de aanbeveling om een beproefde
identity-provider zoals Amazon Cognito te gebruiken in plaats van zelf
wachtwoord-opslag/sessiebeheer te bouwen.

## A08 — Software or Data Integrity Failures

**Wat is het risico?** Data of code wordt vertrouwd zonder te verifiëren dat die
authentiek en onbeschadigd is. In een event-driven architectuur is een concreet risico dat
een consumer een event van een oudere of andere schema-versie binnenkrijgt en dat verkeerd
interpreteert (bijv. een veld dat van betekenis is veranderd), of dat een payload wordt
gedeserialiseerd met een onveilige methode zoals Python's `pickle`, waarmee een aanvaller
in theorie willekeurige code zou kunnen laten uitvoeren.

**Hoe dit project dit voorkomt:**
- Elk `OrderPlaced`-event (`app/events/publisher.py`) bevat een `schema_version`-veld.
  Consumers kunnen hierop controleren welke vorm van het event ze binnenkrijgen, zodat een
  toekomstige schemawijziging niet stilzwijgend tot verkeerde interpretatie leidt.
- De drie consumer-handlers (`consumers/*/handler.py`, via `consumers/common.py`) parsen de
  binnenkomende SQS-body **uitsluitend** met `json.loads()` — nooit met `pickle` of `eval`,
  die willekeurige Python-code zouden kunnen uitvoeren als de payload gemanipuleerd is.
- Een bericht dat niet als geldige JSON geparsed kan worden, wordt niet gecrasht op, maar
  expliciet gerapporteerd als `batchItemFailure` (zie A10), zodat het via de
  event-source-mapping-retry en uiteindelijk de DLQ terechtkomt in plaats van de hele batch
  te laten falen of stilzwijgend te worden genegeerd.

## A09 — Logging & Alerting Failures

**Wat is het risico?** Als er te weinig gelogd wordt, valt een aanval of storing pas laat
(of nooit) op. Als er juist té veel of het verkeerde gelogd wordt — bijvoorbeeld
wachtwoorden, sessietokens of creditcardnummers in platte tekst in CloudWatch Logs — wordt
het logsysteem zelf een datalek-risico. Onbeperkte logretentie is bovendien een stille
kostenpost én een compliance-risico (data die je had moeten verwijderen, staat er nog).

**Hoe dit project dit voorkomt:**
- De Flask-app en alle drie de consumer-Lambda's loggen gestructureerd (JSON) via Python's
  standaard `logging`-module (zie bijv. `logger.info(json.dumps({...}))` in
  `consumers/payment_service/handler.py`), wat de logs machine-leesbaar en doorzoekbaar
  maakt in CloudWatch Logs Insights.
- Er wordt bewust **nooit** PII of betaalgegevens gelogd — de gelogde velden zijn beperkt
  tot niet-gevoelige identifiers zoals `order_id` en `total_cents`.
- Elke Lambda-functie krijgt in Terraform (`terraform/modules/lambda/main.tf`,
  `aws_cloudwatch_log_group`) een **expliciete** `retention_in_days`, in plaats van de
  AWS-standaard van "voor altijd bewaren" aan te houden.

## A10 — Mishandling of Exceptional Conditions

**Wat is het risico?** Een onverwachte fout (een bug, een tijdelijke storing bij een
afhankelijkheid) leidt tot gedrag dat de situatie erger maakt dan nodig: een stacktrace die
interne bestandspaden, code of database-details aan de bezoeker toont, of — in een
event-driven systeem — één enkel kapot of onverwacht bericht dat een hele batch van tien
berichten laat mislukken en daarmee negen prima berichten onnodig laat herhalen of
vastlopen.

**Hoe dit project dit voorkomt:**
- `app/main.py` registreert een generieke `@app.errorhandler(Exception)` die **nooit** de
  originele foutmelding of stacktrace teruggeeft aan de bezoeker, maar altijd een vaste,
  vriendelijke Nederlandstalige boodschap. Er is een aparte variant voor HTMX-requests
  (een klein HTML-fragment, `_error_fragment.html`) versus normale paginabezoeken (een volledige
  foutpagina, `error.html`), zodat de gebruikerservaring consistent blijft met hoe de rest
  van de UI werkt.
- De SQS-event-source-mappings voor de drie consumer-Lambda's zijn in Terraform
  geconfigureerd met `function_response_types = ["ReportBatchItemFailures"]`. Gecombineerd
  met de per-bericht `try/except` in `consumers/common.py::process_sqs_event`, betekent dit
  dat als bericht 3 van de 10 in een batch corrupt is, alleen dát bericht wordt
  teruggemeld voor retry — de andere negen worden gewoon succesvol verwerkt in plaats van
  ook opnieuw aangeboden te worden.
- (Server-Side Request Forgery, van oudsher een apart OWASP-nummer en nu onderdeel van deze
  bredere categorie, is hier laag risico: de enige externe URL's in de applicatie zijn de
  vaste, hotlinked IKEA-productafbeeldingen uit de seed-data — de server doet zelf nooit een
  uitgaand verzoek naar een door de gebruiker opgegeven URL.)
