# Redis Cluster — setup e benchmark

Cluster Redis a 3 master (sharding puro, niente repliche) distribuito su VM-1/2/3,
per misurare la scalabilità di Redis come richiesto dal professore:
1. scaling all'aumentare delle richieste a parità di nodi  → **exp_A_load.sh**
2. scaling a parità di richieste all'aumentare dei nodi    → **exp_B_nodes.sh**
3. comportamento al fallimento di un nodo                  → **exp_C_failover.sh**

Il carico è generato con `memtier_benchmark` da Worker-1 (nodo separato dal
cluster, come da best practice ufficiale Redis). I test colpiscono Redis
direttamente, **senza passare da FastAPI**: a livello applicativo il bottleneck
è la CPU del backend (~1480 RPS) e Redis non saturerebbe mai, quindi per
misurare la scalabilità di Redis lo si stressa direttamente.

## Topologia (IP reali)

```
Worker-1  10.0.1.7  (D16)   memtier_benchmark  (load generator)
VM-1      10.0.1.5  (D4)    nodo Redis cluster
VM-2      10.0.1.4  (D4)    nodo Redis cluster
VM-3      10.0.1.8  (D4)    nodo Redis cluster
VM-4      10.0.1.6  (D4)    PostgreSQL  (non coinvolto nei test memtier)
```

Per tutti gli script: `NODES="10.0.1.5 10.0.1.4 10.0.1.8"`.

## Prerequisiti di rete

Nel NSG Azure, tra VM-1/2/3 devono essere aperte:
- **6379** — porta dati Redis
- **16379** — porta bus del cluster (gossip). Senza, il cluster non si forma.

## File

| File | Ruolo |
|---|---|
| `docker-compose.redis-node.yml` | un nodo Redis in cluster mode (host network) |
| `setup-node.sh` | avvia il nodo su una VM (auto-rileva l'IP) |
| `create-cluster.sh` | forma il cluster a 3 nodi (`redis-cli --cluster create`) |
| `cluster-reshape.sh` | riforma il cluster a N=1/2/3 nodi (per exp B) |
| `run-memtier.sh` | wrapper parametrico di memtier |
| `exp_A_load.sh` | esperimento A — throughput vs carico |
| `exp_B_nodes.sh` | esperimento B — throughput vs nodi |
| `exp_C_failover.sh` | esperimento C — fallimento di un nodo |
| `../../plot_redis.py` | grafici dei 3 esperimenti |

## Procedura completa

### 1. Su OGNI nodo (VM-1, VM-2, VM-3)
```bash
cd ~/AD-2526 && git pull
docker compose -f docker-compose.replica.yml down 2>/dev/null || true  # libera dalle repliche Postgres
bash infra/redis-cluster/setup-node.sh
```
`setup-node.sh` rileva da solo l'IP privato e lo usa come `cluster-announce-ip`.

### 2. Da Worker-1 — forma il cluster
```bash
cd ~/AD-2526 && git pull
NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/create-cluster.sh
```
Atteso: `cluster_state:ok`, `cluster_known_nodes:3`, `cluster_size:3`.

### 3. Verifica da qualsiasi nodo
```bash
docker exec ad2526-redis-cluster redis-cli -c cluster info
docker exec ad2526-redis-cluster redis-cli -c cluster nodes
```

### 4. Esperimenti (da Worker-1)
```bash
# B — scaling con i nodi (la risposta più diretta al prof)
NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/exp_B_nodes.sh

# A — scaling con il carico (ricostruisci prima il cluster a 3 nodi)
NODES="10.0.1.5 10.0.1.4 10.0.1.8" bash infra/redis-cluster/create-cluster.sh
SEED_IP=10.0.1.5 bash infra/redis-cluster/exp_A_load.sh

# C — failover (uccide VM-2 a metà run)
NODES="10.0.1.5 10.0.1.4 10.0.1.8" KILL_NODE=10.0.1.4 \
  bash infra/redis-cluster/exp_C_failover.sh
# ripristino nodo: ssh Karzaladmin@10.0.1.4 'docker start ad2526-redis-cluster'
```

### 5. Grafici (da Windows, dopo aver scaricato results/redis)
```powershell
py plot_redis.py results/redis
```

## Note

- `network_mode: host` è necessario per un cluster cross-VM con Docker.
- Persistenza disabilitata (`--appendonly no --save ""`): è una cache.
- `maxmemory-policy allkeys-lru`: eviction LRU per l'eventuale test di capacità.
- **exp_B** usa `cluster-reshape.sh` (non `create-cluster.sh`) perché deve creare
  cluster da 1 e 2 nodi, che `redis-cli --cluster create` rifiuta (vuole min 3):
  lo fa con `CLUSTER MEET` + `ADDSLOTSRANGE`.
- Se in exp_B il throughput è già piatto da 1 nodo, è il **client** a saturare:
  alza `--threads` o lancia memtier da più nodi in parallelo.
