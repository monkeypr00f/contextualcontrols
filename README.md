# Contextual Controls

Controlli Home Assistant suggeriti in base alle abitudini reali e all’orario.
**Suggerisce controlli: non comanda mai autonomamente la casa.**

## Stato del progetto

Phase 1, versione 0.1.0. Richiede **Home Assistant Core 2026.9.3 o successivo**.
Apprendimento e ranking sono completamente locali. Nessun account AI, nessuna
API key, nessun servizio esterno. Il codice delle fasi successive non è incluso.

La distribuzione HACS è di tipo **Integration**. La futura card avrà una
repository HACS Dashboard separata. In questa versione il risultato è un sensore;
non viene aggiunta automaticamente una sezione dinamica alla dashboard.

> Screenshot placeholder: qui verrà mostrata la card nella Phase 4. Le schermate
> di configurazione e la verifica della Phase 1 sono descritte in `docs/VERIFICATION.md`.

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

La repository deve essere pubblicata su GitHub prima che HACS possa scaricarla.
Finché il proprietario non è definito, gli URL `REPLACE_ME` nel manifest sono
segnaposto e la validazione di pubblicazione non può essere dichiarata conclusa.

Per il manutentore: imposta `documentation`, `issue_tracker` e `codeowners` nel
manifest con il vero account/repository, aggiungi descrizione e topic GitHub,
pubblica i file e preferibilmente una release `v0.1.0`. Esegui la CI.
La submission a Home Assistant Brands e l’inclusione nel catalogo HACS predefinito
sono separate dall’installazione come repository personalizzata. La CI HACS
ignora esclusivamente `brands` finché non viene completata tale submission.

Per installare una repository pubblicata:

1. Apri HACS → menu ⋮ → **Repository personalizzate**.
2. Incolla l’URL GitHub effettivo e scegli categoria **Integrazione**.
3. Cerca Contextual Controls in HACS, scarica e riavvia Home Assistant.
4. Aggiungi l’integrazione dalle impostazioni come sopra.

## Configurazione semplice

Il setup iniziale contiene due schermate: nome e controlli. I domini consigliati
sono già selezionati. Per monitorare soltanto le entità scelte esplicitamente,
svuota l’elenco dei domini automatici. Le esclusioni hanno sempre precedenza.

In **Configura** trovi sezioni separate:

| Sezione | Opzioni |
| --- | --- |
| Generale | Numero suggerimenti 1–12; refresh periodico e su eventi |
| Entità | Inclusioni/esclusioni, domini, aree |
| Apprendimento | 7–90 giorni, fascia ±30–180 minuti, recenza, origine, profilo, entità ignorate |
| Dashboard | Controlli fissi ordinabili, prima/dopo, occupazione degli slot |
| Avanzate / Debug | Soglia minima, cold start, dettagli dei punteggi |
| Reset | Cancellazione confermata per istanza, entità o utente |

Le modifiche ricaricano l’istanza automaticamente e mantengono l’apprendimento.
La UI e i motivi supportano italiano e inglese; i motivi usano la lingua del
server HA, perché un sensore condiviso non può avere attributi diversi per browser.

## Modalità Statistical / Hybrid / AI

**Statistical** è l’unica modalità implementata nella Phase 1. Non vengono
mostrati provider o opzioni AI non funzionanti. Hybrid e AI-assisted arriveranno
con la Phase 3, dopo la validazione delle fasi precedenti.

Conversation può eseguire intenti: non viene chiamata per classificare controlli.
La futura AI riceverà solo candidati locali autorizzati e potrà riordinarli,
con fallback statistico. Non avrà strumenti per eseguire servizi.

## Come impara

Il sistema osserva gli eventi `call_service`. Di default accetta comandi con
utente autenticato e senza contesto padre. Non considera ogni `state_changed`
un utilizzo: una misura del sensore o l’aggiornamento spontaneo di un dispositivo
non sono un’azione volontaria dell’utente.

Un evento indica un **tentativo di comando**, non una garanzia di successo.
Dashboard e API esterne che usano un token utente non sono sempre distinguibili.
Assist senza utente diretto, script derivati e automazioni non sono classificabili
con certezza nella Phase 1. I contesti derivati e sconosciuti sono opt-in e hanno
confidence inferiore. Uno script lanciato direttamente dall’utente è appreso
come controllo script; le azioni interne non diventano automaticamente manuali.

I target espliciti, area, dispositivo, gruppo, piano ed etichetta usano il resolver
HA e sono intersecati con le entità consentite. Sono apprese solo azioni di
controllo riconosciute; creazione scene, reload e richieste di dati sono ignorati.

Ogni utilizzo registra timestamp, entity ID, user ID se disponibile, origine,
azione, confidence e area. Il periodo di scoring è configurabile; la retention
locale arriva a 90 giorni e massimo 50.000 eventi. I dati partono dall’installazione:
nessuna importazione dello storico Recorder e nessuna query SQL.

Il punteggio combina quantità degli utilizzi, vicinanza all’ora attuale, decadimento
temporale, confidence e plausibilità dello stato. Esempio: una luce già accesa
rimane interessante se normalmente viene spenta a quest’ora. Le scene non sono
interpretate semanticamente. L’orario segue il fuso configurato in HA, anche
attraversando mezzanotte. Le formule sono in [ARCHITECTURE.md](ARCHITECTURE.md).

All’inizio sono mostrati controlli recenti e fissi. Senza utilizzi né fissi il
sensore vale 0: è normale. Dopo almeno tre eventi per entità prevale il modello
temporale. I candidati sotto soglia restano esclusi; non si riempiono gli slot
con raccomandazioni inventate. I fissi rispettano esclusioni, aree e disponibilità.

Presenza, affinità per area, giorno feriale/weekend e contesto casa sono Phase 2.
In Phase 1 le aree filtrano l’ammissibilità e vengono conservate nei record.

## Privacy e sicurezza

Tutti i dati restano nell’istanza. Store salva in
`/config/.storage/contextual_controls.<entry_id>` con gestione privata dei file.
Backup HA può includere questo file. Eliminare l’integrazione elimina il relativo
storico; un riavvio o reload invece lo conserva. Un arresto improvviso può perdere
gli ultimi eventi non ancora scritti (scritture differite di circa 15 secondi).

Il sensore non espone user ID né timestamp dei singoli utilizzi. Diagnostics
contiene solo conteggi e impostazioni non sensibili. Il debug è disabilitato
di default e limita i dettagli a 30 candidati. L’attributo `entities` contiene
entity ID, quindi va trattato come informazione della propria casa.

Lock richiede inclusione esplicita. Alarm e siren sono esclusi. L’integrazione
non esegue alcuna azione sui dispositivi: la futura card userà more-info per i
controlli sensibili. La selezione delle entità in questa integrazione non crea
un nuovo sistema di permessi: valgono i permessi nativi Home Assistant.

## Risultato e Lovelace nella Phase 1

Apri il sensore oppure Strumenti per sviluppatori → Stati. Lo stato è il numero
di controlli, inclusi i fissi. Attributi: `entities`, `last_update`, `mode`,
`ai_used`, `learning_period_days`, `candidate_count` e conteggi dello storico.

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
    reason: Usato frequentemente in questa fascia oraria
    source: statistical
    rank: 2
    pinned: false
    usage_count_in_window: 8
mode: statistical
ai_used: false
```

Per visualizzare il sensore senza YAML: modifica la dashboard, aggiungi una card
Entità e scegli il sensore creato. Questo mostra il conteggio e permette di
aprire i dettagli; non genera tile dinamiche. `contextual-controls-card`, editor
visuale, layout responsive e titolo dinamico sono esclusivamente Phase 4.

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
- **Funziona senza internet?** Sì, integralmente nella Phase 1.
- **Perché non uso già AI?** Prima si verifica l’apprendimento locale; non è
  necessario un modello esterno per produrre suggerimenti.

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
Ultima verifica: 48 test locali e 3 test HA passati; hassfest senza errori.
I test AI, weekday/presenza e frontend appartengono alle fasi future. Risultati
e limiti della verifica effettiva sono in [docs/VERIFICATION.md](docs/VERIFICATION.md).

Licenza MIT. Le decisioni e le fonti ufficiali sono in
[ARCHITECTURE.md](ARCHITECTURE.md).
