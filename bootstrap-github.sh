#!/usr/bin/env bash
# =============================================================================
#  Bootstrap di microservice-media-manager su GitHub
#  Esegui DA DENTRO questa cartella, con la GitHub CLI gia' autenticata:
#     gh auth login        # se non lo sei
#     ./bootstrap-github.sh
#
#  REQUISITI DI PIANO (repo PRIVATO):
#   - Environment + secret + deployment branch policy : GitHub Pro/Team/Enterprise
#   - Required reviewers sull'environment              : SOLO Enterprise (su privato)
#   - Branch protection                                : GitHub Pro/Team/Enterprise
#  Su piani inferiori i relativi step stamperanno un WARNING e proseguiranno.
#  Il gate di produzione e' comunque garantito dalla branch protection di `main`
#  (review obbligatoria sul merge => blocca il deploy che parte sul push a main).
# =============================================================================
set -uo pipefail

REPO="microservice-media-manager"
VISIBILITY="private"            # scelto: privato
DEFAULT_BRANCH="main"
ENV_BRANCHES=("develop" "coll" "main")
declare -A ENV_OF=( [develop]="staging" [coll]="collaudo" [main]="production" )

warn(){ echo "WARNING  $*" >&2; }
info(){ echo ">>> $*"; }

command -v gh >/dev/null || { echo "gh CLI non trovata. Installa: https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Non sei autenticato. Esegui: gh auth login"; exit 1; }

OWNER="$(gh api user --jq .login)"
SLUG="$OWNER/$REPO"
info "Owner: $OWNER  |  Repo: $SLUG  |  Visibilita': $VISIBILITY"

# --- 1. Repo + primo push di main ---
if gh repo view "$SLUG" >/dev/null 2>&1; then
  warn "Repo $SLUG gia' esistente: salto la creazione."
else
  git init -q
  git checkout -q -b "$DEFAULT_BRANCH"
  git add .
  git -c user.email=bootstrap@local -c user.name=bootstrap commit -qm "chore: bootstrap contract-first microservice" || true
  gh repo create "$SLUG" --"$VISIBILITY" --source . --remote origin --push
fi

# --- 2. Branch d'ambiente develop e coll (a partire da main) ---
git fetch origin -q || true
for b in develop coll; do
  if git show-ref --verify --quiet "refs/heads/$b"; then
    git checkout -q "$b"
  else
    git checkout -q -b "$b" "$DEFAULT_BRANCH"
  fi
  git push -u origin "$b" 2>/dev/null || warn "push $b non riuscito (forse gia' presente)"
done
git checkout -q "$DEFAULT_BRANCH"

# --- 3. Environments + deployment branch policy + secret (Pro+ su privato) ---
USER_ID="$(gh api user --jq .id)"
for b in "${ENV_BRANCHES[@]}"; do
  env="${ENV_OF[$b]}"
  info "Environment '$env' (branch '$b')"

  # required reviewers solo per production (e solo se Enterprise lo consente)
  if [ "$env" = "production" ]; then
    BODY=$(printf '{"reviewers":[{"type":"User","id":%s}],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' "$USER_ID")
  else
    BODY='{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}'
  fi
  echo "$BODY" | gh api --method PUT "repos/$SLUG/environments/$env" --input - >/dev/null 2>&1 \
    || warn "Environment '$env' non creato (richiede Pro/Team/Enterprise su repo privato)."

  # deployment branch policy: solo il branch corrispondente puo' deployare
  gh api --method POST "repos/$SLUG/environments/$env/deployment-branch-policies" \
    -f name="$b" >/dev/null 2>&1 \
    || warn "Branch policy '$b' su '$env' non impostata (limite di piano?)."

  # secret placeholder per ambiente (DA SOSTITUIRE)
  for s in API_HOST API_KEY API_SECRET; do
    val="REPLACE_ME"; [ "$s" = "API_HOST" ] && val="https://$env.media-manager.local"
    gh secret set "$s" --env "$env" --repo "$SLUG" --body "$val" >/dev/null 2>&1 \
      || warn "Secret $s/$env non impostato (gli environment secret su privato richiedono Pro+)."
  done
done

# --- 4. Branch protection su tutti i branch d'ambiente (Pro+ su privato) ---
for b in "${ENV_BRANCHES[@]}"; do
  cat <<JSON | gh api --method PUT "repos/$SLUG/branches/$b/protection" --input - >/dev/null 2>&1 \
    && info "Branch protection attiva su '$b'" \
    || warn "Branch protection su '$b' non applicata (richiede Pro/Team/Enterprise su repo privato)."
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "restrictions": null
}
JSON
done

# --- 5. Branch di default + feature di prova per testare il processo ---
gh repo edit "$SLUG" --default-branch "$DEFAULT_BRANCH" >/dev/null 2>&1 || true
git checkout -q -b feature/list-all-media "$DEFAULT_BRANCH" 2>/dev/null || git checkout -q feature/list-all-media
git push -u origin feature/list-all-media 2>/dev/null || warn "push feature/list-all-media non riuscito"
git checkout -q "$DEFAULT_BRANCH"

echo
info "FATTO. Prossimi passi per il test funzionale:"
echo "  1) Modifica openapi/api.yaml su feature/list-all-media -> osserva il workflow 'API Draft'."
echo "  2) Apri una PR feature/list-all-media -> develop  : parte la CI (no deploy)."
echo "  3) Merge della PR                                 : parte 'Generate & Deploy' su staging."
echo "  4) PR di promozione develop -> coll -> main       : avanzamento tra ambienti."
echo "  5) Sostituisci i secret placeholder negli Environment (API_KEY/API_SECRET reali)."
