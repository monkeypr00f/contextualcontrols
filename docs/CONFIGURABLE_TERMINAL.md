# Context Dial configurabile — schema 2

Implementazione per Contextual Controls 0.11.0.
Il componente resta indipendente dall'hardware. Il firmware è nel repository
separato `context-dial`; aggiornare entrambi. Il nuovo firmware non funziona con
il solo componente 0.10.6, che non pubblica il payload schema 2.

## Configurare un terminale

1. Installare questa versione del componente e riavviare Home Assistant.
2. Aprire Impostazioni → Dispositivi e servizi → Contextual Controls →
   Configura → Terminali fisici.
3. Inserire un ID uguale alla substitution `terminal_id` del firmware.
4. Scegliere area/e, nome del terminale e, facoltativamente, nome della zona.
   Il titolo usa il nome dell'area; con più aree le unisce. Il nome zona
   permette ad esempio di mostrare “Salotto” mantenendo tre aree associate.
5. Nel selettore nativo Entità fisse scegliere qualsiasi entità HA. Riordinare
   la selezione con il controllo di reorder del frontend, se disponibile.
   L'ordine salvato, non quello alfabetico, è l'ordine iniziale del carosello.
6. Impostare suggerimenti contestuali abilitati, massimo suggerimenti 0–12,
   dim 5–3600 s e off fino a 7200 s (strettamente maggiore di dim).
7. Tornare al menu e scegliere Salva. Per modificare un terminale esistente
   aprire Terminali, scegliere Modifica terminale lasciando vuoto l'ID,
   confermare, modificare il profilo caricato e infine Salva.
8. Aggiungere il dispositivo ESPHome a HA; abilitare “Allow the device to
   perform Home Assistant actions” nelle sue opzioni.

La lista ha massimo 20 elementi complessivi: fissi prima, poi suggerimenti
ordinati dal motore esistente. I duplicati delle entità fisse sono rimossi dai
suggerimenti. I fissi possono appartenere ad aree non associate e a domini
non inclusi nel ranking; le esclusioni/sicurezze globali restano applicate
all'esecuzione. Entità rimosse o non disponibili restano visibili senza azioni.

Il profilo è salvato in `options.terminal_settings[terminal_id]`; le associazioni
esistenti `terminal_mappings` restano compatibili. Esempio concettuale (non una
nuova configurazione YAML di HA):

```json
{
  "terminal_name": "Dial divano",
  "zone_name": "Salotto",
  "fixed_entities": ["light.salotto", "climate.salotto", "switch.lampada_tavolo"],
  "contextual_enabled": true,
  "contextual_max_items": 5,
  "dim_timeout": 30,
  "off_timeout": 120
}
```

## Contratto dati

`sensor.contextual_controls_<terminal_id>_data` ha stato `revision` e attributo
`payload` contenente una stringa JSON. Un unico aggiornamento evita di leggere
titolo, slot e revisione appartenenti a pubblicazioni diverse.

```json
{
  "schema": 2, "terminal_id": "cc_salotto", "terminal_name": "Dial divano",
  "title": "Salotto", "revision": "1791224000000001", "area_ids": ["salotto"],
  "mode": "menu", "active_slot": null, "pending_value": null,
  "feedback": "ready", "dim_timeout": 30, "off_timeout": 120,
  "items": [{
    "slot": 1, "id": "light.salotto", "entity_id": "light.salotto",
    "source": "fixed", "domain": "light", "name": "Lampadario salotto",
    "icon": "mdi:ceiling-light", "icon_glyph": "\udb81\udf69",
    "kind": "LIGHT", "state": "on", "state_text": "Accesa · 68%",
    "value": 68, "min": 0, "max": 100, "step": 5, "unit": "%",
    "supported": true, "available": true
  }]
}
```

`icon_glyph` è il carattere Unicode reale del font MDI 7.4.47: il client non
deve interpretare il nome `mdi:*`. Priorità: icona personalizzata nel registro
entità, attributo icon, fallback device class/dominio, `mdi:help-circle`.
Le icone non MDI o assenti dal catalogo hanno fallback generico. Per i domini
non supportati `kind=UNSUPPORTED`, `supported=false`; KO non chiama servizi.

I sensori legacy title/status/mode/feedback/revision/action_1…action_20 rimangono
disponibili. Stati live aggiornano il contenuto senza cambiare la revisione
finché gli ID degli slot non cambiano. La revisione cambia quando gli slot
cambiano e dopo il riavvio dell'integrazione: comandi con revisione vecchia
sono rifiutati. Durante una regolazione gli slot sono congelati.

Il servizio resta `contextual_controls.terminal_input` con terminal, input
(`select`, `activate`, `adjust`, `back`), slot 1–20, delta -20…20 e revision.
Non accetta entity_id eseguibili inviati dal dispositivo. `refresh_terminal`
rimane disponibile. Il firmware non esegue ranking o predizione.

## Interazione e domini

| Input | Lista | Regolazione |
| --- | --- | --- |
| Rotazione encoder | Navigazione circolare | Varia il valore |
| KO breve | Light/switch: toggle; clima: entra; azione: esegue | Conferma/esce |
| KO 0,5–3 s | Su luce dimmerabile entra nella luminosità **della luce HA** | Nessuna azione |
| Pulsante encoder breve | Ritorna alla lista | Esce; annulla solo il setpoint clima non confermato |

Light e switch mostrano ON/OFF localizzati. Light usa brightness 0–100% e
applica la rotazione in tempo reale (passi circa 5%). Climate mostra temperatura
attuale, setpoint e hvac_action; preview senza servizio, KO applica
`climate.set_temperature` rispettando min_temp/max_temp/target_temp_step.
Il pulsante encoder annulla la preview clima; non annulla valori luce già inviati.

Restano riutilizzati gli adapter esistenti per number, cover con posizione,
media_player con volume, scene, script, button, input_button e input_boolean;
le capacità effettive dipendono dagli attributi e dai servizi HA disponibili.
Per fan fisso, input_number e altri domini il MVP è display-only. Nessun
servizio generico viene indovinato. Il lessico di stato è italiano/inglese
secondo la lingua server HA; non usa le traduzioni JavaScript del frontend.

## Logging e predizione

Evento `contextual_controls_terminal_input`: timestamp UTC, terminal_id,
area_id/area_ids, source fixed/contextual, action_id, position/slot, revision,
available_action_ids, input, action, success, previous_value/new_value, unit,
previous_state/new_state, initial_value. Valori luce/media normalizzati in %.
La preview clima è esplicitamente `input=preview`, non un comando applicato.
I valori osservati dopo un servizio possono precedere lo stato finale di un
device HA asincrono: non vengono presentati come conferma fisica del device.

Interazioni fisse sono emesse sul bus per futuri segnali contestuali, ma non
aggiunte allo storico/ranking. L'osservatore generale dei servizi ignora i
contesti dei comandi del terminale, evitando doppio conteggio. Le azioni
contestuali conservano il tracking esistente. Gli eventi sul bus non sono un
archivio persistente autonomo: per conservare i fissi usare un listener HA.

## Luminosità e standby

Il firmware espone l'entità del device ESPHome **Display Brightness**, number
0–100%, categoria configurazione. Il suo entity_id viene assegnato da HA
(tipicamente `number.context_dial_cucina_display_brightness`) e può essere
rinominato. Non è una light HA controllata dal carosello.

Il valore viene ripristinato da flash; il salvataggio è differito di massimo
circa 5 s: attendere prima di togliere alimentazione. Active usa questo valore;
dim usa min(valore attivo, 12%); off è 0%. Impostare 0 mantiene il display
spento: riportare il numero sopra zero da HA. Primo input a schermo spento
consuma soltanto il wake, inclusa la pressione/rilascio dei pulsanti.

## File e verifiche

Integrazione: terminal.py, terminal_models.py, terminal_icons.py,
mdi_metadata.json, coordinator.py, config_flow.py, const.py, __init__.py,
services.yaml, strings.json/translations, manifest.json/pyproject.toml,
test_terminal.py/test_terminal_models.py/runtime_check.py e documentazione.
Firmware: esphome/context_dial.yaml, include/dial_model.h/dial_power.h,
assets/mdi_font.yaml/materialdesignicons-webfont.ttf, test host e documentazione.
Licenze MDI incluse in third_party.

ESPHome 2026.9.1: config e build binaria ESP-IDF 5.5.5/LVGL riuscite.
Immagine ~1,7 MB; flash ~21%, RAM statica ~33% (non il picco runtime/PSRAM).
131 test Python, Ruff e mypy riusciti. Test host C++: parsing, invalid payload,
focus conservato, valori clima, active/dim/off e gate wake.
Tre test aggiuntivi sulla configurazione firmware verificano i gate reali YAML,
il latch pressione/rilascio e restore della number BLK.
Home Assistant 2026.9.3: 6 smoke test completano con OK, incluso il nuovo flow
e i servizi simulati. Su macOS il processo Python 3.14.7/3.14.8 va però in
segmentation fault durante la finalizzazione dopo i test: non è una run pulita,
da ricontrollare sulla CI Linux prima di una release. Riprodotto anche eseguendo
la versione origin/main 0.10.6 senza queste modifiche, nello stesso ambiente.

Da collaudare sul dispositivo reale: orientamento/colori, verso/debounce EC11,
KO breve/lungo, setpoint, lampeggio/marquee, cambio stato esterno, timeout,
restore dopo alimentazione rimossa >5 s, wake su ciascun input e riconnessione.
Offline mantiene l'ultima UI in RAM, non dopo riavvio; niente comandi offline.
I font testuali includono alfabeto latino di base e accenti italiani: nomi con
altri alfabeti richiedono estendere i glyphs/aggiungere un font compatibile.
La conferma backend non garantisce che il dispositivo HA abbia fisicamente
completato un movimento. Submenu specialistici/fan/input_number restano estensioni.
