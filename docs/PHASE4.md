# Phase 4 — Lovelace card

Versione integrazione: 0.5.0. Versione card: 1.0.0.

La UI è distribuita nella repository HACS Dashboard separata [`monkeypr00f/contextual-controls-card`](https://github.com/monkeypr00f/contextual-controls-card). HACS richiede che una repository Dashboard contenga un file JavaScript con lo stesso nome della repository nella root o in `dist`; la release contiene `dist/contextual-controls-card.js`.

La separazione consente di aggiornare la card senza riavviare Home Assistant. La configurazione salvata mantiene `type: custom:contextual-controls-card`, quindi la migrazione dalla card incorporata non richiede di ricreare la dashboard. La card deve essere installata prima di aggiornare l’integrazione a 0.5.0.

Sono implementati Tiles, Compact e Chips, griglia responsive, editor visuale, titolo dinamico, filtro dei pinned, limite opzionale, stato, motivo, punteggio, ultimo aggiornamento e scelta delle icone. Il tocco automatico esegue solo azioni esplicite dell’utente; i domini con semantica complessa o sensibile aprono more-info. La pressione prolungata apre sempre more-info.

La card legge esclusivamente il sensore configurato e gli stati delle entità restituite nel suo attributo `entities`; non scansiona il registro completo e non comunica con provider AI.
