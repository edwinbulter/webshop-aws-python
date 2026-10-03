# AVG (GDPR) en Cyberbeveiligingswet (NIS2) — nalevingsanalyse

De tabel in de hoofdmap [README.md](../README.md#avg-en-cyberbeveiligingswet-nis2) geeft een
beknopt overzicht. Dit document legt per onderwerp uit **wat de wet vereist** en **hoe deze
applicatie zich daartoe verhoudt** — inclusief de punten waar dat (nog) niet het geval is.
Net als `docs/owasp-top-10.md` verbergt dit document geen hiaten: waar iets ontbreekt, staat
dat expliciet, niet stilzwijgend verondersteld.

## Deel 1 — AVG (GDPR)

### 1. Gegevensinventarisatie

| Gegeven | Waar opgeslagen | Waarom |
|---|---|---|
| E-mailadres | Cognito User Pool + `USER#<sub>`/`PROFILE` (`app/models/user.py`) | Account/inloggen, contact over een bestelling |
| Voornaam, achternaam | `USER#<sub>`/`PROFILE` | Op naam zetten van aflever-/factuuradres |
| Aflever- en factuuradres (naam, straat, postcode, plaats, land) | `USER#<sub>`/`PROFILE`, `Address` in `app/models/user.py` | Bezorging, facturatie |
| Bestelgeschiedenis (producten, bedragen, status, tijdstip) | `ORDER#<id>`-items (`app/models/order.py`), gekoppeld via `user_sub` | Uitvoering van de koopovereenkomst, klantenservice |
| Sessiegegevens (`cognito_sub`, e-mail, rollen) | `SESSION#<id>`-item (`app/auth/session.py`) | Authenticatie — heeft al een TTL van 8 uur, zie [Gebruikersrollen & authenticatie](../README.md#gebruikersrollen--authenticatie) |

Gast-bestellingen (geen account) bevatten geen `user_sub` en zijn dus niet aan een persoon
te koppelen vanuit de data zelf.

### 2. Grondslag per verwerking (Art. 6 AVG)

- **Bestelling plaatsen/uitvoeren** (profiel, adres, orderregels): uitvoering van een
  overeenkomst (Art. 6(1)(b)).
- **Profiel bewaren voor een volgend bezoek**: uitvoering van de overeenkomst/gerechtvaardigd
  belang (Art. 6(1)(b)/(f)) — de klant kan dit zelf aanpassen of (zie hiaat 4.3) nog niet zelf
  laten verwijderen.
- **Marketing/nieuwsbrief**: niet van toepassing — `consumers/notification_service/handler.py`
  simuleert uitsluitend een orderbevestiging (logt en zet een statusveld); er wordt nergens
  toestemming voor marketing gevraagd of een e-mailadres voor dat doel gebruikt, omdat er
  domweg geen marketingfunctie bestaat.

### 3. Rechten van betrokkenen (Art. 15–21 AVG)

| Recht | Status |
|---|---|
| Inzage (Art. 15) | ✅ Aanwezig — `/account` toont het profiel, `/account/orders` de volledige bestelgeschiedenis |
| Rectificatie (Art. 16) | ✅ Aanwezig — `POST /account` (`app/routes/account.py`) past het profiel aan |
| Vergetelheid / verwijdering (Art. 17) | ✅ Aanwezig — `/account/delete` (`app/routes/account.py::delete_account`): verwijdert het Cognito-account en het profiel (naam/adres) na herbevestiging van het wachtwoord. Bestellingen blijven bewust bewaard als gepseudonimiseerd transactierecord — zie bewaartermijnen hieronder voor waarom dat een aparte keuze is |
| Dataportabiliteit (Art. 20) | ✅ Aanwezig — `/account/export` (`app/routes/account.py::export_data`) levert profiel + volledige bestelgeschiedenis als downloadbaar, machineleesbaar JSON-bestand, zonder interne opslagdetails (geen `PK`/`SK`/GSI-sleutels) |
| Bezwaar/beperking (Art. 18/21) | Niet van toepassing — er is geen profilering en geen marketingverwerking om bezwaar tegen te maken |

### 4. Bewaartermijnen (Art. 5(1)(e) AVG — opslagbeperking)

Sessies verlopen vanzelf (TTL, 8 uur, zie `app/auth/session.py`). Een klant kan nu zelf
profielgegevens laten verwijderen op verzoek (`/account/delete`, zie hierboven) — maar dat
is verwijdering **op aanvraag**, geen **automatische** bewaartermijn: er bestaat geen
geplande taak die inactieve profielen of oude bestellingen vanzelf opruimt na een vaste
periode. Dat blijft een **hiaat**. Nederlandse fiscale bewaarplicht verplicht een
ondernemer doorgaans om financiële administratie (waaronder verkoopfacturen/orders)
**7 jaar** te bewaren — dit is precies waarom `/account/delete` bewust alleen het profiel
verwijdert en bestellingen intact laat (zie `single_table.delete_user_profile`'s docstring):
"op verzoek verwijderen" (het AVG-recht) en "bestellingen een vaste periode bewaren om
fiscale redenen" zijn **twee aparte beslissingen**, die dus ook niet in één generieke knop
samengevoegd zijn. Wat nog ontbreekt is de andere kant van diezelfde medaille: een
geautomatiseerd proces dat bestellingen **na** die 7 jaar daadwerkelijk opruimt, in plaats
van ze voor altijd te bewaren.

### 5. Beveiliging van de verwerking (Art. 32 AVG)

Dit overlapt grotendeels met de al bestaande beveiligingsmaatregelen — zie
[OWASP Top 10](owasp-top-10.md) voor de volledige uitleg (toegangscontrole, encryptie,
sessiebeheer, CSRF, etc.), in plaats van die hier te herhalen.

**Expliciete kruisverwijzing — dit is een gegevensbeschermingsrisico, niet alleen een
beveiligingsrisico**: de admin-backoffice (`/admin/customers/<email>`) toont volledige
persoonsgegevens (naam, adres, bestelgeschiedenis) van elke geregistreerde klant, en de
`admin@demo.nl`-inloggegevens staan — op uitdrukkelijk verzoek van de opdrachtgever, voor
demo-doeleinden — publiek in dit README. Elke bezoeker die zich met echte persoonsgegevens
registreert op de live demo, is daarmee zichtbaar voor iedereen die het publieke
admin-wachtwoord gebruikt. Dit is al benoemd in de OWASP-review (A01); het staat hier nogmaals
expliciet omdat het **primair een AVG-risico is**, niet alleen een toegangscontrole-risico —
de README's "Demo-inloggegevens"-sectie waarschuwt bezoekers al om geen echte
persoonsgegevens te gebruiken, wat de praktische mitigatie is zolang dit niet structureel is
opgelost.

### 6. Verwerkers en sub-verwerkers

AWS (Cognito, DynamoDB, Lambda, CloudWatch Logs) is de enige verwerker. AWS biedt een
standaard AVG-verwerkersovereenkomst (DPA) aan die automatisch van toepassing is via de AWS
Service Terms — er is geen aparte overeenkomst nodig zolang alleen standaard AWS-diensten
gebruikt worden, wat hier het geval is. Er zijn geen overige sub-verwerkers: er wordt geen
echte e-maildienst (bijv. SES, SendGrid) aangeroepen — zie punt 2 hierboven.

### 7. Doorgifte buiten de EU

Niet van toepassing. Alle AWS-resources draaien in `eu-central-1` (Frankfurt, EU) — zie
`terraform/backend.env`. De enige externe aanroepen zijn de productafbeeldingen, die
rechtstreeks door de **browser van de bezoeker** bij `ikea.com` worden opgehaald (hotlinking,
zie de disclaimer bovenaan het README) — dit loopt nooit via de eigen server en is dus geen
serverzijdige "doorgifte" van persoonsgegevens in de zin van de AVG.

### 8. Transparantie (Art. 13/14 AVG)

❌ **Hiaat** — er bestaat geen privacyverklaring/privacybeleid-pagina die uitlegt welke
gegevens verzameld worden, met welk doel, hoe lang, en bij wie een betrokkene terecht kan met
vragen of klachten.

### 9. Cookies

De sessiecookie (`app/main.py`, `SESSION_COOKIE_HTTPONLY`/`SAMESITE`/`SECURE`) is strikt
functioneel: zonder deze cookie werkt inloggen, de winkelwagen en afrekenen niet. Er bestaat
geen tracking- of marketingcookie in deze applicatie. Functionele cookies zijn uitgezonderd
van de cookietoestemmingsplicht (ePrivacy-richtlijn, doorwerkend via de AVG) — er ontbreekt
dus **bewust** geen cookiebanner; dit is geen hiaat.

### 10. Datalekken (Art. 33/34 AVG)

❌ **Hiaat** — er bestaat geen gedocumenteerd incident-response-/datalekprotocol. Mocht een
datalek zich voordoen, dan geldt een meldplicht aan de Autoriteit Persoonsgegevens binnen
**72 uur** nadat het lek bekend is geworden (Art. 33) — er is op dit moment geen proces dat
die termijn structureel haalbaar maakt (wie wordt gewaarschuwd, wie beoordeelt de impact, wie
meldt).

### 11. Functionaris Gegevensbescherming (FG/DPO)

Niet verplicht op deze schaal — er is geen grootschalige systematische monitoring en geen
grootschalige verwerking van bijzondere persoonsgegevens (Art. 37).

## Deel 2 — Cyberbeveiligingswet (NIS2)

### 1. Toepasselijkheidsanalyse

De Cyberbeveiligingswet (de Nederlandse implementatie van de EU NIS2-richtlijn, van kracht
sinds 2026-08-15) geldt voor "essentiële" en "belangrijke" entiteiten in 18 aangewezen
sectoren (energie, drinkwater, transport, bankwezen, financiële marktinfrastructuur,
gezondheidszorg, digitale infrastructuur, overheid, ruimtevaart, post-/koeriersdiensten,
afvalbeheer, chemie, voedsel, bepaalde maakindustrie, digitale aanbieders zoals
online-marktplaatsen/zoekmachines/sociale platforms, beheerde (beveiligings)dienstverleners,
en onderzoek). De standaard EU-drempel sluit **micro- en kleine ondernemingen** uit,
ongeacht sector, met een beperkt aantal uitzonderingen (unieke aanbieder van een kritieke
dienst, gekwalificeerde trust-/DNS-/TLD-dienstverleners, overheidsinstanties) die hier niet
van toepassing zijn.

**Conclusie**: dit project is een persoonlijk, niet-commercieel portfolioproject — geen
geregistreerde onderneming, laat staan een middelgrote of grote onderneming in een
aangewezen sector. De Cyberbeveiligingswet is daarmee **niet van toepassing**. Dit is een
conclusie op basis van schaal en aard van het project, geen garantie die blijft gelden als
dit project ooit een echte, commerciële onderneming zou worden.

### 2. Vrijwillig toegepaste praktijken

Hoewel de wet niet van toepassing is, is het nuttig om te laten zien welke NIS2-achtige
basismaatregelen dit project toch al (grotendeels toevallig, via de OWASP-georiënteerde
beveiligingsaanpak) toepast, en welke bewust niet:

| NIS2-maatregelcategorie | Status in dit project |
|---|---|
| Risicobeheer | Gedeeltelijk — zie `docs/owasp-top-10.md`, geen formeel risicoregister |
| Incidentafhandeling | ❌ Geen formeel proces — zie AVG-hiaat 10 hierboven, hetzelfde hiaat |
| Bedrijfscontinuïteit | Niet van toepassing op deze schaal (PoC, geen SLA naar derden) |
| Beveiliging van de toeleveringsketen | Gedeeltelijk — afhankelijkheden zijn gepind (`uv.lock`, `terraform/.terraform.lock.hcl`), zie OWASP A03; geen formeel leveranciersbeleid |
| Kwetsbaarhedenbeheer | Gedeeltelijk — geen geautomatiseerde dependency-scanning ingericht |
| Toegangsbeheer | ✅ Sterk aanwezig — zie OWASP A01/A07 (RBAC, least-privilege IAM, Cognito) |
| Versleuteling | ✅ Aanwezig in transit (HTTPS/TLS) en via AWS-beheerde encryptie at rest; zie OWASP A04 voor de kanttekeningen |
| Basis cyberhygiëne/training | Niet van toepassing (eenpersoonsproject) |

**Eerlijke kanttekening**: MFA staat uit op de Cognito User Pool — al expliciet
gedocumenteerd als bewuste PoC-scope-keuze in `docs/owasp-top-10.md` (A07), niet een
toevallige omissie, maar wel een punt waar NIS2's "multi-factor authentication"-basismaatregel
(als de wet wél van toepassing was) tegenaan zou lopen.
