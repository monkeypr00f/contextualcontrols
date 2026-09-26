# Consegna Phase 1–4

La versione 0.3.0 è installata nell’istanza Home Assistant Core 2026.9.3 e
configurabile interamente dalla UI. `sensor.contextual_controls` è operativo,
ha conservato i dati della Phase 1 dopo aggiornamento e riavvio e restituisce
sei suggerimenti appresi da utilizzi autentici. La card di anteprima li rende
utilizzabili direttamente nella vista **Interno**. Nessun dispositivo è stato
azionato durante le verifiche.

Il proprietario e la repository sono ora definiti:
[`monkeypr00f/contextualcontrols`](https://github.com/monkeypr00f/contextualcontrols).
Codice pubblicato, CI passata e repository riconosciuta da HACS. HACS ha
installato la release v0.3.0 e il riavvio è riuscito. La Phase 3 è stata pubblicata come v0.4.0 e installata nell’istanza reale il 26 settembre 2026. Della Phase 4 è disponibile una prima card Tiles completa
di editor visuale; layout Compact/Chips e pacchetto HACS Dashboard separato
restano per la fase completa.

## Materiale

- [Codice completo dell’integrazione](../custom_components/contextual_controls/)
- [Albero completo dei file](FILES.md)
- [Decisioni architetturali e fonti ufficiali](../ARCHITECTURE.md)
- [Verifica storica della Phase 1](VERIFICATION.md)
- [Funzioni, verifica e limiti della Phase 2](PHASE2.md)
- [Funzioni e verifica dell’anteprima UI](UI_PREVIEW.md)
- [Installazione manuale, HACS e configurazione](../README.md)
- [Test del motore](../tests/test_scoring.py)
- [Test del ciclo Home Assistant](../tests/runtime_check.py)

## Decisioni principali

1. Core puro separato dagli adattatori Home Assistant, testabile senza installare HA.
2. Eventi `call_service` e Context, con attribuzione prudente; nessun apprendimento
   automatico dai semplici cambiamenti di stato.
3. Store locale per istanza, migrazione, retention 90 giorni e cap 50.000 eventi.
4. Scoring deterministico con orario circolare, recenza, frequenza, confidence,
   giorno, presenza, area, contesto e plausibilità dello stato; esclusioni
   assolute e pinned separati.
5. ConfigFlow semplice e OptionsFlowWithReload a sezioni, tradotti EN/IT.
6. Nessuna chiamata AI e nessun comando ai dispositivi. Conversation non è
   considerata un’API sicura per il solo reranking.
7. Card di anteprima inclusa nella Integration per la prova reale; la release
   completa verrà distribuita come plugin HACS Dashboard separato.

## Esempio realmente osservato dopo l’aggiornamento

```yaml
entities:
  - entity_id: switch.cancello_totale
    score: 0.3956
    reason: Controllo usato di recente
    source: statistical
    rank: 1
    pinned: false
    usage_count_in_window: 0
  - entity_id: script.ptz_rimessa_right
    score: 0.379
    reason: Controllo usato di recente
    source: statistical
    rank: 2
    pinned: false
    usage_count_in_window: 0
  - entity_id: script.ptz_rimessa_stop
    score: 0.379
    reason: Controllo usato di recente
    source: statistical
    rank: 3
    pinned: false
    usage_count_in_window: 0
presence_mode: signal
presence_home: null
context_entities_count: 0
learning_records_count: 3
```

La lista e i tre record erano ancora presenti dopo il passaggio 0.1.0→0.2.0.
I test automatici dell’apprendimento usano handler simulati con le vere API HA
in una configurazione temporanea, separata dal processo della casa.

## Stato delle verifiche

56 test locali + 3 test HA passati. Ruff, mypy, compilazione, hassfest e
validazione HACS passati.
La persistenza è verificata rileggendo il file Store da un processo nuovo.
Setup, traduzioni, opzioni, reload e risultato del sensore sono verificati
anche dal browser sull’istanza reale. La sezione Contesto, i filtri origine e
giorno, la migrazione delle opzioni e gli attributi del sensore sono visibili.
I log HA filtrati non riportano problemi per `contextual_controls`.

Phase 2: [pull request #1](https://github.com/monkeypr00f/contextualcontrols/pull/1),
[release v0.2.0](https://github.com/monkeypr00f/contextualcontrols/releases/tag/v0.2.0)
e [CI del merge](https://github.com/monkeypr00f/contextualcontrols/actions/runs/36158028359).

Anteprima UI: [pull request #2](https://github.com/monkeypr00f/contextualcontrols/pull/2)
e [release v0.3.0](https://github.com/monkeypr00f/contextualcontrols/releases/tag/v0.3.0).
La card è comparsa nel picker, l’editor visuale italiano ha salvato la
configurazione e la dashboard ha mostrato i sei suggerimenti, inclusi stato e
motivazione, senza interventi YAML.

Phase 3 AI: [pull request #3](https://github.com/monkeypr00f/contextualcontrols/pull/3)
e [release v0.4.0](https://github.com/monkeypr00f/contextualcontrols/releases/tag/v0.4.0).
Il codice e il runtime temporaneo sono verificati; nessun file 0.4.0 è stato
copiato nell’istanza domestica e HACS non è stato aggiornato.

I checkpoint Git separano architettura, motore statistico, adattatori HA e
verifica/documentazione. La history si consulta con `git log --oneline`.


## Phase 4

La card completa è pubblicata come repository HACS Dashboard separata:
https://github.com/monkeypr00f/contextual-controls-card, release v1.0.0. La CI
verifica sintassi, comportamento essenziale e struttura HACS. L’integrazione
0.5.0 rimuove l’anteprima incorporata; la configurazione Lovelace esistente
continua a usare lo stesso tipo di card.
