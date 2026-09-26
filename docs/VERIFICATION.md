# Verifica Phase 1 — 25 settembre 2026

## Risultato

Integrazione **installata e configurata** nell’istanza indicata dall’utente,
Core 2026.9.3, container `homeassistant`, directory host
`/home/homeassistant/custom_components/contextual_controls`.
Creato e verificato `sensor.contextual_controls` dalla UI italiana.

Repository pubblicata su [GitHub](https://github.com/monkeypr00f/contextualcontrols).
La [CI sul commit eaa9a6f](https://github.com/monkeypr00f/contextualcontrols/actions/runs/36126561405)
è passata: core, homeassistant-runtime, hassfest e HACS.
Il primo run ha rilevato una dipendenza di sviluppo mancante per mypy;
`voluptuous` è ora dichiarata in requirements-dev.txt.

La repository è stata aggiunta a HACS come Integrazione e il download del
commit eaa9a6f è riuscito sulla vera istanza. Il riavvio richiesto da HACS è
stato completato.
Il codice dell’integrazione coincide con quello già caricato e verificato;
questo download non ha modificato configurazione o apprendimento.
Nessun avanzamento alla Phase 2.

## Test eseguiti

| Verifica | Risultato |
| --- | --- |
| `pytest -q` locale | **48 passed** |
| Stessi primi 44 test del motore nel container HA | **44 passed** |
| `pytest -q tests/runtime_check.py` nel container HA | **3 passed** |
| Ruff lint e format | Passati |
| Mypy, 5 moduli del motore | Passato |
| `compileall` codice e test | Passato |
| hassfest ufficiale del tag Core 2026.9.3, tutti i plugin applicabili | **1 integrazione; 0 invalide; nessun warning sul pacchetto** |
| Benchmark 1.000 candidati / 50.000 eventi | **0,069 secondi** sul Mac di sviluppo, singola misura indicativa |
| Creazione ConfigEntry dalla UI HA reale | Passata |
| OptionsFlow italiano e reload automatico | Passati |
| Sensore e attributi pinned su HA reale | Passati |

Il test runtime ha emesso un DeprecationWarning da `homeassistant.components.http`
relativo a una classe aiohttp del core. Non è un errore dell’integrazione.
Hassfest eseguito sul container emette un avviso di ordine di importazione
voluptuous/probatio proveniente dall’ambiente dello strumento; l’esito della
validazione dell’integrazione è privo di warning.

## Criteri di accettazione

| # | Criterio | Evidenza / limite |
| --- | --- | --- |
| 1 | Repository riconosciuta da HACS | Aggiunta e download riusciti sulla vera istanza; validazione HACS CI passata |
| 2 | HA carica senza errori | Caricamento live e test runtime |
| 3 | Aggiunta interamente da UI | Eseguita sulla vera istanza |
| 4 | Selezione entità | Selector visto nel setup e nelle opzioni; schema testato |
| 5 | Registrazione utilizzi | 4 chiamate servizio reali con handler simulato nel test HA |
| 6 | Ranking cambia con utilizzi ripetuti | Test deterministico con due candidati |
| 7 | Orario influenza il ranking | Classifica mattino/sera invertita nel test; inclusa mezzanotte |
| 8 | Opzioni modificabili senza reinstallare | Eseguito sulla vera istanza e testato il reload |
| 9 | Lista ordinata valida | Sensore live e test runtime |
| 10 | Esclusioni assolute | Test entità, dominio, area e pin escluso |
| 11 | Pinned corretti | Test slot/ordine e prova live |
| 12 | Reset learning | Azione HA testata, inclusa conferma mancante e reset selettivo |
| 13 | Restart conserva apprendimento | Store riletto in processo Python nuovo; unload/setup testati |
| 14 | Errori contenuti | Test record invalidi, versioni, contesti; nessun errore live osservato |
| 15 | Test principali passano | 48 unitari + 3 test HA |

La prova di persistenza usa un processo nuovo che rilegge il vero file Store:
non si limita a riutilizzare dati in memoria. Non sono stati inseriti eventi
fittizi nel database della casa né azionati dispositivi reali per generare dati.

## Esempio reale osservato sul sensore

Durante la verifica è stato aggiunto temporaneamente il pin “Faretti Studio”.
Lo stato del sensore era `1` e l’attributo letto dalla UI era:

```yaml
entities:
  - entity_id: switch.faretti_studio
    score: 1
    reason: Controllo fisso
    source: pinned
    rank: 1
    pinned: true
    usage_count_in_window: 0
mode: statistical
ai_used: false
learning_period_days: 21
candidate_count: 0
learning_records_count: 0
```

Il pin di prova è stato poi rimosso tramite OptionsFlow. L’istanza conserva i
domini consigliati e i default: inizierà ad apprendere dai comandi diretti
autenticati. Il valore 0 prima dei primi utilizzi è il cold start previsto.
Nessun token o password è salvato nella repository.

## Limiti intenzionali

- La Phase 1 non distingue sempre dashboard, API con token e Assist. Non
  apprende automaticamente dai semplici cambiamenti di stato.
- Gli eventi sono tentativi di comando; non certificano l’effetto sul dispositivo.
- Presenza, contesto, weekday/weekend e classificazione avanzata sono Phase 2.
- AI, fallback provider e relativi test sono coperti nella Phase 3.
- Card dinamica ed editor visuale sono Phase 4. Il sensore da solo non genera tile.
- La conservazione è limitata a 90 giorni e 50.000 eventi per istanza.
- HACS è verificato come repository personalizzata; Brands e catalogo predefinito sono submission separate.


## Phase 4

La repository Dashboard separata passa `node --check`, 4 test Node e HACS
validation. La release v1.0.0 è stata installata su Home Assistant tramite HACS.
L’integrazione 0.5.0 mantiene invariato il contratto del sensore e rimuove la
registrazione frontend incorporata.
