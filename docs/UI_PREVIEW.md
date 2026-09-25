# Anteprima UI 0.3.0

Questa versione anticipa una parte circoscritta della Phase 4 per rendere
valutabile il ranking statistico già disponibile.

## Cosa mostra

- griglia responsive, 3 colonne desktop e 2 mobile per default;
- icona, friendly name e stato corrente;
- motivo, punteggio e ultimo aggiornamento opzionali;
- filtro dei controlli pinned e limite 1–12;
- titolo fisso o dinamico per fascia oraria;
- stato vuoto configurabile.

## Interazioni

Il tap automatico alterna light, switch, fan e input_boolean; attiva scene,
script e button con il servizio corretto; apre more-info per gli altri domini.
Lock e controlli complessi non ricevono un toggle automatico. Hold e menu
contestuale aprono sempre more-info.

Il backend non esegue servizi. La card può chiamarne uno soltanto in risposta a
un tap esplicito. Nella verifica dell’installazione non vengono toccati i tile.

## Configurazione

La card si registra nel picker e usa il form editor ufficiale introdotto dal
frontend Home Assistant. Il default punta a `sensor.contextual_controls`.
L’integrazione serve e registra automaticamente il modulo, quindi non servono
risorse Lovelace o YAML aggiuntivi.

## Scelta di distribuzione

La card è inclusa temporaneamente nella repository Integration per provarla
sull’istanza reale con un singolo aggiornamento. La Phase 4 completa verrà
distribuita come repository HACS Dashboard separata. La configurazione
`type: custom:contextual-controls-card` e il contratto del sensore non cambiano,
quindi l’estrazione non richiederà di ricreare la card.

## Non incluso

- layout Compact e Chips;
- personalizzazioni per singola entità;
- test visuali su più browser e temi;
- pacchetto HACS Dashboard indipendente;
- AI, che appartiene alla Phase 3.
