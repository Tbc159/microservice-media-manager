#!/usr/bin/env bash
# =============================================================================
#  Bootstrap PARAMETRICO di un repo GitHub con la metodologia contract-first
#  multi-ambiente (branch d'ambiente + Environments + branch protection).
#
#  Esegui DA DENTRO la cartella del progetto, con la GitHub CLI autenticata:
#     gh auth login
#     ./bootstrap-github.sh                  # usa i default (vedi --help)
#     ./bootstrap-github.sh -r altro-repo -v public
#     ./bootstrap-github.sh --dry-run        # mostra solo il piano
#
#  Ogni parametro ha un default ed è impostabile via flag o via variabile
#  d'ambiente omonima (es. VISIBILITY=public ./bootstrap-github.sh).
#
#  REQUISITI DI PIANO (repo PRIVATO):
#   - Environment + secret + deployment branch policy : GitHub Pro/Team/Enterprise
#   - Required reviewers sull'environment              : SOLO Enterprise (su privato)
#   - Branch protection                                : GitHub Pro/Team/Enterprise
#  Su piani inferiori i relativi step stampano un WARNING e proseguono. Il gate di
#  produzione resta garantito dalla branch protection del default branch.
# =============================================================================
set -uo pipefail

# ---- Default (overridabili via flag o variabile d'ambiente) ----
REPO="${REPO:-$(basename "$PWD")}"
OWNER="${OWNER:-}"                                   # vuoto -> utente gh autenticato
VISIBILITY="${VISIBILITY:-private}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
ENV_MAP="${ENV_MAP:-develop:staging,coll:collaudo,main:production}"
SECRETS="${SECRETS:-API_HOST,API_KEY,API_SECRET}"
HOST_SECRET="${HOST_SECRET:-API_HOST}"              # questo secret riceve l'URL host
# NB: il default contiene graffe -> non usare ${VAR:-...} (la "}" chiuderebbe l'espansione)
HOST_TEMPLATE="${HOST_TEMPLATE:-}"
[ -n "$HOST_TEMPLATE" ] || HOST_TEMPLATE='https://{env}.{repo}.local'
REQUIRED_REVIEWS="${REQUIRED_REVIEWS:-1}"
PROD_ENV="${PROD_ENV:-}"                             # vuoto -> env del default branch
FEATURE_BRANCH="${FEATURE_BRANCH:-feature/example}"  # "" oppure --no-feature per saltarlo
DRY_RUN=""

usage(){ cat <<EOF
Bootstrap parametrico di un repo GitHub (metodologia contract-first multi-ambiente).

Uso: $0 [opzioni]
  -r, --repo NOME           nome repo            (default: cartella corrente "$REPO")
  -o, --owner LOGIN         owner                (default: utente gh autenticato)
  -v, --visibility V        private|public       (default: $VISIBILITY)
  -b, --default-branch B    branch di default    (default: $DEFAULT_BRANCH)
  -e, --env-map SPEC        branch:env,...       (default: $ENV_MAP)
  -s, --secrets CSV         secret per ambiente  (default: $SECRETS)
      --host-secret NOME    secret con URL host  (default: $HOST_SECRET)
      --host-template T     template, {env}/{repo} (default: $HOST_TEMPLATE)
      --reviews N           review richieste     (default: $REQUIRED_REVIEWS)
      --prod-env ENV        env con required reviewers (default: env del default branch)
  -f, --feature BRANCH      branch feature di prova (default: $FEATURE_BRANCH)
      --no-feature          non creare il branch di prova
  -n, --dry-run             stampa il piano ed esce, senza eseguire nulla
  -h, --help                questo aiuto

Esempi:
  $0                                  # default, sul repo = cartella corrente
  $0 -r social-service -v public
  $0 -e "dev:staging,main:production" --reviews 2
  VISIBILITY=public $0 --dry-run
EOF
}

# ---- Parsing argomenti ----
while [ $# -gt 0 ]; do
  case "$1" in
    -r|--repo)           REPO="$2"; shift 2;;
    -o|--owner)          OWNER="$2"; shift 2;;
    -v|--visibility)     VISIBILITY="$2"; shift 2;;
    -b|--default-branch) DEFAULT_BRANCH="$2"; shift 2;;
    -e|--env-map)        ENV_MAP="$2"; shift 2;;
    -s|--secrets)        SECRETS="$2"; shift 2;;
    --host-secret)       HOST_SECRET="$2"; shift 2;;
    --host-template)     HOST_TEMPLATE="$2"; shift 2;;
    --reviews)           REQUIRED_REVIEWS="$2"; shift 2;;
    --prod-env)          PROD_ENV="$2"; shift 2;;
    -f|--feature)        FEATURE_BRANCH="$2"; shift 2;;
    --no-feature)        FEATURE_BRANCH=""; shift;;
    -n|--dry-run)        DRY_RUN=1; shift;;
    -h|--help)           usage; exit 0;;
    *) echo "Opzione sconosciuta: $1" >&2; usage; exit 2;;
  esac
done

warn(){ echo "WARNING  $*" >&2; }
info(){ echo ">>> $*"; }

command -v gh  >/dev/null || { echo "gh CLI non trovata: https://cli.github.com"; exit 1; }
command -v git >/dev/null || { echo "git non trovato"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Non sei autenticato. Esegui: gh auth login"; exit 1; }

[ -n "$OWNER" ] || OWNER="$(gh api user --jq .login)"
SLUG="$OWNER/$REPO"

# ---- Parsing env-map -> branch ordinati + mappa branch->env ----
ENV_BRANCHES=(); declare -A ENV_OF=()
IFS=',' read -ra _pairs <<< "$ENV_MAP"
for p in "${_pairs[@]}"; do
  case "$p" in *:*) ;; *) echo "env-map non valido: '$p' (atteso branch:env)"; exit 2;; esac
  br="${p%%:*}"; en="${p##*:}"
  [ -n "$br" ] && [ -n "$en" ] || { echo "env-map non valido: '$p' (atteso branch:env)"; exit 2; }
  ENV_BRANCHES+=("$br"); ENV_OF["$br"]="$en"
done
[ "${#ENV_BRANCHES[@]}" -gt 0 ] || { echo "env-map vuoto"; exit 2; }
[ -n "$PROD_ENV" ] || PROD_ENV="${ENV_OF[$DEFAULT_BRANCH]:-}"
IFS=',' read -ra SECRET_LIST <<< "$SECRETS"

# ---- Piano ----
echo "================= PIANO BOOTSTRAP ================="
echo "  Owner / Repo   : $SLUG"
echo "  Visibilita'    : $VISIBILITY"
echo "  Default branch : $DEFAULT_BRANCH"
echo "  Ambienti       :"
for b in "${ENV_BRANCHES[@]}"; do
  tag=""; [ "$b" = "$DEFAULT_BRANCH" ] && tag=" [default]"
  [ "${ENV_OF[$b]}" = "$PROD_ENV" ] && tag="$tag [required reviewers]"
  printf "     %-12s -> %s%s\n" "$b" "${ENV_OF[$b]}" "$tag"
done
echo "  Secret / env   : ${SECRET_LIST[*]}   (host '$HOST_SECRET' = $HOST_TEMPLATE)"
echo "  Branch protect : $REQUIRED_REVIEWS review su [${ENV_BRANCHES[*]}]"
echo "  Feature test   : ${FEATURE_BRANCH:-<nessuno>}"
echo "=================================================="
[ -n "$DRY_RUN" ] && { info "dry-run: nessuna azione eseguita."; exit 0; }

# ---- 1. Repo + primo push del default branch ----
if gh repo view "$SLUG" >/dev/null 2>&1; then
  warn "Repo $SLUG gia' esistente: salto la creazione."
else
  [ -d .git ] || git init -q
  git checkout -q -B "$DEFAULT_BRANCH"
  git add .
  git -c user.email=bootstrap@local -c user.name=bootstrap \
      commit -qm "chore: bootstrap contract-first microservice" || true
  gh repo create "$SLUG" --"$VISIBILITY" --source . --remote origin --push
fi

# ---- 2. Branch d'ambiente (tutti tranne il default) a partire dal default ----
git fetch origin -q || true
for b in "${ENV_BRANCHES[@]}"; do
  [ "$b" = "$DEFAULT_BRANCH" ] && continue
  if git show-ref --verify --quiet "refs/heads/$b"; then
    git checkout -q "$b"
  else
    git checkout -q -b "$b" "$DEFAULT_BRANCH"
  fi
  git push -u origin "$b" 2>/dev/null || warn "push $b non riuscito (forse gia' presente)"
done
git checkout -q "$DEFAULT_BRANCH"

# ---- 3. Environments + deployment branch policy + secret (Pro+ su privato) ----
USER_ID="$(gh api user --jq .id)"
for b in "${ENV_BRANCHES[@]}"; do
  env="${ENV_OF[$b]}"
  info "Environment '$env' (branch '$b')"

  if [ "$env" = "$PROD_ENV" ]; then
    BODY=$(printf '{"reviewers":[{"type":"User","id":%s}],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' "$USER_ID")
  else
    BODY='{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}'
  fi
  echo "$BODY" | gh api --method PUT "repos/$SLUG/environments/$env" --input - >/dev/null 2>&1 \
    || warn "Environment '$env' non creato (richiede Pro/Team/Enterprise su repo privato)."

  gh api --method POST "repos/$SLUG/environments/$env/deployment-branch-policies" \
    -f name="$b" >/dev/null 2>&1 \
    || warn "Branch policy '$b' su '$env' non impostata (limite di piano?)."

  for s in "${SECRET_LIST[@]}"; do
    if [ "$s" = "$HOST_SECRET" ]; then
      val="${HOST_TEMPLATE//\{env\}/$env}"; val="${val//\{repo\}/$REPO}"
    else
      val="REPLACE_ME"
    fi
    gh secret set "$s" --env "$env" --repo "$SLUG" --body "$val" >/dev/null 2>&1 \
      || warn "Secret $s/$env non impostato (gli environment secret su privato richiedono Pro+)."
  done
done

# ---- 4. Branch protection su tutti i branch d'ambiente (Pro+ su privato) ----
PROT=$(printf '{"required_status_checks":null,"enforce_admins":false,"required_pull_request_reviews":{"required_approving_review_count":%s},"restrictions":null}' "$REQUIRED_REVIEWS")
for b in "${ENV_BRANCHES[@]}"; do
  echo "$PROT" | gh api --method PUT "repos/$SLUG/branches/$b/protection" --input - >/dev/null 2>&1 \
    && info "Branch protection attiva su '$b' ($REQUIRED_REVIEWS review)" \
    || warn "Branch protection su '$b' non applicata (richiede Pro/Team/Enterprise su repo privato)."
done

# ---- 5. Default branch + feature di prova (opzionale) ----
gh repo edit "$SLUG" --default-branch "$DEFAULT_BRANCH" >/dev/null 2>&1 || true
if [ -n "$FEATURE_BRANCH" ]; then
  git checkout -q -b "$FEATURE_BRANCH" "$DEFAULT_BRANCH" 2>/dev/null || git checkout -q "$FEATURE_BRANCH"
  git push -u origin "$FEATURE_BRANCH" 2>/dev/null || warn "push $FEATURE_BRANCH non riuscito"
  git checkout -q "$DEFAULT_BRANCH"
fi

echo
info "FATTO ($SLUG). Prossimi passi per il test funzionale:"
echo "  1) Modifica il contratto OAS su '$FEATURE_BRANCH' -> osserva il workflow di scaffold."
echo "  2) Apri una PR '$FEATURE_BRANCH' -> '${ENV_BRANCHES[0]}'  : parte la CI (no deploy)."
echo "  3) Merge della PR                                        : deploy sull'ambiente del branch."
echo "  4) PR di promozione tra branch d'ambiente                : avanzamento tra ambienti."
echo "  5) Sostituisci i secret placeholder (REPLACE_ME) con i valori reali negli Environment."
