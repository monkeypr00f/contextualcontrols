# Phase 3 — AI opzionale

Versione candidata: 0.4.0. Questa fase è sviluppata e verificata nel repository,
ma non viene installata nell’istanza Home Assistant reale fino al completamento
e a una successiva indicazione del proprietario.

## Funzioni

- modalità Statistical only, Smart / Hybrid e AI assisted;
- provider Disabled, Ollama e OpenAI-compatible;
- shortlist statistica configurabile da 6 a 30 candidati;
- prompt senza strumenti e risposta limitata a una lista JSON ordinata;
- privacy per singola categoria, con token opachi quando gli entity ID sono negati;
- cache per contesto identico e intervallo minimo AI da 5 a 120 minuti;
- timeout, temperatura, endpoint e modello configurabili dalla UI;
- API key OpenAI-compatible in `ConfigEntry.data`;
- fallback statistico per timeout, rete, HTTP e risposta invalida;
- attributi sensore e diagnostics privi di credenziali.

## Confine di sicurezza

Il provider riceve soltanto la shortlist prodotta dal motore locale. Non riceve
un client Home Assistant, strumenti LLM o la possibilità di chiamare servizi.
La risposta viene intersecata con gli ID della shortlist prima del ranking.
Esclusioni, presenza richiesta, soglia minima, disponibilità e controlli fissi
restano gestiti localmente.

Home Assistant Conversation non è un provider Phase 3: la sua API pubblica può
eseguire intenti. L’API LLM pubblica configura strumenti da offrire ai modelli,
ma non è una API generica per richiedere una completion senza strumenti a un
agent arbitrario. Presentarla nella UI sarebbe una garanzia di sicurezza non
supportata dalle API correnti.

## Privacy predefinita

Abilitati: entity ID, friendly name, stato corrente, area, statistiche aggregate
ed entità contestuali selezionate. Disabilitati: orario esatto e presenza.
Non vengono mai inviati user ID, record storici individuali o tutti gli stati HA.

Se gli entity ID sono disabilitati, il modello vede `candidate_1`,
`candidate_2`, ecc. La mappatura resta soltanto in memoria nell’integrazione.

## Fallback e cache

Un errore non rende indisponibile `sensor.contextual_controls`. Il sensore usa
l’ordine statistico e pubblica un codice sanificato come `timeout`,
`connection_error`, `http_503` o `invalid_response`. Nessun URL, payload o
segreto viene copiato nell’errore.

Una richiesta identica riusa l’ultimo ordine AI. Se il contesto cambia prima
dell’intervallo minimo, viene usato temporaneamente il ranking statistico con
`ai_error: minimum_refresh_interval`, evitando di applicare una cache obsoleta.

## Verifica

I test coprono prompt e privacy, token opachi, parsing JSON, duplicati, entità
estranee, ordine Hybrid/AI assisted, cache, rate limit, timeout/fallback e i
contratti HTTP Ollama/OpenAI-compatible. Il runtime Home Assistant verifica
ConfigFlow, migrazione della ConfigEntry, sensore, reload e diagnostics.
