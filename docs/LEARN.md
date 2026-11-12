# Rootfold — ghid de învățare (română, nivel început)

Luci, citește câte un capitol când lucrăm pe el. Scopul nu e să memorezi definiții, ci să poți **explica cu voce tare** de ce există fiecare piesă. La interviu, un junior care explică clar bate un junior care recită termeni.

---

## 1. Ce este Rootfold, pe scurt

Este un strat de **incidente** care stă *în fața* monitorizării (Zabbix, Prometheus, Grafana), nu în locul ei. Când cade un hop de microunde, douăzeci de echipamente din spate încep să alarmeze. Fără corelare, se deschid douăzeci de tichete. Rootfold le **strânge într-un singur incident de cauză-rădăcină**. Când hop-ul revine, nu închide totul orbește: **așteaptă și cere un OK proaspăt** de la fiecare copil. Dacă backup-ul de pe site e încă stricat, deschide un incident nou („leftover”), nu-l îngroapă odată cu părintele.

Asta e problema reală descrisă pe r/networking în septembrie 2026: după ce circuitul a revenit, tichetele copil s-au închis automat și o eroare de backup a fost observată abia a doua zi.

**Întrebări de interviu**

1. *De ce nu e destul un dashboard Grafana?*  
   Grafana arată metrici și alarme. Nu decide care alarmă e cauza și care e simptomul, nu ține un tichet, și nu re-verifică copiii după ce părintele a revenit.

2. *Ce înseamnă „cauză-rădăcină” aici?*  
   Obiectul cel mai „sus” din topologie care e jos acum (de exemplu circuitul de microunde), nu fiecare switch din spatele lui.

3. *De ce e important să spui că datele de pe demo sunt simulate?*  
   Pentru că la interviu trebuie să fii onest. Ai construit motorul și lab-ul; nu pretinzi că monitorizezi o rețea de producție.

---

## 2. API REST, FastAPI, OpenAPI / Swagger

Un **API REST** este un set de URL-uri prin care un program vorbește cu altul, de obicei cu JSON. `GET` citește, `POST` creează/trimite, `PUT` actualizează, `DELETE` șterge.

**FastAPI** e un framework Python care scrie aceste rute și, din modelele Pydantic, generează automat documentația.

**OpenAPI / Swagger** este „meniul” API-ului. Îl vezi la `/api/docs`: poți citi ce rute există și le poți testa. La interviu, mulți angajatori (inclusiv roluri de NOC/L3) întreabă dacă știi să citești un Swagger și să faci un apel cu `curl`.

**Întrebări de interviu**

1. *Ce vezi dacă deschizi `/api/docs`?*  
   Documentația interactivă a API-ului (rute, parametri, exemple). Este generată din aplicație, nu scrisă de mână într-un Word.

2. *Ce diferență e între GET și POST?*  
   GET doar citește (incidente, topologie). POST trimite date (login, ingest de alarme, import de topologie).

3. *De ce documentăm API-ul?*  
   Ca un coleg, un webhook Zabbix sau un script să știe exact ce să trimită, fără să citească tot codul.

---

## 3. Autentificare: JWT vs cheie API

**JWT** (JSON Web Token) e un bilet semnat pe care îl primește un operator după login (`/api/auth/login`). Îl pui în header: `Authorization: Bearer <token>`. Expiră. E pentru oameni (UI, curl, interviu).

**Cheia API** e un secret lung (`rfk_...` sau cheia de lab) pe care îl pune un sistem în `X-API-Key`. E pentru mașini: Alertmanager, Zabbix, un script. Nu e un parolă de om; se poate revoca fără a schimba parola adminului.

Nu trimitem parolele în fiecare request. Parola se folosește o dată, la login. Cheile se stochează **hash-uite**, nu în clar.

**Întrebări de interviu**

1. *De ce nu folosim aceeași parolă și pentru webhook-uri?*  
   Webhook-ul e un sistem, nu un om. Dacă cheia scapă, o revoici. Parola operatorului rămâne valabilă. Drepturile sunt separate.

2. *Ce e un JWT, pe scurt?*  
   Un token semnat de server, cu un termen de expirare, care dovedește că te-ai autentificat deja.

3. *Unde se pune cheia API?*  
   În header-ul `X-API-Key`, pe rutele de ingest.

---

## 4. Baza de date: SQLAlchemy, SQLite, Postgres

**SQLAlchemy** e biblioteca prin care Python vorbește cu o bază SQL, fără să scriem totul în SQL brut. Modelele (`Site`, `Alert`, `Incident`) sunt tabele.

**SQLite** e un fișier pe disc (sau în memorie, la teste). Perfect pentru lab și pentru un singur proces.

**Postgres** e serverul de baze folosit în producție, cu mai mulți clienți concomitent. URL-ul e configurabil (`ROOTFOLD_DATABASE_URL`). Am scris modelele ca să poată trece pe Postgres fără tipuri speciale de SQLite.

**Întrebări de interviu**

1. *Când e destul SQLite și când treci pe Postgres?*  
   SQLite pentru un lab sau un singur nod. Postgres când ai mai multe procese, backup-uri serioase, sau mai mulți operatori simultani.

2. *Ce face un „model” SQLAlchemy?*  
   Descrie o tabelă (coloane, chei) și îți permite să citești/scrii rânduri din Python.

3. *De ce testele folosesc o bază „in-memory”?*  
   Ca fiecare test să pornească curat, fără să lase date pe disc și fără să se influențeze între ele.

---

## 5. Topologie: site-uri, device-uri, circuite, LACP, dependențe

**Site** = o locație (PoP, DC, un oraș).  
**Device** = un echipament (router, switch, radio, server).  
**Circuit / hop** = o legătură: fibră, microunde, etc. Are două capete (A și Z).  
**LACP bundle** = două (sau mai multe) legături legate împreună ca un singur „țeavă” logică. Dacă *un* membru cade, traficul poate rămâne pe celălalt. Dacă *cad toți*, pachetul e jos.

**Dependență părinte–copil:** dacă părintele e jos, alarmele copilului sunt de obicei *simptome*, nu cauze noi. Exemplu: hop-ul Onești–Dărmănești e părintele site-ului Dărmănești; Comănești e în spatele Dărmăneștiului.

În Rootfold mai există și dependențe **implicite**: un device e copilul site-ului său; un membru LACP e copilul bundle-ului.

**Întrebări de interviu**

1. *Ce e LACP, pe scurt?*  
   Agregare de linkuri: două fibre lucrează ca un singur uplink, cu rezervă dacă una se rupe.

2. *De ce un switch inaccesibil nu e automat cauza, când tot site-ul e mut?*  
   Pentru că de obicei s-a rupt uplink-ul (fibră sau microunde). Switch-ul e un simptom.

3. *Ce e un „blast radius”?*  
   Lista a ce e afectat dacă obiectul-rădăcină e jos: site-uri, echipamente, circuite, eventual clienți.

---

## 6. Webhook-uri: Alertmanager și Zabbix

Un **webhook** e un apel HTTP pe care îl face un sistem către altul când se întâmplă ceva. Zabbix sau Alertmanager trimit un JSON la `/api/ingest/zabbix` sau `/api/ingest/alertmanager`.

Rootfold **normalizează** formatele diferite într-o alarmă internă (nume, status firing/resolved, obiect din topologie). Nu trebuie să înlocuim NMS-ul; trebuie doar să-l configurăm să trimită evenimentele aici.

**Întrebări de interviu**

1. *Ce e un webhook?*  
   O notificare automată prin HTTP, de obicei JSON, când un eveniment apare sau se închide.

2. *De ce avem trei rute de ingest?*  
   Pentru că Alertmanager, Zabbix și un script propriu trimit JSON-uri diferite. Fiecare rută știe formatul ei.

3. *Ce se întâmplă dacă alarma nu se potrivește cu un obiect din topologie?*  
   Nu o aruncăm. Deschidem un incident de sine stătător, ca să nu se piardă.

---

## 7. Corelare și recovery sweep

**Corelare:** toate alarmele care „atârnă” de același părinte jos intra în același incident.

**Recovery sweep:** când alarma-părinte trece pe rezolvat:

1. Incidentul nu se închide imediat. Trece în `sweep_pending`.
2. Așteptăm N secunde (implicit 5 minute; în teste, 60, ca să nu dormim).
3. OK-urile venite *chiar atunci* când a revenit circuitul sunt **stale** (false, sau prea devreme). Nu contează ca succes.
4. După fereastră, fiecare copil trebuie să aibă un OK **proaspăt** (datat după `sweep_after`).
5. Ce n-are OK proaspăt, sau e încă `firing`, devine un incident `leftover`.

Asta evită scenariul: „totul s-a închis, dar backup-ul era tot stricat”.

**Întrebări de interviu**

1. *De ce nu închidem incidentul în momentul în care circuitul revine?*  
   Pentru că alarmele copil pot fi închise automat de NMS fără ca serviciul din spate să fi fost cu adevărat verificat.

2. *Ce e un „fresh OK”?*  
   O confirmare de sănătate sosită *după* fereastra de stabilizare, nu o ștergere de alarmă venit odată cu revenirea uplink-ului.

3. *Cine rulează sweep-ul?*  
   Doi drumuri: `POST /api/ops/sweep` (manual, operator autentificat) și un scheduler de fundal cu interval configurabil (`ROOTFOLD_SWEEP_INTERVAL_SECONDS`). În teste intervalul e 0, ca loop-ul să nu pornească.

---

## 8. Fereastra de mentenanță

Dacă anunți o fereastră (schimb de radio, tăiere de fibră planificată) pe un circuit sau un site, alarmele de pe acel obiect **și de pe descendenți** sunt **suppressed**: se salvează, dar nu deschid incident de outage. Altfel, fiecare lucrare planificată ar arăta ca o cădere.

**Întrebări de interviu**

1. *De ce suprimăm și copiii, nu doar obiectul din fereastră?*  
   Pentru că dacă oprești hop-ul, toate device-urile din spate vor alarma. Sunt așteptate.

2. *Ce risc există dacă uiți să închizi fereastra?*  
   O cădere reală de după lucrare ar putea fi ignorată. De aceea ferestrele au `ends_at`.

3. *E la fel cu „acknowledge” pe o alarmă?*  
   Nu. Acknowledge înseamnă „am văzut alarma”. Mentenanța înseamnă „ne așteptam la ea, nu e incident”.

---

## 9. Reverse proxy, Caddy, TLS

Un **reverse proxy** (Caddy sau Nginx) stă în fața aplicației: primește HTTPS de la operatori și transmite HTTP intern către FastAPI. El termină **TLS** (certificatul, cifrul, HTTPS).

În lab, Caddy folosește **CA internă** (`tls internal`): un certificat de încredere doar pe mașinile tale, gratuit, bun pentru Docker local. În producție ai un certificat public (Let’s Encrypt). Nu pretindem că lab-ul e un site public cu CA de încredere globală.

Caddy mai pune **security headers** (HSTS, X-Frame-Options, etc.) și rutează `/healthz`.

**Întrebări de interviu**

1. *Ce face un reverse proxy?*  
   Primește cererile din exterior, termină HTTPS, și le trimite către aplicația din spate.

2. *De ce nu expunem FastAPI direct pe internet cu HTTP?*  
   Traficul ar fi în clar, fără un punct unic pentru certificate, headere și jurnalizare.

3. *Ce e un certificat „internal CA”?*  
   Un certificat emis de o autoritate pe care o instalezi tu pe mașinile de lab. Browserul nu are încredere în el implicit, și e ok — e doar pentru dezvoltare.

---

## 10. Docker Compose, loguri JSON, pytest, CI

**Docker Compose** pornește mai multe containere împreună (API + Caddy) cu un singur fișier. Asta e „self-host”: altcineva poate rula același stack.

**Loguri JSON** (câte un obiect pe linie, cu `ts`, `level`, `msg`) se citesc ușor de un SIEM sau de `jq`. Sunt preferate față de texte libere.

**pytest** rulează testele, inclusiv scenariul din septembrie 2026. Dacă cineva strică sweep-ul, testul cade.

**GitHub Actions** (`.github/workflows/ci.yml`) rulează lint + teste la fiecare push, pe Python 3.11 și 3.12. Încă nu publicăm repo-ul; fișierul e pregătit.

**Întrebări de interviu**

1. *Ce verifică testul „Reddit Sept 2026”?*  
   Că după revenirea părintelui, un copil fără OK proaspăt devine incident nou, iar părintele se închide fără să-l îngroape.

2. *Ce e CI?*  
   Teste (și lint) rulate automat pe un server, nu doar pe laptopul tău.

3. *De ce Docker și pentru un proiect mic?*  
   Ca un angajator sau un coleg să poată porni totul cu `docker compose up`, inclusiv proxy-ul cu TLS, fără să instaleze manual Python și Caddy.

---

## 11. Consola de operator (UI)

Nu e un frontend cu React sau un „build” cu Vite. E **HTML + CSS + JavaScript vanilla**, fișiere statice servite de FastAPI din `src/rootfold/static/`. Deschizi `http://127.0.0.1:8000/`, te autentifici, și consola vorbește cu aceleași rute pe care le vezi în Swagger.

De ce așa, nu un SPA complicat? Ca să poți deschide `app.js` la interviu și să arăți, linie cu linie, login-ul, lista de incidente, poarta L1, harta și handover-ul. Un angajator de junior vede că înțelegi HTTP, JWT în `localStorage`, și rute (aici cu **hash**: `#/incidents`, `#/topology`). Nu pretindem un design system de produs mare; e un aspect de NOC, întunecat, utilizabil și pe telefon (meniul de jos sub 800px).

Butonul de reset și cele de inject (**microwave fade**, **fiber LOS**, **LACP member down**, **parent recover with leftover child**) trimit alerte simulate în laborătorul Carpathian Carrier. Nu sunt o rețea reală.

**Întrebări de interviu**

1. *Ce înseamnă „vanilla JS”?*  
   JavaScript rulat în browser, fără un framework (React/Vue) și fără un pas de compilare. Fișierul pe care îl scrii e fișierul pe care îl servește serverul.

2. *De ce JWT stă în localStorage? E riscant?*  
   E simplu pentru un lab. Dacă un script rău ajunge pe pagină, poate citi token-ul. În producție se discută cookie HttpOnly. La interviu e bine să spui ambele părți.

3. *Cum evită UI-ul să ocolească regula de pe server?*  
   Butoanele de escalate/resolve sunt dezactivate până e poarta completă, dar **regula adevărată e în API** (422). UI-ul e doar o explicație vizuală. Dacă cineva apelează API-ul cu curl fără poartă, tot e blocat.

---

## 12. Poarta de calitate L1 (quality gate)

Înainte ca un operator să **escaladeze** sau să **rezolve** un incident, trebuie să completeze:

- **impact**: `site-down` | `degraded` | `customer-impact` | `no-customer-impact`
- **urgency**: `high` | `medium` | `low`
- cel puțin un **check** (ex. ping la capătul îndepărtat, calendar de mentenanță)
- **notes** de minim 10 caractere

`PUT /api/incidents/{id}/gate` salvează câmpurile. `POST .../escalate` și `POST .../resolve` răspund **422** dacă poarta e incompletă. Consola face același lucru: butoanele stau disabled.

Excepție importantă: când **sweep-ul** închide părintele (hop-ul a revenit, copiii verificați), incidentul se rezolvă cu `resolved_by=sweep` **fără** poartă. Operatorul nu a apăsat Resolve; sistemul a curățat un incident al cărui root cause a dispărut. Leftover-ul rămâne deschis și *acela* cere poartă dacă vrei să-l închizi tu.

**Întrebări de interviu**

1. *De ce forțăm impact, urgență, check-uri și note?*  
   Ca un L1 să nu escaladeze „down down plz” sau să închidă un ticket fără să fi verificat nimic. E o durere reală în NOC-uri; ticket-urile slabe ajung la L2 și se întorc.

2. *De ce nu e destul să blocăm doar în UI?*  
   Pentru că un script, un webhook sau curl pot ocoli pagina. Regula trebuie să trăiască în API.

3. *De ce sweep-ul sare poarta?*  
   Poarta e pentru *oameni* care iau o decizie. Sweep-ul e o acțiune automată, jurnalizată, după o regulă pe care o poți explica (fresh OK). Nu vrem să blocăm curățenia automată până completează cineva un formular.

---

## 13. Predarea schimbului (shift handover)

La sfârșitul turei, operatorul apasă **Build handover from open incidents**. Sistemul face un **snapshot** cu incidentele încă deschise (`open`, `sweep_pending`, `escalated`), plus notele tale. Nu e un email liber scris din memorie: e lista reală din baza de date.

Handover-ul stă în `pending_ack`. **Turul care vine trebuie să apese Acknowledge.** Până atunci nu poți închide un al doilea handover (422). În lab, user-ul `night` / `changeme` e turul de noapte, ca să poți demonstra curgerea în doi oameni.

**Întrebări de interviu**

1. *De ce nu e destul un document Word / un canal de chat?*  
   Pentru că se uită incidente, se copiază greșit, și nimeni nu semnează că a preluat. Snapshot-ul + ack lasă o urmă: cine a închis tura, ce era deschis, cine a preluat.

2. *Ce se întâmplă dacă tura nouă nu dă ack?*  
   Rămâne `pending_ack`, apare un banner în consolă, și nu poți deschide alt handover până se rezolvă. Ideea e să nu se piardă predarea.

3. *Snapshot-ul se actualizează după ce un incident se închide?*  
   Nu. E o fotografie la momentul predării, ca tura nouă să vadă *ce au primit*, nu o listă care se schimbă pe sub ei.

---

## 14. Scheduler-ul de sweep

În Week 1 sweep-ul rula doar dacă cineva apela `POST /api/ops/sweep`. În Week 2 există și un **loop de fundal**: la fiecare `ROOTFOLD_SWEEP_INTERVAL_SECONDS` (implicit 15 în lab, 0 în teste = oprit) aplicația apelează aceeași logică `tick_sweeps`.

Ruta manuală rămâne, pentru demo și pentru un operator care nu vrea să aștepte intervalul. Dacă schimbi intervalul din `PUT /api/ops/settings`, e nevoie de restart ca loop-ul să folosească noua valoare — e scris așa, nu e un bug ascuns.

**Întrebări de interviu**

1. *De ce nu e destul un cron în afara aplicației?*  
   Poți avea și cron. Scheduler-ul în proces e mai simplu de pornit cu `make run` / Compose, fără un al treilea container. Dezavantaj: dacă procesul e jos, loop-ul e jos. De aceea există și trigger-ul manual.

2. *De ce în teste intervalul e 0?*  
   Ca testele să fie deterministe. Nu vrem ca un thread de fundal să închidă incidente în timp ce un test verifică starea. Testele apelează `tick_sweeps` sau `POST /api/ops/sweep` când vor ele, cu un ceas înghețat (`FrozenClock`).

3. *Ce rol are delay-ul de 5 minute (`recovery_sweep_seconds`) față de intervalul scheduler-ului?*  
   Sunt două lucruri. Delay-ul e „cât așteptăm după revenirea părintelui înainte să judecăm copiii”. Intervalul e „din cât în cât rulăm acea judecată”. Dacă delay-ul e 300s și intervalul 15s, sweep-ul efectiv se întâmplă la primul tick *după* ce au trecut cele 300s.

---

## 15. Teste Playwright (fum / smoke UI)

**Playwright** deschide un Chromium adevărat, apasă butoane, completează formulare și verifică ce vede operatorul. Nu înlocuiesc testele pytest de API: acelea sunt rapide și precise. Playwright-ul prinde lucruri de UI (buton disabled, login greșit, inject + leftover vizibil, ack de handover cu user-ul `night`).

Rulezi `make test` (sau `make test-ui`). Prima dată: `uv run playwright install chromium`. Dacă browserul lipsește, testele de UI sunt sărite, nu cad toată suita. Screenshot-urile din `docs/screenshots/ui-*-desktop.png` și `ui-*-mobile.png` sunt generate de un test, ca să poți reface imaginile când schimbi interfața.

**Întrebări de interviu**

1. *Ce e un „smoke test”?*  
   Un test scurt care verifică că drumurile principale nu sunt rupte (login, un inject, poarta, handover), nu fiecare colț al aplicației.

2. *De ce și API, și UI tests?*  
   Testul de API îți spune că regula e corectă (422 fără poartă). Testul de UI îți spune că operatorul chiar vede butonul disabled și poate completa formularul. Una fără alta lasă găuri.

3. *De ce nu testăm UI-ul cu TestClient și HTML parsat?*  
   Pentru că JavaScript-ul din consolă trebuie să ruleze într-un browser. TestClient îți dă HTML-ul gol de la `/`; logica e în `app.js`.

---

## 16. Import din NetBox

**NetBox** e un inventar de rețea (site-uri, device-uri, cabluri, circuite). Mulți NOC-uri îl folosesc ca „sursa adevărului” pentru topologie. Rootfold nu înlocuiește NetBox: îl **citește** și mapează obiectele în propriul graf, ca alarmele să aibă unde să se lipească.

Autentificarea e un **token** în header (`Authorization: Token …`), luat din `ROOTFOLD_NETBOX_URL` și `ROOTFOLD_NETBOX_TOKEN`. Importer-ul trage `/api/dcim/sites/`, `/api/dcim/devices/`, `/api/dcim/cables/` și `/api/circuits/circuits/`, urmează paginarea, apoi face upsert după slug.

Cablurile din același site (un patch intern) sunt sărite — nu sunt un hop între PoP-uri. Circuitele de provider (fibră, microunde) și cablurile între două site-uri devin circuite Rootfold.

Ca să poți explica și testa fără un NetBox viu, există un **fixture JSON înregistrat** (`tests/fixtures/netbox.json`). CLI: `rootfold import-netbox --fixture tests/fixtures/netbox.json`. API: `POST /api/topology/import-netbox`.

**Întrebări de interviu**

1. *De ce nu copiem tot NetBox-ul 1:1?*  
   Rootfold are nevoie doar de relația părinte-copil și de hop-uri, nu de fiecare rack unit sau cablu de patch. Maparea e deliberat îngustă și explicabilă.

2. *Ce e un „recorded fixture”?*  
   Un răspuns API salvat pe disc. Testele îl citesc în loc să cheme internetul, deci sunt deterministe și nu depind de un lab NetBox.

3. *Ce se întâmplă la al doilea import?*  
   Upsert după slug: obiectele existente se actualizează, nu se dublează.

---

## 17. Export de tichete (Jira și ServiceNow)

L2/L3 din multe firme lucrează în **Jira** sau **ServiceNow**, nu în Rootfold. Exportul construiește un payload standard:

- Jira Cloud REST v3: `POST /rest/api/3/issue`, descriere în format ADF (Atlassian Document Format)
- ServiceNow: `POST /api/now/table/incident`, cu impact/urgency mapate 1–3

Credențialele vin din env (`ROOTFOLD_JIRA_*`, `ROOTFOLD_SNOW_*`). Dacă nu sunt setate, exportul e **dry-run**: vezi exact JSON-ul care s-ar trimite, dar nu pleacă nimic. Butonul **Export** din consolă face preview; **Send** e dezactivat până configurezi un backend. Testele mockuiesc HTTP, nu vorbesc cu Jira real.

**Întrebări de interviu**

1. *De ce dry-run implicit când nu e configurat?*  
   Ca un operator (sau un recruiter în lab) să vadă payload-ul fără să scriem din greșeală într-un Jira de producție.

2. *De ce Jira v3 cere ADF, nu text simplu?*  
   API-ul Cloud v3 a trecut descrierile pe un document structurat (paragrafe, text). E un detaliu pe care e bine să-l știi la interviu.

3. *Unde trăiește regula „nu trimite dacă lipsește token-ul”?*  
   În API, nu doar în UI. Butonul Send disabled e o curtoazie; un `dry_run=false` fără config primește 422.

---

## 18. Runbook-uri și bifarea check-urilor L1

Un **runbook** e o procedură scurtă: ce verifici când cade un hop de microunde, un LOS de fibră, un membru LACP, un DNS etc. În repo sunt opt: microwave fade / RSL low, fiber LOS, LACP member down, LACP bundle down, high CRC / interface errors, DNS failure, VPN tunnel down, power / site down. În Rootfold stau ca fișiere **Markdown** în `docs/runbooks/`, cu un antet YAML (id, titlu, cuvinte de potrivire, lista de check-uri) și un corp explicativ.

Când se deschide un incident, Rootfold **atașează automat** runbook-ul care se potrivește (numele alarmei, keyword-uri, media circuitului). Bifarea unui check din runbook se scrie imediat în câmpul `checks` al porții L1. Nu sare restul porții: tot îți trebuie impact, urgență și note.

**Întrebări de interviu**

1. *De ce Markdown în repo, nu un wiki extern?*  
   Ca runbook-ul să fie versionat cu același git ca aplicația, review-uit, și disponibil offline în lab.

2. *Ce se întâmplă dacă două runbook-uri se potrivesc?*  
   Le arătăm pe toate, cu un scor; cel cu scorul cel mai mare e „suggested”.

3. *De ce bifa din runbook nu închide singură poarta L1?*  
   Check-urile sunt doar una din cele patru cerințe. Impactul, urgența și notele rămân decizii ale operatorului.

---

## 19. Raportul lunar de disponibilitate

Pentru fiecare circuit, site și client, raportul calculează pe o lună calendaristică (UTC):

- **număr de incidente** care se suprapun cu luna
- **downtime** ca reuniune de intervale (dacă două incidente se suprapun, timpul comun se numără o dată)
- **uptime %** = 100 × (1 − downtime / durata lunii)
- **MTTR** = media (resolved_at − opened_at) pentru incidentele rezolvate
- **SLA breach** dacă uptime-ul e sub prag (implicit 99.9%, `ROOTFOLD_SLA_PERCENT`)

API: `GET /api/reports/availability?year=2026&month=9` (JSON sau `format=csv`). În consolă, pagina Reports are download CSV și Print/PDF (print-ul din browser). Testele folosesc septembrie 2026 și un ceas înghețat, ca cifrele să fie exacte.

**Întrebări de interviu**

1. *De ce reuniune de intervale, nu sumă?*  
   Dacă două tichete acoperă aceeași oră pe același circuit, circuitul nu a fost „down de două ori”. Suma ar umfla downtime-ul.

2. *Ce e MTTR?*  
   Mean Time To Repair: cât a durat, în medie, până s-a închis incidentul. În Rootfold include și așteptarea de sweep, pentru că incidentul rămâne deschis până atunci.

3. *De ce UTC și nu fusul operatorului?*  
   Raportul trebuie să fie identic indiferent de laptop. Fusul se poate discuta ulterior; acum e explicit și testabil.

---

## Cum te pregătești tu, practic

- Pornește API-ul (`make run`), deschide `http://127.0.0.1:8000/`, loghează-te cu `admin` / `changeme`. Topologia exemplu se importă singură la primul login.
- Din pagina Lab, injectează *Microwave fade*, deschide incidentul, arată blast radius-ul, timeline-ul și runbook-ul atașat. Bifează un check din runbook — apare în poarta L1. Încearcă Escalate fără restul porții (butonul e disabled).
- Apasă Export: vezi un preview dry-run de payload Jira (nimic nu se trimite, lab-ul nu are Jira configurat).
- Deschide Reports, încarcă luna curentă, descarcă CSV-ul.
- Rulează offline `rootfold import-netbox --fixture tests/fixtures/netbox.json` pe o bază goală și explică maparea.
- Reset, apoi *Parent recovers, leftover child remains*. Arată că backup-ul a rămas incident separat.
- Construiește un handover, ieși, intră cu `night` / `changeme`, dă ack.
- Deschide și `/api/docs` și explică aceleași rute în Swagger, ca să se vadă că UI-ul nu e o aplicație paralelă.
- Explică cu voce tare, în română sau engleză, de ce leftover-ul nu trebuie să dispară cu părintele.
