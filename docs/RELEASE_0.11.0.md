# Contextual Controls 0.11.0

## Context Dial configurabile

- Entità fisse scelte da qualsiasi dominio HA tramite selettore nativo ordinabile.
- Carosello fino a 20 elementi: fissi prima dei suggerimenti, senza duplicati.
- Nome terminale, titolo zona/area, suggerimenti opzionali e timeout dim/off nel flow.
- Payload JSON schema 2 con icone MDI, stato leggibile, valori/limiti e aggiornamenti live.
- LIGHT/SWITCH: toggle; LIGHT: luminosità; CLIMATE: preview, conferma setpoint e annullamento.
- Logging fixed/contextual distinto: i fissi non alterano lo storico del ranking.
- Compatibilità dei servizi e sensori precedenti mantenuta; revisione protegge da slot obsoleti.

Il componente HACS resta indipendente dall'hardware. Per il nuovo carosello
installare il firmware Context Dial schema 2 separatamente: il solo aggiornamento
HACS non modifica il firmware. Il firmware espone Display Brightness (number
persistente 0–100%), elimina il doppio KO per BLK e usa KO come azione/conferma.

Richiede Home Assistant Core 2026.9.3 o successivo. Riavviare HA dopo l'aggiornamento.
Configurazione: Contextual Controls → Configura → Terminali fisici → Salva.

## Validazione e limiti

131 test unitari, Ruff/mypy e build binaria ESPHome 2026.9.1 eseguiti localmente.
I test con HA reale completano le verifiche ma il processo macOS termina con
segmentation fault in chiusura, riprodotto anche sulla 0.10.6; la CI Linux
verifica il ciclo completo prima della pubblicazione.

La nuova UX richiede ancora collaudo sul Dial fisico. Fan fisso, input_number e
domini sconosciuti sono display-only; icone non presenti nel catalogo MDI 7.4.47
usano fallback. Stato localizzato italiano/inglese, font con alfabeto latino e
accenti italiani. UI offline conservata in RAM, non dopo reboot. La luminosità
va lasciata salvare per almeno 5 s prima di interrompere l'alimentazione.

Dettagli e checklist: [Context Dial configurabile](CONFIGURABLE_TERMINAL.md).
