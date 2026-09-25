# Consegna Phase 1

Installata nell’istanza locale Home Assistant Core 2026.9.3 e configurata dalla
UI. `sensor.contextual_controls` è operativo e parte da 0, in attesa degli
utilizzi autentici. Nessun dispositivo è stato azionato durante la verifica.

La chiusura del criterio HACS è **pendente**: manca il proprietario/URL GitHub
per sostituire `REPLACE_ME`, compilare codeowners e provare il download reale.
Non sono state implementate le fasi 2–4.

## Materiale

- [Codice completo dell’integrazione](../custom_components/contextual_controls/)
- [Albero completo dei file](FILES.md)
- [Decisioni architetturali e fonti ufficiali](../ARCHITECTURE.md)
- [Test eseguiti, criteri e limiti](VERIFICATION.md)
- [Installazione manuale, HACS e configurazione](../README.md)
- [Test del motore](../tests/test_scoring.py)
- [Test del ciclo Home Assistant](../tests/runtime_check.py)

## Decisioni principali

1. Core puro separato dagli adattatori Home Assistant, testabile senza installare HA.
2. Eventi `call_service` e Context, con attribuzione prudente; nessun apprendimento
   automatico dai semplici cambiamenti di stato.
3. Store locale per istanza, migrazione, retention 90 giorni e cap 50.000 eventi.
4. Scoring deterministico con orario circolare, recenza, frequenza, confidence
   e plausibilità dello stato; esclusioni assolute e pinned separati.
5. ConfigFlow semplice e OptionsFlowWithReload a sezioni, tradotti EN/IT.
6. Nessuna chiamata AI e nessun comando ai dispositivi. Conversation non è
   considerata un’API sicura per il solo reranking.
7. Futura card distribuita come plugin HACS Dashboard separato.

## Esempio realmente osservato

Durante il test dei controlli fissi sulla tua istanza:

```yaml
entities:
  - entity_id: switch.faretti_studio
    score: 1
    reason: Controllo fisso
    source: pinned
    rank: 1
    pinned: true
    usage_count_in_window: 0
```

Il pin è stato rimosso alla fine della prova. Il test non ha acceso o spento
Faretti Studio. I test dell’apprendimento hanno usato handler simulati con le
vere API HA in una configurazione temporanea, separata dal processo della casa.

## Stato delle verifiche

48 test locali + 3 test HA passati. Ruff, mypy, compilazione e hassfest passati.
La persistenza è verificata rileggendo il file Store da un processo nuovo.
Setup, traduzioni, opzioni, reload e risultato del sensore sono verificati
anche dal browser sull’istanza reale. CI GitHub e download HACS non ancora eseguiti.

I checkpoint Git separano architettura, motore statistico, adattatori HA e
verifica/documentazione. La history si consulta con `git log --oneline`.
