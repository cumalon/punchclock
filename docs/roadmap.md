# TimeClockPi — Roadmap

Aquest document recull l'ordre de treball actual del projecte. Les fases marcades com a completades corresponen a funcionalitats implementades i validades al terminal de referència.

## 1. Base del terminal — completat

- Raspberry Pi 2 Model B i Raspberry Pi Display V1.1.
- Raspberry Pi OS Lite.
- Backend Flask servit amb Waitress.
- SQLite com a font de dades local.
- Arrencada i recuperació automàtiques amb systemd.
- Chromium en mode kiosk sobre Wayland/labwc.
- Funcionament offline per als fitxatges.

## 2. Fitxatge bàsic per PIN — completat

- Identificació de treballadors per PIN.
- PIN emmascarat a la pantalla.
- Entrada i sortida.
- Tokens curts d'identificació.
- Detecció i confirmació de seqüències anòmales.
- Històric de fitxatges no destructiu.
- Limitació temporal d'intents incorrectes de PIN de treballador.
- Ordenació cronològica segura a través dels canvis DST d'Europe/Madrid, mantenint la representació local.

## 3. Administració web — completat

- Autenticació d'administradors.
- Sessions i protecció CSRF.
- Gestió de treballadors i configuració.
- Consulta i filtratge de fitxatges.
- Exportació CSV.
- Correccions auditables.
- Revisió i reobertura d'incidències amb historial.
- Canvi de contrasenya.
- PIN individual de sis dígits per administrador.
- Invalidació de sessions quan l'administrador és desactivat o canvien les seves credencials.

## 4. USB, exportació i recuperació — completat

- Detecció, muntatge i desmuntatge controlat d'USB.
- Muntatge amb `nosuid,nodev,noexec`.
- Exportació de fitxatges des del kiosk.
- Autorització amb PIN individual d'administrador.
- Token temporal i d'un sol ús.
- Bloqueig temporal després de cinc intents incorrectes.
- Auditoria d'intents, autoritzacions i exportacions sense registrar el PIN.
- Escriptura atòmica del CSV, `fsync` i verificació binària abans de l'expulsió.
- Expulsió segura de l'USB.
- Infraestructura de backup, verificació, restore i rollback automàtic validada.
- Restore privilegiat restringit amb staging tractat com a no fiable i journal privat de root.
- Recuperació automàtica abans d'arrencar el backend si un tall interromp un restore.

## 5. Backup/restore al web admin — completat

- Crear backups des de l'administració web.
- Llistar backups disponibles al dispositiu USB.
- Seleccionar i preparar una restauració.
- Confirmacions clares abans d'aplicar un restore.
- Mostrar l'estat i el resultat de l'operació.
- Mantenir backup/restore fora del kiosk.

## 6. Redisseny visual del kiosk i del web admin — completat

Donar a tot TimeClockPi una identitat visual coherent, professional, agradable i fàcil d'utilitzar. El kiosk ha de continuar sent tàctil, simple i lleuger per al Raspberry Pi 2; el web admin ha de tenir una interfície de gestió clara, moderna i eficient.

- Redissenyar la pantalla d'inici.
- Incorporar el logotip i la identitat visual de l'empresa.
- Definir tipografia, espaiat, jerarquia visual i estil coherent.
- Millorar botons, teclat numèric, missatges i diàlegs.
- Fer més clars els estats d'entrada, sortida, èxit, error i incidència.
- Millorar les transicions i el feedback tàctil/visual sense carregar el hardware.
- Revisar la pantalla USB perquè segueixi el mateix llenguatge visual.
- Adaptar correctament tots els elements a la resolució real de la pantalla.
- Fer proves d'ús al terminal físic i ajustar llegibilitat, contrast i mides tàctils.
- Preparar recursos gràfics i logos de manera que es puguin substituir fàcilment.
- Redissenyar el web admin amb un aspecte professional coherent amb el kiosk.
- Incorporar al web admin els logos i la identitat corporativa corresponents.
- Definir una capçalera/navegació administrativa clara i consistent.
- Millorar taules, formularis, filtres, botons, avisos, diàlegs i estats buits.
- Diferenciar visualment accions normals, sensibles i destructives.
- Millorar la llegibilitat dels historials de fitxatges, incidències i auditories.
- Fer que kiosk i administració comparteixin una base visual comuna sense forçar la mateixa distribució ni densitat d'informació.
- Mantenir els recursos i CSS prou lleugers per al hardware del terminal i navegadors d'administració habituals.

La primera versió de producció utilitzarà el PIN com a mètode d'identificació. RFID i empremta no són requisits per al desplegament inicial i es reprendran més endavant.

## 7. Hardware d'identificació — ajornat després de la primera posada en producció

- Investigar i integrar RFID.
- Estudiar la comunicació amb el Suprema SFM5020-1M.
- Si és viable, integrar identificació per empremta.
- Mantenir el PIN com a mètode alternatiu.
- Conservar la separació entre identitat del treballador i credencial física.

## 8. Hardware auxiliar — ajornat després de la primera posada en producció

- Integrar/provar speaker o buzzer.
- Estudiar LEDs disponibles.
- Integrar el relé si hi ha una funció real que ho justifiqui.
- Definir feedback sonor coherent amb la interfície.

## 9. Robustesa de producció — fase actual

- Comportament davant talls elèctrics.
- Recuperació davant errors o corrupció.
- Control d'espai de disc.
- Logs i rotació.
- Watchdog.
- Funcionament sense xarxa.
- Sincronització i validació de l'hora.
- Gestió d'errors de perifèrics.
- Procediment d'actualització.
- Procediment d'instal·lació/reinstal·lació.
- Helpers de recuperació i serveis adaptats al layout de producció (`punch`, `/home/punch/timeclockpi`, `/var/lib/timeclockpi`) i validats al terminal de referència.
- Prova completa partint d'una Raspberry Pi neta.
- Estudiar la viabilitat d'un codi numèric tàctil de manteniment al terminal físic que, en situacions de recuperació, permeti sortir controladament del kiosk i obrir un terminal local. Definir autenticació, auditoria, limitació d'intents i tancament/retorn segur al kiosk abans d'implementar-ho.

## 10. Multi-terminal i servidor central

- Identificador únic de terminal.
- Sincronització amb servidor central.
- Enviament segur de fitxatges.
- Funcionament offline amb cua local.
- Reconciliació posterior.
- Coordinació de diversos terminals.

## Criteri general

TimeClockPi ha de continuar sent offline-first, amb SQLite com a font local de veritat, historial de fitxatges no destructiu, administració separada del flux de treballadors i una arquitectura que permeti afegir nous mètodes d'identificació sense canviar el nucli.
