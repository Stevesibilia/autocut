# AutoCut — Specifiche di progetto

Documento di specifiche destinato a Claude Code. Descrive un'applicazione per
la selezione e la preparazione automatica di clip video da riprese di vacanza
(drone, telefono, fotocamera), pensata per alimentare un editor di montaggio
esterno (CapCut desktop) anziché sostituirlo.

---

## 1. Obiettivo

Data una cartella con decine o centinaia di file video grezzi, produrre una
cartella di sotto-clip **già scremate, già tagliate, già ordinate e già
normalizzate**, pronte da importare in CapCut con un solo drag & drop.

Il problema da risolvere non è il montaggio in sé, ma la scrematura: guardarsi
150 file per trovare i 3 secondi buoni di ognuno. Il montaggio vero e proprio
(beat sync, transizioni, titoli, export) resta a CapCut, che lo fa già bene.

### Criterio di successo

Da ~150 file grezzi di una vacanza si deve ottenere in un'unica passata una
cartella `_selects/` con 30-50 clip numerate, tutte utilizzabili, che importate
in ordine alfabetico in CapCut producano una timeline sensata senza ulteriore
riordino manuale.

---

## 2. Non-obiettivi

Cose che il progetto **non** deve fare:

- Non è un editor video. Niente timeline, niente rendering del montaggio finale.
- Non genera transizioni, titoli, sottotitoli o effetti.
- Non genera musica. Produce il prompt da incollare in Suno, non l'audio.
- Non fa upload su servizi cloud. Tutto deve girare in locale.
- Non deve gestire progetti collaborativi o multi-utente.

---

## 3. Contesto d'uso

- Utente singolo, tecnicamente competente (sa leggere Python, sa usare la CLI).
- Quattro sorgenti da gestire, spesso mescolate nella stessa vacanza:
  - **drone** (DJI): riprese aeree, file lunghi, molto materiale inutile
    all'inizio e alla fine di ogni volo;
  - **action cam** (GoPro, Insta360): alto frame rate, campo visivo molto ampio
    con distorsione, tanto materiale mosso, spesso registrazioni continue lunghe;
  - **telefono**: scene familiari, verticali e orizzontali mescolate, clip brevi;
  - **reflex**: poche clip ma di qualità alta, spesso su cavalletto o gimbal.
- Colonna sonora generata con Suno. Il flusso è a due passate: prima si
  selezionano le clip, poi l'applicazione **genera il prompt Suno** adatto al
  montaggio, l'utente genera la traccia, e la traccia rientra
  nell'applicazione per il taglio a battuta.
- Editor a valle: CapCut desktop.

---

## 4. Architettura

Tre strati nettamente separati, in questo ordine di sviluppo:

```
autocut/
├── core/          # libreria: analisi, scoring, selezione, export
├── cli/           # interfaccia a riga di comando (Fase 1)
└── gui/           # applicazione desktop (Fase 2)
```

Vincolo architetturale importante: `core/` non deve **mai** importare nulla da
`cli/` o `gui/`, e non deve stampare a schermo. Comunica progresso ed eventi
tramite callback o generatori, così che CLI e GUI possano entrambe consumarlo.
La GUI della Fase 2 deve essere un consumatore della stessa API che usa la CLI,
non una riscrittura.

### Fase 1 — prototipo CLI

Scopo: validare la qualità della selezione automatica sul materiale reale prima
di investire nella GUI. Deve essere usabile e utile da solo.

### Fase 2 — applicazione desktop con GUI

Scopo: rendere il processo pilotabile e correggibile a mano, perché nessun
algoritmo di scoring azzeccherà il 100% delle scelte e serve un passaggio di
revisione umana rapido.

---

## 5. Stack tecnologico

### Core

- **Python 3.11+**
- **ffmpeg / ffprobe** come binari esterni, invocati via `subprocess`. Non usare
  wrapper Python che nascondono i parametri: il controllo fine sui filtri serve.
- **PyAV** oppure **OpenCV** per il decoding campionato dei frame. PyAV è
  preferibile per efficienza e controllo sui keyframe; OpenCV è accettabile se
  semplifica molto il codice.
- **NumPy** per le metriche sui frame.
- **PySceneDetect** per lo split dei file che contengono più inquadrature.
- **librosa** per l'analisi della traccia audio (beat tracking, BPM).
- **Pydantic** per i modelli dati e la validazione della configurazione.
- **Rich** o **tqdm** per l'output della CLI.

### GUI (Fase 2)

Preferenza: **PySide6 (Qt)**. Motivazioni: il core è già Python quindi non serve
un ponte tra linguaggi; Qt gestisce nativamente l'accesso al filesystem, le
griglie di miniature e la riproduzione video con `QMediaPlayer`; l'app finale è
distribuibile con PyInstaller o Nuitka.

Alternative accettabili se emergono problemi seri di packaging o di
responsività: **Flet** (più rapido da scrivere, meno controllo) oppure un'app
locale **FastAPI + frontend web** in una finestra `pywebview`. In quest'ultimo
caso però va risolto il problema dell'anteprima video di file locali di grandi
dimensioni, che è il motivo principale per cui Qt è la scelta di default.

Da evitare: Electron, per il peso e per la duplicazione di runtime.

---

## 6. Pipeline funzionale

### 6.1 Ingest

Scansione ricorsiva di una o più cartelle sorgente.

- Estensioni accettate: `.mp4`, `.mov`, `.mkv`, `.avi`, `.m4v`, `.insv`, `.lrv`.
- Per ogni file, `ffprobe` in JSON: durata, risoluzione, fps, codec, bitrate,
  `creation_time`, rotazione.
- Estrazione GPS quando disponibile. I file DJI e quelli da iPhone/Android
  espongono le coordinate nell'atomo `moov/udta`; `exiftool` è più affidabile di
  `ffprobe` per questo, quindi va usato se presente sul sistema, con fallback
  silenzioso se manca.

**Classificazione della sorgente.** Ogni file va etichettato come `drone`,
`actioncam`, `phone` o `reflex`, perché soglie di scoring, regole di scarto e
trattamento in export differiscono per sorgente. La classificazione va dedotta
automaticamente da marca e modello nei metadati, dai pattern di nome file
(`DJI_`, `GX01`, `IMG_`, `VID_`, `DSC_`), dalla presenza di sidecar tipici e dal
frame rate. Deve essere **sovrascrivibile a mano** per cartella e per file,
perché il rilevamento automatico sbaglierà su qualche modello.

**Telemetria per sorgente.** È il vantaggio più grosso disponibile e va sfruttato
dove c'è:

- **Drone DJI**: sidecar `.SRT` con lo stesso nome del video, con altitudine
  relativa, GPS, ISO, shutter e focale per frame. L'altitudine è il segnale più
  affidabile in assoluto per scartare decolli e atterraggi, molto meglio di
  qualsiasi euristica sull'immagine.
- **GoPro**: telemetria **GPMF** in uno stream dati dentro l'MP4, estraibile con
  `ffmpeg -codec copy -map 0:d`. Contiene accelerometro, giroscopio e GPS.
  L'accelerometro identifica gli scossoni meglio di qualsiasi analisi dei pixel,
  e il GPS distingue le riprese in movimento da quelle statiche.
- **Insta360**: i `.insv` sono file proprietari con traccia dati; se il parsing
  risulta complesso, è accettabile richiedere all'utente l'esportazione
  preventiva in MP4 dallo Studio ufficiale, documentando il limite. I `.lrv`
  sono proxy a bassa risoluzione e, quando presenti, vanno usati per l'analisi
  al posto del file pieno: è un guadagno di velocità enorme, a costo zero.
- **Telefono e reflex**: nessuna telemetria, si procede con le sole metriche
  sull'immagine.

**Note specifiche per sorgente:**

- Action cam: campo visivo molto ampio, quindi la metrica di nitidezza va
  calcolata sul centro del frame, non sull'intero fotogramma, altrimenti la
  distorsione ai bordi falsa il punteggio. Frame rate alti (120/240 fps) vanno
  riconosciuti come candidati naturali allo slow motion.
- Telefono: presenza di clip verticali. Vanno rilevate e gestite esplicitamente
  (§6.7), non mescolate silenziosamente alle orizzontali.
- Reflex: soglie di qualità più severe, perché il materiale è poco e già buono;
  lo scarto aggressivo qui è controproducente.
- Ordinamento cronologico globale su `creation_time`, con fallback su mtime.
  Il mescolamento di sorgenti diverse (drone + telefono + reflex) deve produrre
  un ordine temporale coerente.

### 6.2 Segmentazione

- PySceneDetect (`ContentDetector`) su ogni file per individuare stacchi interni.
  Un file che contiene tre inquadrature diverse va trattato come tre candidati
  separati, non come uno solo.
- Sotto una soglia minima (default 1.5 s) i segmenti si scartano.

### 6.3 Analisi e scoring

Decoding campionato: **non decodificare tutti i frame**. Campionare a 2 fps,
ridimensionando a lato lungo 320 px. Su 4K questo è la differenza tra minuti e
ore.

Metriche per frame campionato:

| Metrica | Metodo | Serve a |
|---|---|---|
| Nitidezza | Varianza del laplaciano | Scartare mosso e fuori fuoco |
| Esposizione | % di pixel clippati a 0 e a 255 nell'istogramma | Scartare sotto/sovraesposto |
| Movimento | Magnitudine media del flusso ottico, o differenza assoluta tra frame consecutivi | Distinguere movimento cinematico da staticità e da scossoni |
| Stabilità | Deviazione standard del vettore di movimento nel tempo | Scartare gimbal instabile e correzioni brusche |
| Colorfulness | Metrica di Hasler-Süsstrunk | Premiare tramonti e paesaggi saturi, penalizzare cielo bianco piatto |

Lo score composito è una media pesata con **pesi configurabili da file di
configurazione**, non hardcoded. I pesi giusti si trovano solo iterando sul
materiale reale.

Regole di scarto esplicite, applicate prima dello scoring:

- Segmenti con altitudine sotto una soglia (dal `.SRT`) → decollo/atterraggio.
- Segmenti con movimento sotto una soglia per tutta la durata → drone fermo.
- Segmenti con movimento sopra una soglia e stabilità bassa → riprese scosse.
- Primi e ultimi N secondi di ogni file (default 1 s) → sempre scartati, sono
  quasi sempre l'inizio e la fine della pressione sul pulsante.

### 6.4 Selezione della finestra migliore

Per ogni segmento sopravvissuto, ricerca a finestra scorrevole della sottofinestra
di durata target con lo score medio più alto. Durata target configurabile,
default 3 s.

Vincoli sulla selezione globale:

- Massimo N clip per file sorgente (default 1) per evitare che un unico volo
  lungo monopolizzi il montaggio.
- Numero massimo di clip totali, configurabile.
- Quota minima per sorgente, così che un montaggio non diventi solo aeree
  perché il drone produce le inquadrature tecnicamente più pulite.

#### Deduplica e diversità

**Requisito centrale del progetto, non una rifinitura.** La selezione per solo
punteggio produce sistematicamente il risultato sbagliato: dieci inquadrature
quasi identiche della stessa spiaggia, tutte con score alto, e un montaggio
noioso. Il valore di una clip dipende da quelle già scelte, non solo da sé stessa.

L'algoritmo deve essere di selezione **greedy con penalità di similarità**: si
sceglie iterativamente la clip che massimizza `score - λ · max(similarità con le
clip già selezionate)`, con `λ` configurabile e regolabile dall'interfaccia.
Alternativa accettabile: Maximal Marginal Relevance, che è la stessa idea
formalizzata.

La similarità va calcolata su più segnali combinati, ciascuno disattivabile:

| Segnale | Metodo | Cattura |
|---|---|---|
| Visivo | Distanza coseno tra embedding CLIP/SigLIP | Somiglianza semantica reale (stessa scena, stesso soggetto) |
| Visivo (fallback) | Perceptual hash + istogramma colore | Somiglianza grossolana, senza modelli |
| Spaziale | Distanza GPS | Riprese fatte nello stesso punto |
| Temporale | Distanza tra timestamp | Clip consecutive dello stesso momento |
| Movimento | Somiglianza del profilo di movimento | Tre panoramiche identiche da sinistra a destra |

Vincoli aggiuntivi sulla diversità:

- Numero massimo di clip per cluster visivo, configurabile (default 2-3).
- Distanza temporale minima tra clip consecutive nel montaggio finale, per
  evitare tre inquadrature dello stesso minuto una dopo l'altra.
- Bilanciamento tra categorie semantiche: se il materiale contiene aeree,
  persone, cibo e dettagli, il montaggio dovrebbe attingere a tutte, non solo
  alla categoria più numerosa.

Il fallback senza modelli AI (phash + istogrammi + GPS + tempo) deve esistere e
funzionare in modo accettabile: il modulo AI migliora nettamente la qualità della
deduplica, ma la funzione non può dipenderne per esistere.

### 6.5 Generazione del prompt Suno

Dopo la selezione, l'applicazione analizza le clip **scelte** e produce un prompt
pronto da incollare in Suno per generare una colonna sonora coerente con il
montaggio. È il passaggio che chiude il cerchio: la musica viene costruita
addosso al video invece del contrario.

#### Ordine delle operazioni

C'è una dipendenza circolare da sciogliere esplicitamente: il taglio a battuta
(§6.6) ha bisogno del BPM, ma la traccia non esiste ancora. La soluzione:

1. AutoCut **sceglie** il BPM in base al materiale selezionato e lo scrive nel
   prompt come valore esplicito.
2. L'utente genera la traccia in Suno.
3. La traccia rientra in AutoCut, che ne **verifica il BPM reale** con librosa.
   Suno non garantisce di rispettare il BPM richiesto, quindi in caso di
   scostamento oltre una tolleranza l'applicazione deve avvisare e proporre di
   riquantizzare sul BPM effettivo.
4. Taglio a battuta ed export.

Il BPM proposto si ricava dalla durata media delle clip selezionate e
dall'energia del materiale, scegliendo un valore per cui le durate tipiche
cadano su multipli interi di battuta. Va comunque presentato come proposta
modificabile.

#### Segnali da cui deriva il prompt

Tutti già disponibili dall'analisi, nessuno richiede lavoro aggiuntivo:

- **Durata totale** del montaggio e numero di clip → lunghezza e articolazione
  del brano.
- **Profilo di energia** nel tempo (movimento medio per clip lungo la sequenza)
  → mappa direttamente sull'arco dinamico della struttura.
- **Tag semantici** dominanti (§7) → genere e strumentazione. Montagna e aeree
  chiedono qualcosa di diverso da spiaggia e famiglia.
- **Palette colore** dominante e temperatura → mood. Toni caldi e tramonti
  portano altrove rispetto a blu freddi e mare aperto.
- **Ora del giorno** dai timestamp e **luogo** dal GPS, con reverse geocoding
  offline opzionale → riferimenti geografici e atmosfera.
- **Rapporto tra sorgenti**: prevalenza di aeree suggerisce qualcosa di ampio e
  cinematografico, prevalenza di scene familiari qualcosa di più intimo.

#### Formato dell'output

File `suno-prompt.md` nella cartella di output, con tre blocchi copiabili:
**Title**, **Description**, **Structure**. Tutto in minuscolo, tutto strumentale.

Regole di formattazione da rispettare rigorosamente, sono i vincoli reali
dell'interfaccia Suno:

**Description** (campo stile, limite ~200 caratteri):

- Tag separati da virgola, mai frasi.
- Ordine di priorità, perché Suno pesa di più i tag iniziali: genere/epoca →
  strumenti con aggettivo specifico (`sweeping strings`, non `strings`) → mood →
  produzione → BPM.
- Da 4 a 7 descrittori. Di più peggiora il risultato.
- Nessuna ripetizione dello stesso concetto con parole diverse.
- Chiudere sempre con `no vocals, instrumental`.

**Structure** (campo lyrics, tag tra parentesi quadre):

- Un tag per riga, sempre.
- Un solo modificatore per tag, e il modificatore precede la parola di sezione.
  Mai virgole dentro le parentesi. `[slow intro]` e `[dark intro]` su due righe,
  mai `[slow, dark intro]`.
- Parole di sezione ammesse, nient'altro: `intro`, `verse`, `verse 1`, `verse 2`,
  `verse 3`, `pre-chorus`, `chorus`, `bridge`, `solo`, `break`, `drop`, `build`,
  `transition`, `outro`, `end`.
- Da 3 a 6 tag per sezione, che rinforzano dimensioni diverse (energia,
  strumento, mood, tempo).
- Nessun tag vocale di alcun tipo, essendo il brano strumentale.
- Gli aggettivi di produzione (`filtered`, `sidechained`, `punchy`) non
  funzionano come modificatori di struttura: vanno nella Description attaccati
  al loro strumento. Nella struttura si usa il nome dello strumento.
- Ogni strumento nominato nella Description deve comparire come modificatore in
  almeno due tag di struttura.
- L'ultima riga è sempre `[end]`.

**Mappatura energia → struttura.** Il profilo di energia del montaggio va
tradotto nell'arco della struttura: apertura calma sulle prime clip, sviluppo,
picco in corrispondenza delle clip con score e movimento più alti, chiusura in
risoluzione. Non un arco generico uguale per tutti i progetti, ma quello
effettivo del video montato.

#### Implementazione

Approccio a due livelli:

- **Base, senza modelli**: tabella di mappatura da (tag dominanti, mood colore,
  energia) a (genere, strumentazione, BPM) più un generatore di struttura basato
  su template. Deterministico, veloce, sempre disponibile.
- **Opzionale, con LLM locale**: rifinitura del prompt a partire dai segnali
  strutturati, per una descrizione più naturale e specifica. Vale la pena solo
  se l'output del livello base risulta insoddisfacente all'uso.

In entrambi i casi serve una **validazione formale** dell'output prima di
mostrarlo: lunghezza della Description entro il limite, un solo tag per riga,
assenza di virgole dentro le parentesi, parole di sezione valide, presenza di
`[end]`, assenza di tag vocali. Un prompt formalmente sbagliato produce musica
sbagliata, e l'errore non è evidente guardandolo.

L'applicazione deve poter generare **3-5 varianti** dello stesso prompt con mood
o strumentazione leggermente diversi, perché in Suno si generano comunque più
tentativi e conviene variare tra uno e l'altro.

### 6.6 Sincronizzazione al BPM

Questo è il passaggio che rende superfluo gran parte del lavoro manuale in CapCut.

- Se l'utente fornisce una traccia audio, `librosa.beat.beat_track()` per
  estrarre BPM e posizioni dei beat. L'utente deve poter **sovrascrivere il BPM
  a mano**, perché le tracce Suno hanno spesso un BPM noto e dichiarato e il
  rilevamento automatico occasionalmente lo dimezza o lo raddoppia.
- Ogni clip viene tagliata a una durata pari a un multiplo esatto della battuta:
  a 120 BPM significa 1 s, 2 s, 4 s. La scelta del multiplo per ogni clip segue
  lo score: le clip migliori ricevono durate più lunghe.
- Opzionale, comportamento configurabile: alternare durate lunghe e brevi per
  dare respiro al ritmo del montaggio, invece di usare la stessa durata ovunque.

Risultato: le clip messe semplicemente in fila cadono già sui beat, e l'auto
beat sync di CapCut deve correggere pochissimo o nulla.

### 6.7 Export delle clip

Taglio con ffmpeg. Due modalità:

- **Precisa** (default): re-encoding con `-c:v libx264 -crf 18` o HEVC, taglio
  al frame esatto. Più lenta, ma le durate a battuta devono essere esatte
  altrimenti il punto 6.5 non serve a niente.
- **Veloce**: `-c copy` con allineamento al keyframe più vicino. Utile per un
  primo giro esplorativo, va documentato che introduce imprecisione sulle durate.

Trasformazioni applicate in export:

- **Rimozione audio** (`-an`) come default. L'audio del drone è solo rumore di
  eliche e sporca la timeline di CapCut. Deve essere disattivabile per le clip
  familiari, dove l'audio ambientale ha senso.
- **Normalizzazione** di risoluzione e frame rate su un target unico
  configurabile (default 3840×2160 @ 30 fps). Evita che CapCut faccia conversioni
  al volo e scatti in preview.
- **Applicazione LUT** opzionale, con il filtro `lut3d`, per il materiale girato
  in D-Log o D-Cinelike. L'utente fornisce il file `.cube`. Deve essere possibile
  applicare **LUT diversi per sorgente**: D-Log del drone, flat della action cam,
  profilo del telefono e profilo della reflex non coincidono, e un unico LUT
  applicato a tutto peggiora tre sorgenti su quattro. La corrispondenza
  sorgente → LUT va nella configurazione.
- **Conversione slow motion** opzionale: le clip a 60 fps riesportate a 30 fps
  con `setpts` diventano slow motion fluido. Utile sulle riprese aeree e
  praticamente obbligatoria sulle action cam a 120 o 240 fps, dove la velocità
  reale è quasi sempre inguardabile.
- **Gestione delle clip verticali** dal telefono. Tre strategie configurabili:
  escluderle dalla selezione, riempire i lati con sfondo sfocato, oppure
  ritagliare al centro. Il default è escluderle, ma la scelta deve essere
  esplicita e visibile: mescolare silenziosamente verticali e orizzontali rovina
  il montaggio ed è il tipo di errore che si scopre solo in CapCut.
- **Correzione della distorsione** opzionale per le action cam, con il filtro
  `lenscorrection` o un LUT dedicato, per attenuare l'effetto fisheye sui bordi.

### 6.8 Nomenclatura dell'output

Vincolo funzionale forte: **CapCut importa in ordine alfabetico**, quindi il
nome del file è il meccanismo con cui si trasferisce l'ordine cronologico alla
timeline. Formato:

```
{indice:03d}_{data}_{sorgente}_{tag}_{durata}s.mp4

esempi:
012_20260812_drone_tramonto_4.0s.mp4
013_20260812_phone_famiglia_2.0s.mp4
014_20260812_actioncam_snorkeling_2.0s.mp4
015_20260813_reflex_dettaglio_4.0s.mp4
```

Struttura della cartella di output:

```
output/
├── _selects/         # le clip scelte, numerate
├── _rejects/         # gli scarti, per sicurezza (opzionale, configurabile)
├── report.html       # revisione visiva
├── manifest.json     # stato completo dell'analisi
├── suno-prompt.md    # prompt pronto da incollare in Suno (§6.5)
└── beatmap.txt       # posizioni dei beat, per riferimento in CapCut
```

### 6.9 Report di revisione

`report.html` autonomo, apribile nel browser: griglia con miniatura, nome file,
durata, score composito, punteggi delle singole metriche, e sorgente. Serve a
cancellare a mano in due minuti le clip che l'algoritmo ha sbagliato prima di
importare in CapCut.

Nella Fase 2 questo report è sostituito dalla schermata di revisione della GUI,
ma va mantenuto come output della CLI.

---

## 7. Componenti AI (opzionali, degradazione graduale)

L'uso di modelli è ammesso e in alcuni punti è chiaramente superiore alle
euristiche classiche. Vincoli non negoziabili:

- **Tutto in locale.** Nessuna chiamata ad API esterne per l'analisi del
  materiale. Modelli scaricati una volta e messi in cache.
- **Degradazione graduale.** L'applicazione deve funzionare, con qualità
  inferiore, anche se i modelli non sono installati o non c'è GPU. I moduli AI
  sono strato aggiuntivo sopra le metriche classiche, mai prerequisito.
- **Attivabili singolarmente** da configurazione.

Moduli previsti, in ordine di rapporto valore/complessità:

1. **Embedding CLIP o SigLIP** su un frame per segmento. È l'abilitatore di
   tutto il resto ed è il primo da implementare.

2. **Similarità semantica per la deduplica** (§6.4). La distanza tra embedding è
   il segnale di similarità nettamente migliore rispetto a hash percettivi e
   istogrammi, perché riconosce che due inquadrature della stessa baia da angoli
   diversi sono la stessa cosa mentre due tramonti in posti diversi non lo sono.
   È il modulo AI con il ritorno più alto e va implementato per primo dopo gli
   embedding stessi.

3. **Tagging semantico zero-shot.** Classificazione dell'embedding contro un set
   di etichette (`ripresa aerea`, `tramonto`, `spiaggia`, `montagna`, `persone`,
   `cibo`, `città`, `sott'acqua`, `interno`, `strada`). Serve a tre cose:
   popolare il campo `tag` del nome file, permettere all'utente di filtrare e
   bilanciare il montaggio per categoria, e alimentare la generazione del prompt
   Suno (§6.5), che senza tag semantici resta molto generica.

4. **Scoring estetico.** Aesthetic predictor addestrato su embedding CLIP (i
   pesi LAION sono adatti). Cattura qualità che le metriche classiche non vedono:
   composizione, luce, interesse del soggetto.

5. **Rilevamento volti** (MediaPipe o InsightFace). Le scene familiari hanno un
   valore che nessuna metrica di nitidezza cattura: una clip mossa con dentro tuo
   figlio vale più di un panorama perfetto. Deve alzare lo score, non abbassarlo,
   e va gestita come regola separata dalle metriche di qualità tecnica. Serve
   anche alla deduplica: due clip visivamente simili ma con persone diverse non
   vanno trattate come duplicati.

6. **Rifinitura del prompt Suno tramite LLM locale** (§6.5, opzionale). Prende i
   segnali strutturati già calcolati e produce una descrizione musicale più
   specifica di quella generata da template. L'output deve passare comunque dalla
   validazione formale, perché un LLM ignora volentieri i vincoli di formato di
   Suno.

7. **Ordinamento narrativo tramite LLM** (bassa priorità). Da GPS e timestamp si
   può ricavare la sequenza dei luoghi e proporre un raggruppamento per tappa
   invece che puramente cronologico.

---

## 8. Modello dati

Un unico `manifest.json` è la fonte di verità e lo stato persistente del
progetto. Deve contenere, per ogni segmento analizzato: percorso sorgente,
in/out point, tutte le metriche grezze, lo score composito, l'esito
(selezionato/scartato) con la motivazione, i tag, il percorso del file esportato.

Requisito importante: **cache dell'analisi**. Le metriche vanno indicizzate su
hash del file (o su percorso + dimensione + mtime, se l'hash su file da GB è
troppo lento). Rianalizzare la stessa cartella dopo aver cambiato solo i pesi di
scoring deve essere istantaneo. Senza questo, l'iterazione sui parametri è
impraticabile e i parametri giusti si trovano solo iterando.

Il manifest deve anche essere il formato di progetto della GUI: aprire un
manifest esistente ripristina lo stato completo della revisione.

---

## 9. Interfaccia CLI (Fase 1)

```bash
# prima passata
autocut analyze    ./riprese --out ./montaggio-grecia
autocut select     ./montaggio-grecia --max-clips 40 --duration 3.0 --diversity 0.6
autocut soundtrack ./montaggio-grecia --variants 3
autocut report     ./montaggio-grecia

# ...si genera la traccia in Suno, poi seconda passata

autocut sync       ./montaggio-grecia --audio traccia-suno.mp3
autocut export     ./montaggio-grecia --no-audio
```

Comandi separati e rieseguibili singolarmente, che leggono e scrivono lo stesso
manifest. È un requisito, non un dettaglio: il ciclo di messa a punto consiste
nel rilanciare `select` venti volte con parametri diversi sopra un `analyze`
fatto una volta sola.

`autocut sync` senza `--bpm` esplicito rileva il BPM reale della traccia e lo
confronta con quello proposto in fase di `soundtrack`, avvisando in caso di
scostamento. Con `--bpm` il valore fornito ha la precedenza.

Un comando `autocut run` che concatena la prima passata è utile come scorciatoia.

Configurazione da `autocut.toml`, con override da riga di comando.

---

## 10. Interfaccia GUI (Fase 2)

Flusso a cinque schermate, con navigazione avanti/indietro.

**1. Progetto e sorgenti.** Selezione delle cartelle sorgente (drag & drop),
cartella di output, scelta del profilo (drone / famiglia / misto). Apertura di
un progetto esistente da manifest.

**2. Analisi.** Barra di avanzamento con file corrente, tempo stimato residuo e
possibilità di annullare. L'analisi gira in un worker separato: la UI non deve
mai bloccarsi. Su cartelle da centinaia di GB questo passaggio dura a lungo e
deve essere interrompibile e riprendibile.

**3. Revisione.** È la schermata centrale dell'applicazione e va curata più
delle altre.

- Griglia di miniature, ordinate per posizione cronologica o per score.
- Anteprima al passaggio del mouse: scrubbing sulla clip senza aprirla.
- Toggle tieni/scarta con un click, e con la tastiera (spazio, frecce), perché
  quaranta clip da rivedere con il mouse sono quaranta click di troppo.
- Regolazione dei punti di in/out della singola clip, con anteprima.
- Filtri per tag, per sorgente, per fascia di score.
- Slider dei pesi di scoring con **riordinamento in tempo reale** della griglia.
  Possibile solo grazie alla cache di §8, ed è la funzione che rende la GUI
  effettivamente superiore alla CLI.
- **Slider di diversità** (il `λ` di §6.4), con ricalcolo immediato della
  selezione. Da un estremo "solo le migliori" all'altro "il più varie possibile".
  È il parametro che l'utente vorrà toccare più spesso, quindi deve stare in
  primo piano e non in un pannello di impostazioni avanzate.
- **Vista per gruppi di simili**: le clip considerate duplicate vanno mostrate
  raggruppate, con evidenziata quella scelta dall'algoritmo e le altre in
  secondo piano. Deve bastare un click per dire "no, tieni quest'altra". È il
  modo più veloce per correggere gli errori di deduplica, che sono inevitabili.
- Contatore visibile di clip selezionate e durata totale del montaggio.

**4. Colonna sonora.** Diviso in due momenti, che rispecchiano le due passate.

Prima: il prompt Suno generato dalle clip selezionate, mostrato nei tre blocchi
(Title, Description, Structure) con un pulsante di copia per ciascuno, la
possibilità di scorrere tra le varianti generate, un campo BPM modificabile che
rigenera il prompt, e alcuni controlli di alto livello sul mood (più calmo /
più energico, più cinematografico / più intimo) per chi vuole guidare il
risultato senza riscrivere i tag a mano. Il prompt deve essere anche
**editabile a mano**, con la validazione formale che segnala gli errori in
tempo reale.

Poi: caricamento della traccia generata, waveform con i beat rilevati, confronto
tra BPM richiesto e BPM effettivo con avviso in caso di scostamento, e scelta
della strategia di durata.

**5. Export.** LUT per sorgente, risoluzione e frame rate target, gestione dei
verticali, slow motion, rimozione audio. Poi export con avanzamento e apertura
della cartella risultante al termine.

Requisiti trasversali della GUI: nessuna operazione lunga sul thread della UI;
stato salvato di continuo sul manifest, così una chiusura accidentale non perde
un'ora di revisione; interfaccia in italiano.

---

## 11. Prestazioni

Obiettivo indicativo: analisi di 100 GB di 4K in meno di 30 minuti su un
portatile recente senza GPU.

Leve principali, in ordine di impatto:

- Campionamento dei frame invece del decoding completo (§6.3). È la leva
  decisiva, tutto il resto è secondario.
- Elaborazione dei file in parallelo con `ProcessPoolExecutor`, dimensionata sui
  core fisici.
- Decoding hardware quando disponibile (`h264_cuvid`, `videotoolbox`), con
  fallback software.
- Cache persistente (§8).

---

## 12. Roadmap

**M1 — Ingest e analisi.** Scansione, ffprobe, parsing SRT, metriche classiche,
manifest, cache. Output: solo `report.html`, nessun taglio. Serve a verificare
che lo scoring sia sensato prima di costruirci sopra.

**M2 — Selezione ed export.** Finestra migliore, regole di scarto, deduplica con
i segnali classici (phash, istogrammi, GPS, tempo), taglio, normalizzazione,
nomenclatura. A questo punto lo strumento è già utile.

**M3 — Embedding e diversità.** CLIP/SigLIP, similarità semantica, selezione
greedy con penalità, tagging zero-shot. Anticipato rispetto agli altri moduli AI
perché la deduplica è un requisito centrale e non una rifinitura, e perché il
tagging è il presupposto di M4.

**M4 — Colonna sonora.** Generazione del prompt Suno da template, validazione
formale, varianti. Poi beat tracking sulla traccia generata, durate a battuta,
verifica del BPM effettivo, `beatmap.txt`.

**M4b — Moduli AI rimanenti.** Scoring estetico, rilevamento volti, eventuale
rifinitura del prompt con LLM.

**M5 — GUI.** Le cinque schermate sopra il core esistente.

**M6 — Packaging.** Eseguibile distribuibile, ffmpeg incluso o rilevato, primo
avvio che scarica i modelli.

Fermarsi dopo M2 e usare lo strumento su materiale reale prima di procedere è un
esito accettabile e probabilmente auspicabile: i parametri di scoring vanno
tarati sul materiale vero, e ogni milestone successiva costruisce su quella
taratura.

---

## 13. Test

- Fixture: una decina di clip brevi che coprano i casi noti (decollo, mosso,
  sovraesposto, statico, ripresa buona, multi-inquadratura). Non servono file
  grandi.
- Test unitari sulle metriche, con valori attesi per ogni fixture.
- Test sulla generazione dei comandi ffmpeg, verificando la stringa prodotta
  senza eseguirla.
- Test di integrazione end-to-end su una cartella fixture, verificando durate
  esatte delle clip esportate quando la modalità di taglio è precisa.
- Test sulla quantizzazione a battuta: a BPM noto le durate risultanti devono
  essere multipli esatti entro un frame.
- Test sulla deduplica: date fixture con clip deliberatamente quasi identiche
  (stessa scena, angoli leggermente diversi), la selezione ne deve tenere al
  massimo il numero configurato, e deve tenere quella con lo score più alto.
- Test sul validatore del prompt Suno: una batteria di prompt malformati
  (virgole dentro le parentesi, più tag sulla stessa riga, parole di sezione
  inventate, tag vocali su un brano strumentale, Description oltre il limite)
  deve essere respinta con l'errore corretto. Questo test è più importante di
  quanto sembri, perché è l'unico modo di accorgersi di un prompt sbagliato
  senza generare la traccia.

---

## 14. Questioni aperte

Da chiarire con l'utente prima o durante M1:

1. **Sistema operativo di destinazione.** Determina il decoding hardware, i
   percorsi di ffmpeg e la strategia di packaging.
2. **Modelli esatti delle quattro sorgenti.** Servono per verificare la
   disponibilità e il formato della telemetria: `.SRT` per il drone, GPMF per la
   GoPro, tracce dati per Insta360. È l'informazione più utile in assoluto per
   la qualità delle regole di scarto.
3. **Profili colore usati per sorgente.** D-Log, D-Cinelike, flat, standard.
   Determina se il modulo LUT è centrale o accessorio e quanti LUT servono.
4. **Presenza di GPU** utilizzabile, che sposta significativamente la soglia di
   convenienza dei moduli AI.
5. **Generi musicali preferiti** per i montaggi di vacanza, da usare come base
   della tabella di mappatura in §6.5. Senza questo, il generatore di prompt
   produce cinematic ambient per qualunque cosa.
6. Se in Suno si usi la modalità strumentale pura (solo campo Description) o
   quella con campo lyrics disponibile, perché nel primo caso il blocco Structure
   non ha dove essere incollato e conviene comunque generarlo per riferimento.
7. Se il montaggio debba essere sempre cronologico o se abbia senso un
   raggruppamento per luogo o per tappa.
