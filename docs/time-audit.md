# Auditoria temporal — simulació d'activitat

## Abast i conclusió

La lògica de fitxatge i permisos ja desa timestamps explícits i conserva la
zona `Europe/Madrid`, però només alguns mètodes de permisos accepten un
`now` opcional. Els endpoints del terminal no l'exposen, el fitxatge ordinari
consulta directament el rellotge i les actuacions de supervisió registren
l'hora real. Per tant, encara no es pot executar una simulació històrica
coherent exclusivament mitjançant l'API.

La proposta d'aquesta fase és només d'auditoria. No s'ha modificat cap funció
ni cap endpoint.

## Fonts temporals i dependències

### Temps de negoci

| Àrea | Codi actual | Ús de la data/hora |
| --- | --- | --- |
| Fitxatge ordinari | `timeclock/database.py`: `create_punch()` (595–597); `app.py`: `POST /api/punch` (1496–1546) | Crea el timestamp del fitxatge i determina si l'últim fitxatge correspon al dia local actual per detectar seqüències anòmales. |
| Estat i inici de permisos | `get_employee_leave_context()` (1162–1196), `start_employee_leave()` (1199–1276); `POST /api/leave/options` (1432–1441) i `POST /api/leave/start` (1444–1470) | Determina el dia local, la continuïtat d'una entrada anterior i l'hora del fitxatge/inici. `start_employee_leave()` ja accepta `now`. |
| Finalització i retorn | `finish_employee_leave()` (1278–1342), `punch_with_open_leave()` (1369–1448); `POST /api/leave/finish` (1473–1493) i `POST /api/punch` (1496–1527) | Crea l'hora de retorn, valida l'ordre temporal, calcula durada i canvi de dia, crea incidències i actualitza la decisió diària. Tots dos mètodes accepten `now`; el context també. |
| Regularització del retorn | `regularize_employee_leave_return()` (1816–1884); `POST /api/admin/leaves/<id>/regularize-return` (602–612) | Valida que l'hora declarada no sigui futura respecte de `datetime.now(timezone.utc)` i registra `regularized_at` amb hora real. |
| Regularització d'entrada/sortida | `regularize_employee_leave_late_arrival()` (1886–1937) i `regularize_employee_leave_early_departure()` (1939–2005); endpoints corresponents a `app.py` (615–638) | Desa les hores previstes i posa l'hora real de regularització a `regularized_at`. |
| Decisions i incidències | `_refresh_daily_leave_decision()` (1466–1626), `decide_daily_leave()` (1733–1779), `decide_employee_leave()` (2040–2079), `set_punch_incident_status()` (992–1023); endpoints de decisió i revisió a `app.py` (641–687, 674–687, 1010–1025) | Agrupa permisos per data local, recalcula minuts i invalidacions, i enregistra timestamps d'historial, aprovació/rebuig i revisió. |
| Classificació i historial de supervisió | `classify_employee_leave_departure()` (2007–2037), consultes de supervisió (1629–1730) i endpoints de `app.py` (572–687) | La classificació no consulta el rellotge; les consultes ordenen i presenten dates persistides. |
| Correcció de fitxatges | `correct_punch()` (923–975); `PATCH /api/admin/punches/<id>` (983–1007) | La data efectiva corregida la proporciona l'administrador; `corrected_at` és el moment d'auditoria de la correcció. |
| Còmputs i informes | `timeclock/hours_report.py`: `build_hours_report()` (83–...) i `/api/admin/hours-report`, `/api/admin/hours-report.xlsx` (`app.py` 820–843) | Fan servir dates inicial/final explícites i timestamps persistits; durades es calculen entre instants normalitzats a UTC. No depenen del rellotge actual. |

Les decisions diàries es desen a `daily_leave_decision.local_date` i les
decisions històriques migrades continuen sense enllaç a una decisió diària;
els fluxos nous poden agrupar intervals per treballadora, tipus i data local
(`timeclock/database.py:1466–1524`, `docs/leave-configuration.md:51–60`).

### Temps de seguretat i operació

Aquestes fonts han de continuar usant el temps real i no han de rebre el rellotge
simulat:

- `app.py:241–277`: límits d'intents PIN d'empleada i PIN d'USB amb
  `time.monotonic()`.
- `app.py:285–302`, `1144–1210`, `1284–1302`: caducitat de tokens
  d'identificació i autoritzacions USB amb `time.monotonic()`. Les renovacions
  després d'una confirmació també són de seguretat (`1467`, `1490`, `1524`,
  `1540`).
- Sessions d'administració Flask (30 minuts), caducitat i invalidació per
  `admin_user.updated_at` (`app.py:214–220, 452–467`;
  `docs/architecture.md:102–110`).
  Canvis de contrasenya/PIN i activació de comptes actualitzen aquesta versió
  (`timeclock/database.py:741–919`).
- `create_terminal_event()` (`timeclock/database.py:661–668`), hora de salut a
  `GET /api/admin/settings` (`app.py:742–753`), nom del CSV USB
  (`app.py:1329–1330`) i manifest de còpia (`backup.py:44`) són marques
  temporals operatives/auditoria, no timestamps d'activitat simulada.
- SQLite no usa `CURRENT_TIMESTAMP` ni `CURRENT_DATE` per a les regles de
  negoci. Els timestamps es desen com ISO amb zona horària; les funcions
  SQLite `local_timestamp_date` i `utc_timestamp_sort_key`
  (`timeclock/database.py:17–49`) en preserven data de Madrid i ordre real,
  inclosa la transició d'horari d'estiu/hivern.
- El rellotge del navegador en `static/app.js` i `static/admin.js` és de
  presentació i interacció; no és una font d'autoritat per al backend.

## Canvis mínims proposats per a la fase B

1. Consolidar la referència temporal de negoci amb un paràmetre opcional
   `current=None`, resolt dins de la funció en `Europe/Madrid`, en lloc de
   canviar el rellotge del sistema. Conservar la compatibilitat de les crides
   existents.
2. Completar l'ús de la referència a `create_punch()`, les regularitzacions i
   qualsevol timestamp d'historial de supervisió generat durant decisions o
   correccions. Passar la mateixa referència al llarg de les operacions
   compostes (`/api/punch`, permís obert, finalització i refresc de decisió)
   perquè les validacions i els timestamps derivats siguin coherents.
3. Afegir un únic punt d'entrada a l'API per llegir la data simulada només en
   entorn de desenvolupament/proves. Les rutes del terminal el validaran una
   sola vegada i la transmetran a les funcions de negoci. Els valors d'hores
   explícits de regularització continuaran validant-se contra aquesta mateixa
   referència.
4. No propagar la referència a cap mecanisme de seguretat ni a marques de
   sistema. No canviar còmputs, política d'aprovació, precisió, estructura de
   base de dades ni format de timestamp.
5. Els informes continuaran filtrant per dates que el client indica
   explícitament; no necessiten un nou rellotge.

## Protecció contra falsificació en producció

Un valor temporal rebut del client no és fiable. El servidor només l'ha
d'acceptar quan una opció de configuració confiable del procés habiliti
explícitament el mode de simulació per a desenvolupament/proves. La
configuració ha de fallar de manera tancada: absència o valor invàlid vol dir
rellotge real; en producció s'ha de rebutjar qualsevol petició que inclogui el
camp simulat, i l'opció no s'ha de poder habilitar des d'una petició HTTP.
L'habilitació no ha d'exposar-se a la configuració ordinària d'administració.
La caducitat de sessions, tokens i límits d'intents es manté amb el temps real
monotònic.

Abans d'implementar-ho, cal confirmar quin indicador d'entorn existent pot
garantir inequívocament que el procés no és el WSGI de producció. Si no n'hi
ha cap, la fase B haurà d'afegir una opció local de procés amb valor
predeterminat desactivat i una comprovació explícita que el WSGI desplegat no
l'accepti.

## Riscos i proves necessàries

- **Regressió de comportament per defecte:** totes les crides sense `current`
  han de continuar donant el mateix comportament; cobrir amb la suite completa
  existent.
- **Coherència entre operacions:** provar una sola referència al crear el
  fitxatge, iniciar/finalitzar permisos, validar retorns, crear incidències,
  actualitzar i invalidar decisions, i escriure l'historial de supervisió.
- **Canvis d'hora i data local:** provar timestamps amb `Europe/Madrid`, les
  dues ocurrències de l'hora repetida a la tardor, l'hora inexistent a la
  primavera, canvis de dia local i intervals que travessen mitjanit. Les
  durades han de continuar calculant-se en UTC.
- **No acceptar dates futures:** provar la validació de retorn regularitzat
  tant amb hora real com amb referència simulada, inclosos instants amb zona
  horària diferent.
- **Separació de seguretat:** provar que enviar una data simulada no canvia la
  caducitat ni el límit de PIN, i que l'API no l'accepta quan el mode no està
  explícitament habilitat, especialment en configuració de producció.
- **Informes i historial:** contrastar els resultats per dates històriques,
  incloses hores treballades, permisos reconeguts, incidències i històric de
  decisions.

## Estat de la fase

Auditoria completada. La fase B no s'ha iniciat. Cal aprovació expressa abans
de fer canvis funcionals.
