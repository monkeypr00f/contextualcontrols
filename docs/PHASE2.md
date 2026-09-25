# Verifica Phase 2

## Funzioni aggiunte

- presenza opzionale tramite `person`, `device_tracker` e `binary_sensor`;
- modalità presenza ignorata, segnale o requisito per mostrare suggerimenti;
- confronto stesso giorno oppure feriale/weekend;
- snapshot locali delle sole entità contestuali configurate;
- affinità dell’area quando una presenza configurata ha un’area nota;
- origini manual, Assist, automation, script e unknown con confidence distinta;
- motivazioni localizzate per giorno, presenza, contesto e area;
- diagnostics aggregati senza user ID, entity ID o storico preciso;
- migrazione ConfigEntry v1→v2 e Store v1/v2→v3.

## Comportamento prudente

Un contesto autenticato senza padre è manuale. Assist viene riconosciuto dalla
chiamata `conversation.process`; automazioni e script dagli eventi Context del
Core. Se la catena non è osservabile, l’origine resta unknown. Un semplice
`state_changed` non diventa mai un utilizzo.

Le entità contestuali non sono candidate, non vengono inviate all’esterno e non
attivano servizi. Lo Store conserva soltanto il loro stato al momento di un
utilizzo ammesso. `unknown` e `unavailable` non entrano nella snapshot.

## Copertura

I test puri verificano presenza, contesto, giorno, area, ranking, origini,
retention e migrazioni. Il test con il runtime Home Assistant verifica selector,
reload delle opzioni, require-home, persistenza, migrazione della ConfigEntry,
attribuzione Assist/manuale, diagnostics e assenza di chiamate autonome.

## Limiti

- Home Assistant non espone una singola API pubblica che identifichi sempre UI,
  Assist, script e automazioni. Le origini non dimostrabili restano unknown.
- Un comando UI e un client REST/WebSocket con lo stesso utente possono avere
  Context indistinguibili.
- Il confronto contestuale usa uguaglianza di stato; non interpreta semanticamente
  temperature, meteo, scene o modalità personalizzate.
- AI appartiene alla Phase 3; card ed editor Lovelace alla Phase 4.
