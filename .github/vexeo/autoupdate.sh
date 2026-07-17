#!/usr/bin/env bash
# Auto-actualización del fork VEXEO Soporte Remoto.
#
# Detecta la última release de rustdesk/rustdesk; si es más nueva que la base
# de nuestra última release (o si FORCE=true), reconstruye el árbol branded
# desde el tag limpio de upstream con vexeo-kit.py, crea un commit-snapshot
# sobre master, lo taggea y lo publica. El push del tag dispara flutter-tag.yml
# (build + release) y vexeo-release-finalize.yml marca la release como latest.
#
# Convención de tags del fork: SIEMPRE X.Y.Z-N (N de 1 a 9), nunca el nombre
# limpio de upstream — así nunca colisionan y el cliente en la base X.Y.Z
# siempre ve la primera build X.Y.Z-1 como update.
#
# Entorno:
#   VEXEO_PAT  (solo CI) token con Contents:RW + Workflows:RW en
#              jesusfromero/rustdesk y Contents:RW en jesusfromero/hbb_common.
#              En local no hace falta: se usan tus credenciales de git/gh.
#   FORCE=true rebuild aunque no haya versión upstream nueva (sube sufijo -N).
set -euo pipefail

UPSTREAM_REPO="rustdesk/rustdesk"
FORK_REPO="jesusfromero/rustdesk"
HBB_UPSTREAM="https://github.com/rustdesk/hbb_common"
HBB_FORK_REPO="jesusfromero/hbb_common"
FORCE="${FORCE:-false}"

# Identidad git explícita: los commit-tree corren en repos sin config global
# (runner de CI y clone temporal de hbb_common).
export GIT_AUTHOR_NAME="vexeo-autoupdate" GIT_AUTHOR_EMAIL="soporte@vexeo.digital"
export GIT_COMMITTER_NAME="vexeo-autoupdate" GIT_COMMITTER_EMAIL="soporte@vexeo.digital"

if [[ -n "${VEXEO_PAT:-}" ]]; then
    HBB_FORK_URL="https://x-access-token:${VEXEO_PAT}@github.com/${HBB_FORK_REPO}.git"
else
    HBB_FORK_URL="https://github.com/${HBB_FORK_REPO}.git"
fi

HBB_DIR=""; KIT_TMP=""
# `return 0` al final es obligatorio: si no, cuando el script sale temprano
# (HBB_DIR/KIT_TMP vacíos) la última prueba `[[ -n "" ]]` devuelve 1 y ese
# código se convierte en la salida del script aunque hiciéramos `exit 0`.
cleanup() { [[ -n "$HBB_DIR" ]] && rm -rf "$HBB_DIR"; [[ -n "$KIT_TMP" ]] && rm -rf "$KIT_TMP"; return 0; }
trap cleanup EXIT

# Exige working tree limpio (protege ejecuciones locales: el flujo hace
# checkout --detach y git add -A).
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: working tree sucio. Ejecuta sobre un clon limpio." >&2
    exit 1
fi

semver_max() { grep -E '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9]+)?$' | sort -V | tail -1; }

echo "== Detectando versiones =="
UPSTREAM_TAG=$(gh api "repos/$UPSTREAM_REPO/releases/latest" --jq .tag_name)
[[ "$UPSTREAM_TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Tag upstream inesperado: $UPSTREAM_TAG"; exit 1; }

# Lista de releases del fork, distinguiendo lista-vacía de error de API.
if ! OUR_RAW=$(gh api "repos/$FORK_REPO/releases?per_page=100" --jq '.[].tag_name' 2>/tmp/gherr); then
    if grep -qi 'Not Found' /tmp/gherr; then OUR_RAW=""; else
        echo "ERROR consultando releases del fork:" >&2; cat /tmp/gherr >&2; exit 1; fi
fi
OUR_RELEASES=$(echo "$OUR_RAW" | semver_max || true)   # la de versión más alta
OUR_LATEST="$OUR_RELEASES"
OUR_BASE="${OUR_LATEST%-*}"
echo "upstream: $UPSTREAM_TAG | nuestra última: ${OUR_LATEST:-ninguna} (base ${OUR_BASE:-n/a})"

if [[ "$UPSTREAM_TAG" == "$OUR_BASE" && "$FORCE" != "true" ]]; then
    echo "Ya estamos en la base $UPSTREAM_TAG y FORCE!=true — nada que hacer."
    exit 0
fi

# Siguiente sufijo -N para esta base (todas las releases del fork llevan -N).
esc="${UPSTREAM_TAG//./\\.}"
MAX_N=0
while read -r t; do
    [[ "$t" =~ ^${esc}-([0-9]+)$ ]] || continue
    n="${BASH_REMATCH[1]}"; (( n > MAX_N )) && MAX_N=$n
done <<< "$OUR_RAW"
NEW_N=$((MAX_N + 1))
(( NEW_N <= 9 )) || { echo "Sufijo -$NEW_N > 9 rompería la comparación de versiones"; exit 1; }
NEW_VERSION="${UPSTREAM_TAG}-${NEW_N}"
echo "Nueva versión VEXEO: $NEW_VERSION"

echo "== Preparando árbol upstream $UPSTREAM_TAG =="
git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "https://github.com/$UPSTREAM_REPO"
# Fetch a un namespace propio (refs/vexeo-upstream/*) — nunca a refs/tags/,
# para no colisionar con los tags del fork ni depender de tags heredados.
git fetch -q --no-tags upstream "refs/tags/$UPSTREAM_TAG:refs/vexeo-upstream/$UPSTREAM_TAG"
UP_COMMIT=$(git rev-parse "refs/vexeo-upstream/$UPSTREAM_TAG")
HBB_PIN_UPSTREAM=$(git ls-tree "$UP_COMMIT" libs/hbb_common | awk '{print $3}')
[[ -n "$HBB_PIN_UPSTREAM" ]] || { echo "No se encontró el pin de hbb_common en $UPSTREAM_TAG"; exit 1; }
echo "commit upstream: $UP_COMMIT | pin hbb_common: $HBB_PIN_UPSTREAM"

git fetch -q origin
MASTER=$(git rev-parse origin/master)

echo "== Reconstruyendo fork de hbb_common =="
HBB_DIR=$(mktemp -d)
git clone -q "$HBB_FORK_URL" "$HBB_DIR"
pushd "$HBB_DIR" >/dev/null
git remote add up "$HBB_UPSTREAM"
git fetch -q up "$HBB_PIN_UPSTREAM"
git checkout -q --detach "$HBB_PIN_UPSTREAM"
python3 - <<'PYEOF'
import re, sys
p = "src/config.rs"
c = open(p).read()
subs = [
    (r'pub static ref APP_NAME: RwLock<String> = RwLock::new\("RustDesk"\.to_owned\(\)\);',
     'pub static ref APP_NAME: RwLock<String> = RwLock::new("VEXEO Soporte Remoto".to_owned());'),
    (r'pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[[^\]]*\];',
     'pub const RENDEZVOUS_SERVERS: &[&str] = &["rustdesk.vexeo.digital"];'),
    (r'pub const RS_PUB_KEY: &str = "[^"]*";',
     'pub const RS_PUB_KEY: &str = "O7Lw+QX9oN5xKNjSTwO5B5LspsbO7zXPCuBSP0hUIqk=";'),
    # ORG: se usa en get_full_name() = ORG.APP_NAME → nombra los .plist del
    # servicio y la carpeta de config. El kit cambia a la vez el prefijo
    # com.carriez.RustDesk de los scripts; si se toca uno sin el otro, el
    # instalador escribiría un .plist con nombre distinto al que se comprueba.
    (r'pub static ref ORG: RwLock<String> = RwLock::new\("com\.carriez"\.to_owned\(\)\);',
     'pub static ref ORG: RwLock<String> = RwLock::new("es.vexeo".to_owned());'),
]
for pat, rep in subs:
    c, n = re.subn(pat, lambda _m: rep, c)
    if n != 1:
        print(f"hbb_common: patrón sin match único ({n}): {pat}", file=sys.stderr); sys.exit(1)
open(p, "w").write(c)
print("hbb_common: parches VEXEO aplicados")
PYEOF
git add -A
HBB_TREE=$(git write-tree)
if [[ "$HBB_TREE" == "$(git rev-parse origin/main^{tree})" ]]; then
    HBB_SHA=$(git rev-parse origin/main)
    echo "El fork de hbb_common ya está al día ($HBB_SHA) — sin push"
else
    HBB_SHA=$(git commit-tree "$HBB_TREE" -p "$(git rev-parse origin/main)" -p "$HBB_PIN_UPSTREAM" \
        -m "chore: VEXEO sobre hbb_common $HBB_PIN_UPSTREAM (base RustDesk $UPSTREAM_TAG)")
    git push -q origin "$HBB_SHA:refs/heads/main"
    echo "fork hbb_common actualizado: $HBB_SHA"
fi
popd >/dev/null

echo "== Reconstruyendo árbol branded $NEW_VERSION =="
KIT_TMP=$(mktemp -d)
cp -R .github/vexeo/. "$KIT_TMP/"
git checkout -q --detach "$UP_COMMIT"
python3 "$KIT_TMP/vexeo-kit.py" --version "$NEW_VERSION" --hbb-pin "$HBB_SHA"
git add -A -- ':!libs/hbb_common'
git update-index --add --cacheinfo "160000,$HBB_SHA,libs/hbb_common"
TREE=$(git write-tree)

if [[ "$TREE" == "$(git rev-parse "$MASTER^{tree}")" && "$FORCE" != "true" ]]; then
    # El árbol no cambia respecto a master. Recuperación: si el tag de la
    # versión actual de master no está en el remoto (un run anterior publicó
    # el commit pero falló el push del tag), lo publicamos ahora.
    CUR_VER=$(git show "$MASTER:Cargo.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)
    git checkout -q master 2>/dev/null || true
    if [[ -n "$CUR_VER" ]] && ! git ls-remote --exit-code --tags origin "refs/tags/$CUR_VER" >/dev/null 2>&1; then
        echo "Recuperación: falta el tag $CUR_VER en el remoto — lo publico."
        git push origin "$MASTER:refs/tags/$CUR_VER"
    else
        echo "El árbol no cambia y el tag ya existe — nada que publicar."
    fi
    exit 0
fi

NEW_COMMIT=$(git commit-tree "$TREE" -p "$MASTER" -p "$UP_COMMIT" \
    -m "chore: VEXEO Soporte Remoto $NEW_VERSION (upstream RustDesk $UPSTREAM_TAG + kit VEXEO)

Generado por .github/vexeo/autoupdate.sh
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
git checkout -q master 2>/dev/null || true

echo "== Publicando master + tag $NEW_VERSION =="
# Push atómico: master (fast-forward sobre origin/master) y el tag juntos.
git push --atomic origin "$NEW_COMMIT:refs/heads/master" "$NEW_COMMIT:refs/tags/$NEW_VERSION"
echo "Hecho: el push del tag $NEW_VERSION dispara el build (flutter-tag.yml)."
echo "Cuando el build acabe, vexeo-release-finalize.yml marcará la release como latest."
