#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera la relazione .docx del progetto (benchmark applicativo + Redis distribuito).
Uso:  py build_report.py
Output:  Relazione_Redis_Distribuito.docx
"""

from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).parent
APP = ROOT / "results" / "run4_32w" / "charts"          # 3 repliche PostgreSQL
APP5 = ROOT / "results" / "run5_32w_1db" / "charts"     # 1 database singolo
REDIS = ROOT / "results" / "redis" / "charts"
ARCH = ROOT / "results" / "architecture.png"
OUT = ROOT / "Relazione_Redis_Distribuito.docx"

doc = Document()
normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(11)


def h1(t): doc.add_heading(t, level=1)
def h2(t): doc.add_heading(t, level=2)

def p(t):
    par = doc.add_paragraph(t)
    par.paragraph_format.space_after = Pt(8)
    return par

def img(path, w=6.1, caption=None):
    if Path(path).exists():
        doc.add_picture(str(path), width=Inches(w))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if caption:
            c = doc.add_paragraph(caption)
            c.alignment = WD_ALIGN_PARAGRAPH.CENTER
            c.runs[0].italic = True
            c.runs[0].font.size = Pt(9)
    else:
        ph = doc.add_paragraph(f"[grafico da inserire: {Path(path).name}]")
        ph.runs[0].italic = True

def table(headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for i, htext in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = htext
        for par in cell.paragraphs:
            for run in par.runs:
                run.font.bold = True
                run.font.size = Pt(10)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
            for par in cells[i].paragraphs:
                for run in par.runs:
                    run.font.size = Pt(10)
    doc.add_paragraph()
    return t


# ============================================================== TITOLO
doc.add_heading("Valutazione di Redis in configurazione distribuita", level=0)
sub = doc.add_paragraph("Scalabilità all'aumentare dei nodi e delle richieste, e comportamento al fallimento di un nodo")
sub.runs[0].italic = True
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

# ============================================================== 1. INTRODUZIONE
h1("1. Introduzione")
p("Questo documento raccoglie il lavoro svolto per valutare il comportamento di Redis quando "
  "viene distribuito su più nodi. Il punto di partenza è un'applicazione che simula un social "
  "network: un backend che espone gli endpoint tipici di un feed (timeline, profili, post, "
  "like) e che usa Redis come cache davanti a un database PostgreSQL. Su questa base abbiamo "
  "prima misurato quanto la cache incide sulle prestazioni e dove si trova il collo di "
  "bottiglia del sistema, e poi siamo passati al cuore della richiesta: capire come Redis "
  "scala quando i nodi aumentano, come si comporta all'aumentare del carico a parità di nodi, "
  "e cosa succede quando un nodo viene a mancare.")
p("Le tre domande a cui rispondiamo sono: come scala Redis a parità di richieste "
  "all'aumentare dei nodi; come scala all'aumentare delle richieste tenendo fissi i nodi; e "
  "come gestisce il fallimento di un nodo. Per ognuna riportiamo la metodologia, i numeri "
  "ottenuti e una lettura dei risultati.")

# ============================================================== 2. AMBIENTE
h1("2. Ambiente di prova")
p("L'infrastruttura è composta da cinque macchine virtuali su Azure, collegate sulla stessa "
  "rete privata. Una macchina più potente (16 vCPU) ospita il backend applicativo e funge "
  "anche da generatore di carico; le altre quattro sono macchine da 4 vCPU e 16 GB di RAM "
  "ciascuna. È importante notare che le stesse macchine hanno avuto un ruolo diverso nelle due "
  "fasi del lavoro. Nella fase del benchmark applicativo, VM-1, VM-2 e VM-3 erano le tre "
  "repliche di lettura di PostgreSQL, mentre VM-4 ospitava il PostgreSQL principale (il "
  "master). Nella fase di test su Redis, le stesse VM-1, VM-2 e VM-3 sono state riutilizzate "
  "come nodi del cluster Redis, mentre VM-4 è rimasta il database. Non potevano svolgere "
  "entrambi i ruoli contemporaneamente, avendo a disposizione solo cinque macchine.")
table(["Nodo", "Risorse", "Fase benchmark applicativo", "Fase test Redis"],
      [["Worker-1", "16 vCPU", "Backend FastAPI + generatore di carico", "Generatore di carico (memtier)"],
       ["VM-1", "4 vCPU, 16 GB", "Replica di lettura PostgreSQL", "Nodo Redis cluster"],
       ["VM-2", "4 vCPU, 16 GB", "Replica di lettura PostgreSQL", "Nodo Redis cluster"],
       ["VM-3", "4 vCPU, 16 GB", "Replica di lettura PostgreSQL", "Nodo Redis cluster"],
       ["VM-4", "4 vCPU, 16 GB", "PostgreSQL principale (master)", "PostgreSQL principale (master)"]])
p("Il backend è scritto in Python (FastAPI) e gira con 32 processi worker. Redis è nella "
  "versione 7. I test applicativi usano Locust, che simula utenti concorrenti via HTTP; i "
  "test sul solo Redis usano memtier_benchmark, eseguito sulla macchina del backend, separata "
  "dai nodi del cluster come raccomandato dalla documentazione ufficiale.")
img(ARCH, caption="Schema dell'architettura: Worker-1 (backend, 32 worker, generatore di carico), le tre VM (repliche PostgreSQL nella fase applicativa, nodi Redis nella fase di test) e VM-4 (PostgreSQL principale).")

# ============================================================== 3. MISURAZIONI E BOTTLENECK
h1("3. Misurazioni e colli di bottiglia: quadro d'insieme")
p("Prima di entrare nel dettaglio dei singoli esperimenti conviene fissare il risultato più "
  "importante, perché spiega tutto il resto: in questo sistema il collo di bottiglia non è "
  "fisso, ma si sposta a seconda di come è configurato il livello di persistenza. Lo abbiamo "
  "misurato confrontando le strategie di caching in due configurazioni del database e poi "
  "sollecitando Redis direttamente.")
p("La tabella seguente riassume dove cede il sistema nelle varie condizioni e con quale "
  "throughput massimo. I valori applicativi sono in richieste al secondo (un'intera richiesta "
  "HTTP, che può comportare più operazioni interne); i valori di Redis sono in operazioni al "
  "secondo a livello di singolo comando.")
table(["Configurazione", "Collo di bottiglia", "Throughput massimo"],
      [["Senza cache, 1 database", "Database", "~23 richieste/s"],
       ["Senza cache, 3 repliche DB", "Database", "~450 richieste/s"],
       ["Con cache, 1 database", "Database (scritture e miss)", "~400 richieste/s"],
       ["Con cache, 3 repliche DB", "CPU del backend", "~1.480 richieste/s"],
       ["Redis cluster (test diretto)", "Generatore di carico (client)", "~2.000.000 operazioni/s"]])
p("Le note da tenere a mente sui colli di bottiglia sono tre. La prima: senza cache ogni "
  "lettura diventa una query, e il database satura quasi subito; è il caso peggiore. La "
  "seconda: con la cache attiva il database viene alleggerito dalle letture, ma scritture e "
  "letture che non trovano il dato continuano ad arrivarci, quindi con un solo nodo di "
  "database resta lui il limite, mentre con le repliche il limite passa alla CPU del backend "
  "(a quel punto il database è quasi a riposo, incide per circa il 7% del tempo di una "
  "richiesta). La terza, e più importante per il seguito: Redis non è mai il collo di "
  "bottiglia del sistema, perché è talmente veloce che a cedere è sempre qualcos'altro, prima "
  "il backend e poi, nei test diretti, la macchina che genera il carico.")
p("Lo spostamento del collo di bottiglia è il filo conduttore di tutto il lavoro e conviene "
  "leggerlo in tre passaggi. Partendo dal caso senza cache su un solo database, il limite è "
  "chiaramente il database: ogni richiesta è una query costosa e il nodo cede subito. "
  "Aggiungendo la cache, gran parte delle letture smette di toccare il database, che però "
  "resta il limite finché è un nodo solo, perché deve comunque assorbire scritture e letture "
  "mancate. Distribuendo il database su tre repliche di lettura, finalmente il database si "
  "libera e il punto di pressione si sposta sulla CPU del backend. È questo il senso della "
  "frase \"il collo di bottiglia si sposta\": non è un valore fisso, dipende da quale "
  "componente, di volta in volta, è quello più sollecitato.")
p("Un punto va chiarito perché a prima vista stona: senza cache, passando da un database a "
  "tre repliche, il throughput sale da circa 23 a circa 450 richieste al secondo, cioè quasi "
  "venti volte, non tre come ci si aspetterebbe da tre repliche. La spiegazione è che il "
  "singolo database, schiacciato dalla query di feed, non si limita a essere \"tre volte più "
  "lento\": entra in uno stato di sovraccarico in cui le richieste si accodano per decine di "
  "secondi (la latenza al novantanovesimo percentile arriva a oltre due minuti), e il "
  "throughput utile precipita ben al di sotto della sua quota proporzionale. Distribuendo le "
  "letture su tre repliche, ciascuna lavora in un regime non saturo e si evita questo "
  "collasso. Il confronto, quindi, non è tra un nodo e tre nodi nelle stesse condizioni, ma "
  "tra un nodo in collasso e tre nodi che lavorano in modo sano.")

# ============================================================== 4. BENCHMARK APPLICATIVO
h1("4. Benchmark applicativo: il dettaglio")
p("Per arrivare al quadro appena descritto abbiamo confrontato cinque strategie di gestione "
  "della cache (nessuna cache, cache-aside, write-through, push-feed e ibrida) facendo "
  "crescere gli utenti concorrenti da 10 fino a 700, in due configurazioni del database: una "
  "con un solo nodo di PostgreSQL e una con tre repliche di lettura. Confrontando le due si "
  "vede direttamente lo spostamento del collo di bottiglia.")

h2("4.1 Database NON distribuito (un solo nodo)")
p("Nel primo scenario tutte le operazioni convergono su un unico nodo di database. Senza "
  "cache (la curva più in basso del grafico) il sistema è praticamente immobile sulle 23 "
  "richieste al secondo a qualsiasi carico: l'unico database è il muro. Le strategie con "
  "cache fanno molto meglio, ma anche loro si fermano intorno alle 400 richieste al secondo, "
  "perché scritture e letture che non trovano il dato in cache continuano ad arrivare "
  "sull'unico nodo.")
img(APP5 / "throughput_vs_users.png", caption="DATABASE NON DISTRIBUITO (1 nodo) — Throughput: senza cache ~23 richieste/s, con cache ~400, limitato comunque dal database singolo.")
p("La latenza al novantanovesimo percentile spiega perché senza cache il throughput è così "
  "basso: non è un nodo lento, è un nodo in sovraccarico, con richieste in coda per decine di "
  "secondi (fino a oltre due minuti). È questo collasso a far precipitare il throughput.")
img(APP5 / "p99_vs_users.png", caption="DATABASE NON DISTRIBUITO (1 nodo) — Latenza 99° percentile: senza cache supera i 100 secondi, sintomo di sovraccarico.")

h2("4.2 Database distribuito (tre repliche)")
p("Distribuendo le letture su tre repliche lo scenario cambia radicalmente. Le strategie con "
  "cache salgono fino a circa 1.480 richieste al secondo, oltre tre volte rispetto al caso "
  "con un solo nodo. Anche il caso senza cache migliora molto (da 23 a circa 450), perché le "
  "query di lettura si ripartiscono su tre nodi che non collassano.")
img(APP / "throughput_vs_users.png", caption="DATABASE DISTRIBUITO (3 repliche) — Throughput: le strategie con cache raggiungono ~1.480 richieste/s. Il database non è più il limite.")

h2("4.3 Dove si sposta il collo di bottiglia")
p("Con le repliche, dove cede il sistema? La prossima immagine mostra la quota di tempo di "
  "una richiesta effettivamente spesa nel database: resta molto bassa, intorno al 7%. Il "
  "database è quasi a riposo, e il tempo se ne va nella CPU del backend, che diventa il nuovo "
  "collo di bottiglia. È la prova visiva dello spostamento descritto all'inizio.")
img(APP / "db_ratio.png", caption="DATABASE DISTRIBUITO (3 repliche) — Quota di tempo nel database: ~7%. Il limite non è più il database, ma la CPU del backend.")
p("Il riepilogo di questa parte è semplice: la cache porta un guadagno enorme (da 23 a circa "
  "400 richieste al secondo) e le repliche di lettura spostano ancora il limite (fino a circa "
  "1.480), finché a fermare il sistema non è più il database ma la CPU del backend. È questo "
  "il motivo per cui, per misurare davvero la scalabilità di Redis, lo abbiamo dovuto "
  "sollecitare direttamente, senza il backend di mezzo.")

# ============================================================== 5. METODOLOGIA REDIS
h1("5. Redis distribuito: metodologia")
p("Il cluster Redis è stato configurato con tre nodi master e sharding dei dati: le chiavi "
  "sono suddivise tra i nodi in base a una funzione di hash, e ogni chiave vive su un solo "
  "nodo. Nella prima fase non abbiamo usato repliche, quindi ogni nodo è l'unico responsabile "
  "della sua fetta di dati. Il carico è generato con memtier_benchmark dalla macchina del "
  "backend, che colpisce direttamente il cluster.")
p("La scelta di bypassare il backend è deliberata: come visto, l'applicazione satura sulla "
  "CPU del backend ben prima di mettere in difficoltà Redis. Misurando Redis in modo diretto "
  "otteniamo invece il suo comportamento reale.")

# ============================================================== 6. SCALING RICHIESTE
h1("6. Scalabilità con le richieste (nodi fissi)")
p("La prima prova tiene fisso il cluster a tre nodi e fa crescere il carico, aumentando "
  "progressivamente le connessioni e il livello di pipelining (quante richieste il client "
  "invia prima di attendere le risposte). I valori misurati sono i seguenti.")
table(["Carico (thread/conn/pipeline)", "Throughput (ops/s)", "Latenza media (ms)"],
      [["2 / 25 / 1", "162.000", "0,9"],
       ["4 / 50 / 1", "282.000", "2,1"],
       ["4 / 50 / 8", "1.420.000", "3,4"],
       ["4 / 50 / 16", "1.970.000", "4,9"],
       ["8 / 100 / 16", "1.930.000", "19,8"],
       ["8 / 100 / 32", "2.370.000", "33,3"],
       ["12 / 100 / 32", "2.200.000", "52,1"]])
p("Il throughput sale da circa 160 mila operazioni al secondo fino a superare i 2,3 milioni, "
  "poi smette di crescere mentre la latenza inizia a salire rapidamente: è la saturazione. "
  "Va però sottolineato che questo tetto, intorno ai 2 milioni di operazioni al secondo, non "
  "è il limite del cluster ma quello della macchina che genera il carico, come chiariamo nel "
  "punto successivo.")
img(REDIS / "expA_throughput_vs_load.png", caption="Throughput e latenza al crescere del carico, cluster fisso a tre nodi.")

# ============================================================== 7. SCALING NODI
h1("7. Scalabilità con i nodi (richieste fisse)")
p("La seconda prova è quella più legata alla domanda sulla distribuzione: come si comporta "
  "Redis aggiungendo nodi. Provando a misurare il throughput a uno, due e tre nodi, il "
  "risultato è risultato piatto.")
table(["Numero di nodi", "Throughput (ops/s)"],
      [["1", "~2.050.000"], ["2", "~2.060.000"], ["3", "~2.030.000"]])
p("La spiegazione non è che Redis non scali, ma che un singolo nodo è così veloce da saturare "
  "la capacità di generazione del client prima di essere messo in difficoltà. Lo abbiamo "
  "verificato in tutti i modi: riducendo le connessioni, cambiando il pipelining e usando "
  "due macchine generatrici insieme. In ogni caso il throughput resta intorno ai 2 milioni di "
  "operazioni al secondo, perché il limite è la rete e la CPU del client, non il cluster. È "
  "un comportamento documentato: quando il server è molto veloce, è il client a diventare il "
  "collo di bottiglia.")
img(REDIS / "expB_throughput_vs_nodes.png", caption="Throughput a uno, due e tre nodi: piatto, perché il limite è il generatore di carico.")
p("Per osservare lo scaling con i nodi serviva quindi misurare una dimensione diversa dal "
  "throughput grezzo: la capacità. Lo sharding distribuisce i dati tra i nodi, quindi più nodi "
  "significano più memoria complessiva e più chiavi gestibili. Abbiamo limitato la memoria di "
  "ogni nodo e misurato quante chiavi il cluster riesce a trattenere, a uno, due e tre nodi.")
table(["Numero di nodi", "Chiavi trattenute", "Rapporto rispetto a 1 nodo"],
      [["1", "733.211", "1,0×"],
       ["2", "1.521.009", "2,1×"],
       ["3", "2.304.964", "3,1×"]])
p("Il risultato è una scalabilità praticamente lineare: raddoppiando e triplicando i nodi, la "
  "capacità raddoppia e triplica. Questa è la risposta concreta alla domanda sullo scaling "
  "con i nodi, sulla dimensione che l'hardware permette di osservare.")
img(REDIS / "expD_capacity_vs_nodes.png", caption="Capacità del cluster al crescere dei nodi: scaling lineare grazie allo sharding.")

# ============================================================== 8. FAILOVER
h1("8. Fallimento di un nodo")
p("L'ultima parte mette alla prova la tolleranza ai guasti, confrontando due topologie: il "
  "cluster a tre master senza repliche e un cluster ad alta disponibilità con repliche.")

h2("8.1 Senza repliche")
p("Sul cluster a tre master senza repliche abbiamo lanciato un carico costante e, a metà "
  "prova, fermato uno dei tre master. L'effetto è stato immediato: il throughput è crollato a "
  "zero e il client ha iniziato a ricevere errori su tutte le richieste. Il nodo fermato era "
  "l'unico responsabile di un terzo delle chiavi, e senza una replica quelle chiavi sono "
  "diventate irraggiungibili.")
img(REDIS / "expC_failover_timeline.png", caption="Throughput nel tempo senza repliche: al fallimento del nodo il servizio crolla a zero.")
p("Un dettaglio merita una nota, perché è controintuitivo: ci si potrebbe aspettare un calo a "
  "due terzi (i due nodi superstiti continuano a lavorare), invece il servizio si ferma del "
  "tutto. Questo perché Redis Cluster, nella configurazione predefinita, rifiuta tutte le "
  "operazioni quando anche un solo gruppo di chiavi non è coperto: privilegia la coerenza al "
  "servizio parziale. Il sistema è tornato disponibile solo riavviando il nodo.")

h2("8.2 Con repliche")
p("Abbiamo poi configurato un cluster ad alta disponibilità con sei nodi: tre master e tre "
  "repliche, una per master, collocate ciascuna su una macchina diversa da quella del proprio "
  "master (così la caduta di una macchina non porta via master e copia insieme). Ripetendo "
  "l'arresto di un master, il risultato è opposto: la sua replica è stata promossa "
  "automaticamente a nuovo master in pochi secondi, riprendendo gli slot scoperti, e il "
  "cluster è tornato in stato operativo da solo. Lo abbiamo verificato dallo stato del "
  "cluster, che mostrava il nodo fermato come \"fail\" e la replica corrispondente diventata "
  "master degli slot del caduto.")
p("Il tempo di indisponibilità dipende dalla configurazione: il cluster attende un intervallo "
  "di rilevamento del guasto (cinque secondi) prima di dichiarare morto il master, a cui si "
  "aggiunge il tempo di elezione e promozione, nell'ordine di un paio di secondi. Il servizio "
  "si ripristina quindi in circa sei o sette secondi, contro un'indisponibilità a tempo "
  "indefinito nel caso senza repliche.")
p("Una nota metodologica: lo strumento di benchmark, caduto il nodo, non si riaggancia da "
  "solo alla nuova topologia e interrompe il carico, quindi la ripresa non si vede come "
  "risalita del throughput nei suoi dati. Per misurare con precisione il tempo di "
  "indisponibilità abbiamo usato una sonda dedicata, descritta al punto seguente.")

# ============================================================== 9. DOWNTIME
h1("9. Misura del downtime")
p("Per quantificare esattamente quanto resta giù il servizio durante un failover, abbiamo "
  "scritto una sonda che interroga il cluster circa cinque volte al secondo usando un client "
  "in modalità cluster, capace di seguire i reindirizzamenti e quindi di riconoscere il nuovo "
  "master appena promosso. A differenza del generatore di carico, questa sonda non resta "
  "bloccata sulla vecchia topologia e si riprende non appena il cluster torna operativo, "
  "permettendo di leggere la durata esatta dell'interruzione.")
p("La sonda registra, istante per istante, se il servizio risponde oppure no per una chiave "
  "appartenente allo shard che viene fatto cadere. Il grafico mostra la disponibilità nel "
  "tempo: parte dal 100%, scende a zero nel momento dell'arresto del master, e risale al 100% "
  "quando la replica viene promossa. La finestra evidenziata è il downtime misurato.")
img(REDIS / "expF_downtime.png", caption="Disponibilità del servizio nel tempo: la finestra rossa è la durata dell'interruzione (downtime) durante il failover.")

# ============================================================== 10. RIEPILOGO OPERAZIONI
h1("10. Riepilogo degli esperimenti")
p("La tabella raccoglie tutte le prove eseguite, con lo scopo di ciascuna e l'esito.")
table(["Esperimento", "Cosa misura", "Esito"],
      [["Benchmark applicativo", "dove cede il sistema con/senza cache e repliche",
        "il collo di bottiglia si sposta dal database al backend"],
       ["Scaling richieste (A)", "throughput vs carico, nodi fissi",
        "cresce fino a ~2,4 M ops/s, poi satura (limite client)"],
       ["Scaling nodi - throughput (B)", "throughput vs numero di nodi",
        "piatto, perché il limite è il generatore, non il cluster"],
       ["Scaling nodi - capacità (D)", "chiavi cachate vs numero di nodi",
        "scaling lineare: 1×, 2×, 3×"],
       ["Failover senza repliche (C)", "effetto della caduta di un master",
        "cluster bloccato, servizio azzerato fino al riavvio"],
       ["Failover con repliche (E)", "caduta di un master con replica",
        "promozione automatica, cluster di nuovo operativo"],
       ["Misura downtime (F)", "durata esatta dell'interruzione",
        "interruzione di pochi secondi, poi ripresa"]])

# ============================================================== 11. CONCLUSIONI
h1("11. Conclusioni")
p("Mettendo insieme i risultati, il quadro è coerente. Sul piano applicativo la cache è "
  "decisiva e sposta il collo di bottiglia: senza cache il limite è il database, con la cache "
  "e le repliche di lettura il limite diventa la CPU del backend. In nessuno dei casi "
  "misurati Redis è il fattore limitante, ed è la ragione per cui, per valutarne la "
  "scalabilità, lo abbiamo sollecitato direttamente.")
p("Sul piano del cluster distribuito, la scalabilità con le richieste mostra una curva che "
  "cresce fino a saturare, ma il tetto osservato (circa 2 milioni di operazioni al secondo) è "
  "imposto dal generatore di carico, non dal cluster: un singolo nodo Redis è più veloce di "
  "quanto l'hardware client a disposizione riesca a sollecitarlo. La scalabilità con i nodi è "
  "invece pienamente visibile sulla dimensione della capacità, dove cresce in modo lineare "
  "grazie allo sharding. Infine, sul fronte della resilienza, senza repliche la caduta di un "
  "nodo blocca l'intero cluster fino al ripristino manuale, mentre con le repliche una copia "
  "viene promossa automaticamente e il servizio riprende in pochi secondi.")
p("In sintesi, Redis distribuito scala bene in capacità e distribuisce il carico tra i nodi, "
  "mentre la sua altissima velocità per singolo nodo fa sì che, con risorse client limitate, "
  "il throughput non sia il parametro che evidenzia lo scaling. La resilienza dipende dalla "
  "presenza di repliche: senza, un guasto è bloccante; con repliche, è gestito in modo "
  "trasparente, al costo di raddoppiare i nodi.")

doc.save(OUT)
print(f"Documento creato: {OUT}")
