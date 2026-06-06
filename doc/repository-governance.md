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

> **Percorso pianificato** per il futuro (lo step immediato è "solo documentazione", la branch
> protection resta invariata). Qui il dettaglio operativo per quando si procederà.

Un secondo utente GitHub con accesso **write** può **approvare** le PR di `Tbc159`, soddisfacendo la
regola senza bypass. È il vero "sviluppo condiviso".

Punto chiave: il validatore è un **utente esterno e indipendente**. L'onboarding è a **due lati** —
l'owner manda l'invito, ma l'account del validatore **non è gestito dall'owner**: accetta e
approva in autonomia. L'owner non ha (e non deve avere) le credenziali del validatore.

### Lato owner (`Tbc159`) — invito e ruolo

1. **Invitare** il validatore (UI: *Settings → Collaborators → Add people*; oppure API):
   ```bash
   gh api -X PUT repos/Tbc159/microservice-media-manager/collaborators/<USERNAME_VALIDATORE> \
     -f permission=push        # push = write (minimo perché l'approvazione conti)
   ```
2. L'owner **non può** accettare l'invito al posto del validatore: l'azione è sul suo account.
3. L'owner può in qualsiasi momento **revocare** l'accesso (*Settings → Collaborators → Remove*) o
   cambiare il ruolo. È l'unica leva che ha sul validatore: l'invito e la sua revoca.

### Lato validatore esterno (sul **proprio** account)

1. Riceve la notifica/email d'invito, oppure va su
   `https://github.com/Tbc159/microservice-media-manager/invitations`.
2. **Accetta** l'invito (solo lui può farlo).
3. Per validare una PR: apre *Files changed → Review changes → **Approve***. Con un'approvazione di
   un utente **write**, il gate è soddisfatto e il merge non richiede forzatura.
4. Buone pratiche **a sua discrezione** (l'owner non le impone): 2FA attiva sul proprio account.

### Separazione degli account e fiducia

- L'owner controlla **solo** invito, ruolo e revoca; **non** ha accesso all'account del validatore.
- Il validatore agisce in autonomia; non condivide credenziali con l'owner.
- **Minimo privilegio:** ruolo **write**, mai `admin`. Nota: su un repo personale, `write` è il
  livello minimo perché un'approvazione *conti* ai fini della regola, ma `write` consente anche il
  push diretto. La branch protection impone comunque il passaggio da PR; se si vuole vietare i push
  diretti, va aggiunta una regola che li blocchi (su repo personali GitHub non offre un ruolo
  "solo-review" che soddisfi i required reviews — quella granularità esiste nelle organizzazioni).
- Se in futuro servisse separare meglio i ruoli (review senza write, team di validatori), valutare
  la migrazione del repo sotto una **organizzazione** GitHub.

### Ruoli a confronto

| Ruolo | Approvazione conta? | Push / merge | Gestisce settings |
|-------|---------------------|--------------|-------------------|
| `pull` (read) | ❌ | ❌ | ❌ |
| `triage` | ❌ | ❌ | ❌ |
| `push` (write) | ✅ | ✅ | ❌ |
| `maintain` | ✅ | ✅ | parziale |
| `admin` | ✅ | ✅ | ✅ |

Per un validatore esterno: **`push` (write)**, revocabile in qualsiasi momento.

## Decisione attuale e percorso

**Stato (2026-06-05):** nessuna modifica applicata alla branch protection — si resta col bypass
admin per ora (scelta: *solo documentazione*). Le regole restano com'erano.

**Percorso pianificato:** introdurre un **validatore esterno** (Soluzione B), tenendo presente che
è un account indipendente non gestito dall'owner. A quel punto il gate review sarà soddisfacibile
senza forzatura.

**Opzioni ancora disponibili quando si vorrà agire:**
1. Relax di `develop` e `coll` (Soluzione A) → l'owner lavora senza bypass negli ambienti di
   iterazione, tenendo il gate solo su `main`.
2. Validatore esterno con write (Soluzione B) + eventuale `required_status_checks` +
   `enforce_admins=true` su `main` per un gate di produzione reale.
3. Valutare di rendere il **repo privato**: i self-hosted runner su repo pubblici sono un rischio
   di sicurezza.

Queste modifiche toccano la governance del repo: vanno applicate con consapevolezza dell'owner
(non sono parte del deploy automatico).
