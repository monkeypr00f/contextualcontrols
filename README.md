# Contextual Controls

Controlli Home Assistant suggeriti in base alle abitudini reali e all’orario.
**Suggerisce controlli: non comanda mai autonomamente la casa.**

## Stato del progetto

Versione 0.6.0. Richiede **Home Assistant Core 2026.9.3 o successivo**.
Apprendimento, filtri e ranking di base sono sempre locali. L’AI è opzionale e
può soltanto riordinare una shortlist già ammessa dal motore statistico.
Presenza, giorno della settimana, area e contesto casa contribuiscono al ranking
senza eseguire comandi.

Il backend è distribuito come HACS **Integration**. La card Lovelace è il pacchetto
HACS **Dashboard** separato
[`contextual-controls-card`](https://github.com/monkeypr00f/contextual-controls-card),
così può essere aggiornata senza riavviare Home Assistant. Se usavi l’anteprima
incorporata, installa la card prima di aggiornare l’integrazione a 0.5.0.

## Installazione manuale

1. Copia la cartella `custom_components/contextual_controls` in
   `/config/custom_components/contextual_controls` del tuo Home Assistant.
   Copia l’intera cartella, incluse `translations` e `manifest.json`.
2. Riavvia Home Assistant.
3. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.
4. Cerca **Contextual Controls**, scegli il nome e le entità, quindi termina.

Non occorre modificare `configuration.yaml`. Il primo sensore, con il nome
predefinito e senza conflitti, è `sensor.contextual_controls`. Istanze aggiuntive
o nomi già occupati producono ID differenti: verifica il dispositivo creato.

## Installazione HACS

Repository: [monkeypr00f/contextualcontrols](https://github.com/monkeypr00f/contextualcontrols).
I metadati indicano questo repository e il manutentore `@monkeypr00f`.

Repository pubblicata e download HACS verificato a partire dalla versione 0.1.0.
La submission a Home Assistant Brands e l’inclusione nel catalogo HACS predefinito
sono separate dall’installazione come repository personalizzata. La CI HACS
ignora esclusivamente `brands` finché non viene completata tale submission.

Per installare una repository pubblicata:

1. Apri HACS → menu ⋮ → **Repository personalizzate**.
2. Incolla `https://github.com/monkeypr00f/contextualcontrols` e scegli categoria **Integrazione**.
3. Cerca Contextual Controls in HACS, scarica e riavvia Home Assistant.
4. Aggiungi l’integrazione dalle impostazioni come sopra.

## Configurazione semplice

Il setup iniziale contiene due schermate: nome e controlli. I domini consigliati
sono già selezionati. Per monitorare soltanto le entità scelte esplicitamente,
svuota l’elenco dei domini automatici. Le esclusioni hanno sempre precedenza.

In **Configura** trovi sezioni separate:

| Sezione | Opzioni |
| --- | --- |
| Generale | Modalità, numero suggerimenti 1–12; refresh periodico e su eventi |
| Entità | Inclusioni/esclusioni, domini, aree |
| Apprendimento | 7–90 giorni, fascia ±30–180 minuti, recenza, origine, profilo, entità ignorate |
| Contesto | Presenza, modalità presenza, entità contestuali |
| Dashboard | Controlli fissi ordinabili, prima/dopo, occupazione degli slot |
| Accesso rapido / Apple | Slot, sicurezza, stabilità, entità sensibili e apprendimento |
| Avanzate / Debug | Soglia minima, cold start, dettagli dei punteggi |
| AI opzionale | Provider, shortlist, cache, timeout, temperatura e privacy |
| Reset | Cancellazione confermata per istanza, entità o utente |

Le modifiche ricaricano l’istanza automaticamente e mantengono l’apprendimento.
La UI e i motivi supportano italiano e inglese; i motivi usano la lingua del
server HA, perché un sensore condiviso non può avere attributi diversi per browser.

## Modalità Statistical / Hybrid / AI

**Statistical only** usa esclusivamente il ranking locale. **Smart / Hybrid**
combina l’ordine statistico con quello del provider. **AI assisted** dà più peso
all’ordine del modello, mantenendo gli stessi filtri, la soglia locale e la
shortlist. Con provider disabilitato o non raggiungibile entrambe tornano
automaticamente al ranking statistico.

I provider implementati sono **Ollama** (`/api/chat`) e **OpenAI-compatible**
(`/v1/chat/completions`). Nessun SDK esterno è richiesto. URL, modello, timeout
e temperatura sono configurabili dalla UI; l’API key è conservata in
`ConfigEntry.data` e non compare in log o diagnostics.

Conversation non viene usata perché la sua API pubblica può eseguire intenti e
non garantisce un percorso provider-indipendente senza strumenti. L’API LLM di
Home Assistant espone strumenti ai modelli, ma non offre una completion generica
sicura per questo reranking. La decisione è descritta in
[ARCHITECTURE.md](ARCHITECTURE.md).

Il modello riceve al massimo 6–30 candidati statistici. La risposta ammessa è
solo una lista JSON ordinata. ID estranei, duplicati e valori non validi vengono
scartati; un output inutilizzabile attiva il fallback. L’AI non riceve strumenti,
non può aggiungere candidati e non può chiamare servizi Home Assistant.

## Come impara

Il sistema osserva gli eventi `call_service`. Di default accetta comandi con
utente autenticato e senza contesto padre. Non considera ogni `state_changed`
un utilizzo: una misura del sensore o l’aggiornamento spontaneo di un dispositivo
non sono un’azione volontaria dell’utente.

Un evento indica un **tentativo di comando**, non una garanzia di successo.
Dashboard e API esterne che usano un token utente non sono sempre distinguibili.
Assist, script e automazioni sono riconosciuti quando la catena Context di Home
Assistant fornisce un’origine osservabile. I casi ambigui restano unknown con
confidence bassa. Manual UI e Assist sono attivi di default; automazioni, azioni
interne agli script e unknown sono opt-in. Uno script lanciato direttamente
dall’utente resta un controllo manuale; le sue azioni interne sono classificate
separatamente.

I target espliciti, area, dispositivo, gruppo, piano ed etichetta usano il resolver
HA e sono intersecati con le entità consentite. Sono apprese solo azioni di
controllo riconosciute; creazione scene, reload e richieste di dati sono ignorati.

Ogni utilizzo registra timestamp, entity ID, user ID se disponibile, origine,
azione, confidence, area, presenza e una snapshot delle sole entità contestuali
scelte. Il periodo di scoring è configurabile; la retention
locale arriva a 90 giorni e massimo 50.000 eventi. I dati partono dall’installazione:
nessuna importazione dello storico Recorder e nessuna query SQL.

Il punteggio combina quantità degli utilizzi, vicinanza all’ora attuale, decadimento
temporale, giorno, presenza, area, contesto, confidence e plausibilità dello stato.
Esempio: una luce già accesa
rimane interessante se normalmente viene spenta a quest’ora. Le scene non sono
interpretate semanticamente. L’orario segue il fuso configurato in HA, anche
attraversando mezzanotte. Le formule sono in [ARCHITECTURE.md](ARCHITECTURE.md).

All’inizio sono mostrati controlli recenti e fissi. Senza utilizzi né fissi il
sensore vale 0: è normale. Dopo almeno tre eventi per entità prevale il modello
temporale. I candidati sotto soglia restano esclusi; non si riempiono gli slot
con raccomandazioni inventate. I fissi rispettano esclusioni, aree e disponibilità.

Il confronto dei giorni può usare lo stesso giorno esatto, feriale/weekend o
nessuna distinzione. La presenza può essere ignorata, usata come segnale oppure
richiesta: in quest’ultimo caso vengono nascosti anche i controlli fissi quando
nessuna entità configurata è a casa. Gli stati contestuali sono confrontati come
valori opachi, senza inferenze semantiche.

## Privacy e sicurezza

Senza provider AI tutti i dati restano nell’istanza. Store salva in
`/config/.storage/contextual_controls.<entry_id>` con gestione privata dei file.
Backup HA può includere questo file. Eliminare l’integrazione elimina il relativo
storico; un riavvio o reload invece lo conserva. Un arresto improvviso può perdere
gli ultimi eventi non ancora scritti (scritture differite di circa 15 secondi).

Il sensore non espone user ID né timestamp dei singoli utilizzi. Diagnostics
contiene solo conteggi e impostazioni non sensibili. Il debug è disabilitato
di default e limita i dettagli a 30 candidati. L’attributo `entities` contiene
entity ID, quindi va trattato come informazione della propria casa.

Per l’AI ogni categoria è autorizzabile separatamente: entity ID, friendly name,
stato, area, statistiche aggregate, orario esatto, presenza ed entità
contestuali. Gli entity ID disattivati vengono sostituiti da token come
`candidate_1`. Non vengono mai inviati storico grezzo, user ID o l’intero state
registry. Il default non invia minuti/secondi né presenza. Contesto invariato
usa la cache; il minimo intervallo configurabile evita chiamate continue.

Lock, alarm e siren richiedono inclusione esplicita. L’integrazione non esegue
mai azioni autonomamente. La card e Quick Access chiamano servizi soltanto dopo
un tocco o una richiesta esplicita dell’utente; Quick Access applica inoltre la
policy di sicurezza configurata. La selezione delle entità non crea un nuovo
sistema di permessi: valgono i permessi nativi Home Assistant.

## Card Lovelace

Installa `https://github.com/monkeypr00f/contextual-controls-card` in HACS come
repository **Dashboard**, aggiorna il browser, quindi modifica una dashboard,
scegli **Aggiungi card**, cerca **Contextual Controls**, scegli il sensore e salva.
HACS registra la risorsa e non occorre modificare YAML. La card mostra una
griglia responsive di tile con icona, nome e stato. Dal suo editor visuale puoi
configurare titolo, limite, colonne desktop/mobile, motivo, punteggio, ultimo
aggiornamento, controlli fissi e azione al tocco. Il titolo dinamico usa
Buongiorno, Per te adesso, Questa sera e Prima di dormire.

Con azione automatica, light/switch/fan/input_boolean vengono alternati; scene,
script e button usano l’azione appropriata. Climate, media player, cover, lock,
vacuum, select e number aprono more-info. La pressione prolungata apre sempre
more-info. La card non esegue mai azioni senza un’interazione dell’utente.

Se non ci sono suggerimenti può nascondersi oppure mostrare “Nessun suggerimento
per ora”. Tiles, Compact e Chips sono implementati e selezionabili dall’editor visuale.

## Contratto del sensore

Apri il sensore oppure Strumenti per sviluppatori → Stati. Lo stato è il numero
di controlli, inclusi i fissi. Attributi: `entities`, `last_update`, `mode`,
`ai_used`, `ai_cached`, `ai_provider`, `ai_status`, `last_ai_update`,
`learning_period_days`, `candidate_count` e conteggi dello storico. In caso di
problema compare anche `ai_error`, senza rendere indisponibile il sensore.

Esempio **illustrativo** (i risultati reali dipendono dai tuoi utilizzi):

```yaml
entities:
  - entity_id: scene.serata
    score: 1.0
    reason: Controllo fisso
    source: pinned
    rank: 1
    pinned: true
    usage_count_in_window: 0
  - entity_id: light.camera
    score: 0.8123
    reason: Usato spesso con la presenza attuale
    source: statistical
    rank: 2
    pinned: false
    usage_count_in_window: 8
mode: hybrid
ai_used: true
ai_cached: false
ai_provider: ollama
ai_status: used
presence_mode: signal
presence_home: true
```

La card usa questo attributo come contratto pubblico e non analizza tutte le
entità dell’istanza.

## Apple Quick Access

Contextual Controls espone da 1 a 10 slot stabili, sei per impostazione
predefinita: `sensor.contextual_control_1`,
`sensor.contextual_control_2`, ecc. L'entity ID dello slot resta invariato;
nome, icona, stato e target seguono l'ultimo ranking già calcolato. Leggere o
eseguire uno slot non avvia AI, scoring o query storiche.

Le due azioni pubbliche sono:

```yaml
action: contextual_controls.get_slot
data:
  slot: 1
response_variable: current_slot
```

```yaml
action: contextual_controls.execute_slot
data:
  slot: 1
  expected_entity_id: light.camera
  source: shortcut
response_variable: result
```

`expected_entity_id` è facoltativo ma consigliato: se il target è cambiato,
l'azione restituisce `stale_slot` senza comandare il nuovo dispositivo. Gli slot
mantengono inoltre il target per due minuti per impostazione predefinita. Safe
protegge entità sensibili e domini di sicurezza; Balanced consente i controlli
comuni ma continua a bloccare i domini di sicurezza; Direct richiede comunque
`confirmed: true` per un'entità sensibile e non inventa azioni ambigue.

### Apple Watch

Percorso con meno configurazione: crea sei Shortcuts chiamati **Context 1** …
**Context 6**. In ciascuno aggiungi Home Assistant → **Perform action**, scegli
`contextual_controls.execute_slot` e usa JSON `{"slot":1,"source":"apple_watch"}`
cambiando il numero. Abilita **Show on Apple Watch** nelle proprietà dello
Shortcut. Lo stesso Shortcut può essere lanciato da Siri o dalla complication
Shortcuts.

La Home dell'app Home Assistant per Apple Watch mostra ufficialmente Scripts,
Scenes e iOS Actions. In alternativa copia
[`docs/apple-quick-access-scripts.yaml`](docs/apple-quick-access-scripts.yaml),
riavvia, poi nell'iPhone apri Companion App → Apple Watch → Configuration e
aggiungi gli script Context 1…6. Una custom integration HACS non può crearli o
inserirli nella schermata Watch tramite API pubblica.

Gli script Watch conservano label e icona statiche. Per mostrare il target
dinamico usa una complication templata con
`states('sensor.contextual_control_1')`; gli aggiornamenti delle complication
sono soggetti al budget watchOS e non costituiscono una griglia interattiva.

### iPhone Lock Screen

La soluzione diretta è aggiungere uno Shortcut Context N alla Lock Screen,
all'Action Button o al Control Center. Per un accesso visivo usa il widget
accessory circolare **Scripts** con uno degli script wrapper, oppure **Open Page**
verso la dashboard rapida. Il Custom Widget Beta della Companion App supporta
attualmente i formati System, non quelli accessory della Lock Screen.

La configurazione di esempio per una dashboard mobile è in
[`docs/contextual-controls-quick-dashboard.yaml`](docs/contextual-controls-quick-dashboard.yaml).
Dopo averla aggiunta, usa l'App Intent Home Assistant **Open Page** o il widget
Open Page. Live Activities non sono usate: mostrano stato e aprono un URL, ma la
documentazione corrente non espone pulsanti dinamici adatti a questi slot.

### Shortcuts, Action Button e Control Center

Lo Shortcut usa sempre lo stesso numero; non contiene l'entity ID dinamico.
Home Assistant **Perform action** restituisce il JSON dell'azione quando la
risposta è abilitata. Aggiungi l'azione Shortcuts **Vibra dispositivo** soltanto
nel ramo in cui `success` è vero. Per target sensibili crea una variante che:

1. chiama `get_slot` e mostra nome/azione;
2. chiede conferma;
3. chiama `execute_slot` con `expected_entity_id` dalla prima risposta e
   `confirmed: true`.

La provenienza (`apple_watch`, `ios_lock_screen`, `shortcut`, `action_button` o
`control_center`) serve solo a storico e diagnostica, mai ad allentare la policy.

## Reset e ignora utilizzo

La via più semplice è **Configura → Reset apprendimento**. Scegli eventualmente
entità e utente e attiva la conferma. Senza filtri il reset riguarda l’intera
istanza. I due filtri insieme selezionano la loro intersezione.

La stessa operazione è disponibile in **Strumenti per sviluppatori → Azioni →
Contextual Controls: Reset apprendimento**, con selector dell’istanza e
`confirm: true` obbligatorio. La UI servizi HA non offre un modal generico:
la conferma è quindi verificata lato server.

Per ignorare un’entità senza cancellare tutto: **Apprendimento → Non imparare
da queste entità**. Smette di raccogliere nuovi eventi e di usare le vecchie
evidenze per quell’entità. Rimuovendola dalla lista puoi riusare lo storico
ancora in retention. I fissi possono rimanere visibili; per nascondere sempre
un controllo usa invece Entità escluse.

## Troubleshooting e FAQ

- **Non trovo l’integrazione:** verifica cartella, manifest e riavvio; aggiorna
  la pagina del browser e consulta i log filtrando `contextual_controls`.
- **Nessun suggerimento:** usa un controllo dalla UI, attendi alcuni secondi,
  verifica inclusioni, aree, soglia e profilo. I cambiamenti di stato spontanei
  non costituiscono apprendimento. Aggiungi controlli fissi se desideri contenuto subito.
- **Uno script non appare:** includi il dominio script o l’entità specifica;
  deve essere lanciato direttamente con context utente per il default prudente.
- **Entità fissa assente:** può essere esclusa, fuori area, disabilitata o unavailable.
- **L’orario non aggiorna il ranking:** controlla fuso e refresh. Solo eventi non
  aggiorna se il tempo trascorre senza eventi; default 15 minuti + eventi.
- **Storico dopo restart:** Store viene riletto. Non rimuovere e ricreare l’istanza
  per aggiornare, perché la rimozione elimina i suoi dati.
- **Posso usare più istanze?** Sì, hanno Store e sensori indipendenti.
- **Funziona senza internet?** Sì. Disabilita l’AI oppure usa Ollama in rete locale.
- **AI non raggiungibile:** il sensore continua con il ranking statistico e
  mostra un codice breve in `ai_error`, ad esempio `timeout`.
- **Il provider restituisce entità inventate:** vengono ignorate e non possono
  superare la shortlist locale.
- **Perché non compare Conversation agent?** L’API pubblica può eseguire intenti;
  non offre ancora una garanzia generica “nessuno strumento” adatta a questo uso.

## Sviluppo e verifiche

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

`tests/runtime_check.py` verifica il ciclo HA reale con le librerie 2026.9.3 in
una configurazione temporanea e servizi simulati, senza connettersi al processo
della casa. Può essere eseguito dentro il container HA esistente:

```sh
python -m unittest tests.runtime_check -v
```

CI include syntax, lint, tipi del motore, pytest, test runtime HA, hassfest e HACS.
Ultima verifica locale: 77 test passati. La CI esegue inoltre 4 test completi
con Home Assistant 2026.9.3, hassfest e HACS. I test coprono anche privacy,
parsing, provider, cache, ranking e fallback AI. Risultati
e limiti della verifica effettiva sono in [docs/VERIFICATION.md](docs/VERIFICATION.md).

Licenza MIT. Le decisioni e le fonti ufficiali sono in
[ARCHITECTURE.md](ARCHITECTURE.md).
