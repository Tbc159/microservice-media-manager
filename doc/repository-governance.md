# Governance del repository: permessi, review, validatori

Come sono configurati accessi e gate di merge, perché oggi serve la "forzatura" admin, e come
risolverlo (relax delle regole o validatore esterno).

## Situazione attuale (rilevata 2026-06-05)

| Aspetto | Valore |
|---------|--------|
| Owner | `Tbc159` (account utente, non organizzazione) |
| Visibilità | **pubblico** |
| Permesso di `Tbc159` | **admin** (`admin: true`) — pieno controllo |
| Collaboratori | solo `Tbc159` |
| Branch protetti | `develop`, `coll`, `main` |
| Regola su ciascuno | **1 review approvante richiesta**, `enforce_admins=false`, nessun required status check |

## Il problema non sono i permessi

`Tbc159` **è già admin**: il pieno controllo c'è. Il vero ostacolo è una combinazione:

1. la branch protection richiede **1 approvazione** prima del merge;
2. **GitHub non consente di approvare le proprie PR**;
3. essendo `Tbc159` l'**unico** collaboratore, quell'approvazione non è mai ottenibile.

Con `enforce_admins=false`, l'admin può **bypassare** la regola (la "forzatura" spuntata in fase di
merge): è il workaround attuale, ma sporco e non è "operare con i giusti privilegi".

> Nota tecnica: perché un'approvazione **conti** ai fini della regola, il revisore deve avere
> accesso **write** (o superiore). Le review di chi ha solo lettura non soddisfano il requisito.

## Soluzione A — Allineare le regole alla strategia di branching (consigliata)

La strategia documentata prevede il **gate reviewer solo su `main`** (produzione). Quindi:

- **`develop` e `coll`**: rimuovere la review obbligatoria → l'owner mergia le proprie PR senza
  bypass. La CI (`ci.yaml`) resta il gate automatico.
- **`main`**: mantenere 1 review + aggiungere un **validatore esterno** (sotto), così il gate è
  soddisfacibile senza bypass.

Rimuovere la review obbligatoria su un branch (mantenendo il resto della protezione):
```bash
gh api -X DELETE \
  repos/Tbc159/microservice-media-manager/branches/develop/protection/required_pull_request_reviews
# idem per 'coll'
```

Hardening consigliato su `main` (rendere la CI un gate di merge):
```bash
gh api -X PATCH repos/Tbc159/microservice-media-manager/branches/main/protection/required_status_checks \
  -f strict=true -f 'contexts[]=validate-and-test'
# opzionale: enforce_admins=true per vietare il bypass anche all'owner in produzione
gh api -X POST repos/Tbc159/microservice-media-manager/branches/main/protection/enforce_admins
```

## Soluzione B — Aggiungere un validatore esterno

Un secondo utente GitHub con accesso **write** (o **maintain**) può **approvare** le PR di
`Tbc159`, soddisfacendo la regola senza bypass. È il vero "sviluppo condiviso".

### Passi

1. **Invitare il validatore** (ruolo minimo `push`/write; `maintain` se deve anche gestire alcune
   impostazioni — evitare `admin` per il principio del minimo privilegio):
   ```bash
   gh api -X PUT repos/Tbc159/microservice-media-manager/collaborators/<USERNAME> \
     -f permission=push        # push=write | maintain | triage | pull
   ```
   In alternativa via UI: *Settings → Collaborators → Add people*.
2. **Il validatore accetta l'invito** (email o `https://github.com/Tbc159/microservice-media-manager/invitations`).
3. **Flusso di review**: su una PR il validatore apre *Files changed → Review changes → Approve*.
   Con almeno un'approvazione di un utente write, il gate è soddisfatto e il merge non richiede
   forzatura.

### Ruoli a confronto

| Ruolo | Può approvare PR (conta)? | Può mergiare/push | Gestisce settings |
|-------|---------------------------|-------------------|-------------------|
| `pull` (read) | ❌ (review non conta) | ❌ | ❌ |
| `triage` | ❌ | ❌ | ❌ |
| `push` (write) | ✅ | ✅ | ❌ |
| `maintain` | ✅ | ✅ | parziale |
| `admin` | ✅ | ✅ | ✅ |

Per un validatore esterno: **`push` (write)** è sufficiente; `maintain` se serve gestione parziale.

## Raccomandazione operativa

1. Relax di `develop` e `coll` (Soluzione A) → l'owner lavora senza bypass nei due ambienti di
   iterazione.
2. `main` resta gated: aggiungere un **validatore esterno** con write (Soluzione B) e, idealmente,
   `required_status_checks` + `enforce_admins=true` per un gate di produzione reale.
3. Valutare di rendere il **repo privato**: i self-hosted runner su repo pubblici sono un rischio
   di sicurezza (vedi [pipeline.md](pipeline.md)).

Queste modifiche toccano la governance del repo: vanno applicate con consapevolezza dell'owner
(non sono parte del deploy automatico).
