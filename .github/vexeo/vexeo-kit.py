#!/usr/bin/env python3
"""Kit de branding VEXEO Soporte Remoto.

Transforma un árbol LIMPIO de un tag upstream de RustDesk en el árbol branded
VEXEO. Es la única fuente de verdad del branding: el pipeline de auto-update
(autoupdate.sh) lo ejecuta sobre cada tag nuevo de upstream.

Uso (desde la raíz del repo, con el tag upstream ya en el working tree):
    python3 .github/vexeo/vexeo-kit.py --version 1.4.10 --hbb-pin <sha-fork-hbb_common>

Cada parche verifica que su patrón exista ANTES de aplicar; si upstream cambió
el código y un patrón obligatorio no casa, el script falla con un mensaje claro
(el workflow convierte ese fallo en un issue). Los parches opcionales solo
avisan.
"""

import argparse
import os
import plistlib
import re
import shutil
import sys

APP_NAME = "VEXEO Soporte Remoto"
COMPANY = "VEXEO Digital Solutions, S.L."
BUNDLE_ID = "es.vexeo.soporte"
FORK = "jesusfromero/rustdesk"
RELEASES_LATEST_URL = f"https://github.com/{FORK}/releases/latest"

KIT_SRC = os.path.dirname(os.path.abspath(__file__))

errors = []
warnings = []


def fail(msg):
    errors.append(msg)
    print(f"  ✗ {msg}", file=sys.stderr)


def note(msg):
    warnings.append(msg)
    print(f"  ⚠ {msg}")


def patch(path, old, new, required=True, count=1, is_regex=False):
    """Sustituye old→new en path. Si required y no casa exactamente `count`
    veces, registra error."""
    if not os.path.exists(path):
        (fail if required else note)(f"{path}: no existe")
        return
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if is_regex:
        found = len(re.findall(old, content, flags=re.M))
    else:
        found = content.count(old)
    if found != count:
        msg = f"{path}: patrón encontrado {found} veces (esperado {count}): {old[:80]!r}"
        (fail if required else note)(msg)
        # No aplicamos un reemplazo cuyo alcance no es el esperado: mejor un
        # parche omitido (detectable) que ocurrencias inesperadas sustituidas.
        return
    if is_regex:
        # lambda: el replacement se usa literal (sin procesar \0, \1, etc.)
        content = re.sub(old, lambda _m: new, content, count=count, flags=re.M)
    else:
        content = content.replace(old, new, count)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✓ {path}")


def patch_plist(path, keys):
    if not os.path.exists(path):
        fail(f"{path}: no existe")
        return
    with open(path, "rb") as f:
        data = plistlib.load(f)
    data.update(keys)
    with open(path, "wb") as f:
        plistlib.dump(data, f)
    print(f"  ✓ {path} (plist)")


def install_kit_and_assets(repo_root):
    """Reinstala el propio kit en .github/vexeo, los workflows VEXEO en
    .github/workflows y el overlay de assets binarios sobre el árbol."""
    dest_kit = os.path.join(repo_root, ".github", "vexeo")
    if os.path.realpath(KIT_SRC) != os.path.realpath(dest_kit):
        if os.path.exists(dest_kit):
            shutil.rmtree(dest_kit)
        shutil.copytree(KIT_SRC, dest_kit)
        print(f"  ✓ kit instalado en {dest_kit}")
    wf_src = os.path.join(dest_kit, "workflows")
    wf_dst = os.path.join(repo_root, ".github", "workflows")
    if not os.path.isdir(wf_src):
        fail(f"{wf_src}: no existe el directorio de workflows VEXEO")
        return
    for name in os.listdir(wf_src):
        shutil.copy2(os.path.join(wf_src, name), os.path.join(wf_dst, name))
        print(f"  ✓ workflow {name} instalado")
    overlay = os.path.join(dest_kit, "assets", "tree")
    if not os.path.isdir(overlay):
        fail(f"{overlay}: no existe el overlay de assets binarios")
        return
    n = 0
    for dirpath, _dirnames, filenames in os.walk(overlay):
        for fname in filenames:
            src = os.path.join(dirpath, fname)
            rel = os.path.relpath(src, overlay)
            dst = os.path.join(repo_root, rel)
            if not os.path.exists(os.path.dirname(dst)):
                fail(f"overlay: el directorio destino de {rel} no existe en upstream")
                continue
            shutil.copy2(src, dst)
            n += 1
    if n == 0:
        fail("overlay de assets vacío: el branding gráfico desaparecería")
    print(f"  ✓ overlay de assets: {n} archivos")


def apply_update_check():
    """Fase 3: redirige la comprobación y descarga de actualizaciones del
    cliente a las releases del fork. Compartida por los modos full y
    update-check (bootstrap)."""
    print("== Update check → releases del fork ==")
    patch("src/common.rs",
          """pub fn check_software_update() {
    if is_custom_client() {
        return;
    }
""",
          """pub fn check_software_update() {
""")
    patch("src/common.rs",
          "// Because the url is always `https://api.rustdesk.com/version/latest`.",
          "// VEXEO: consulta la última release del fork en la API de GitHub.",
          required=False)
    patch("src/common.rs",
          """    let (request, url) =
        hbb_common::version_check_request(hbb_common::VER_TYPE_RUSTDESK_CLIENT.to_string());""",
          f"""    let url = "https://api.github.com/repos/{FORK}/releases/latest".to_string();""")
    patch("src/common.rs",
          "client.post(&url).json(&request).send().await",
          'client.get(&url).header("User-Agent", "vexeo-soporte-remoto").send().await',
          count=2)
    patch("src/common.rs",
          """    let bytes = latest_release_response.bytes().await?;
    let resp: hbb_common::VersionCheckResponse = serde_json::from_slice(&bytes)?;
    let response_url = resp.url;
    let latest_release_version = response_url.rsplit('/').next().unwrap_or_default();""",
          f"""    if !latest_release_response.status().is_success() {{
        log::warn!(
            "VEXEO update check: GitHub respondió {{}}",
            latest_release_response.status()
        );
        return Ok(());
    }}
    let bytes = latest_release_response.bytes().await?;
    let resp: serde_json::Value = serde_json::from_slice(&bytes)?;
    let latest_release_version = resp
        .get("tag_name")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .trim_start_matches('v')
        .to_string();
    let response_url = format!("https://github.com/{FORK}/releases/tag/{{latest_release_version}}");""")
    patch("flutter/lib/common.dart",
          "    if (!bind.isCustomClient()) {", "    {")
    patch("flutter/lib/desktop/pages/desktop_home_page.dart",
          """    if (!bind.isCustomClient() &&
        updateUrl.isNotEmpty &&
        !isCardClosed &&
        bind.mainUriPrefixSync().contains('rustdesk')) {""",
          "    if (updateUrl.isNotEmpty && !isCardClosed) {")
    patch("flutter/lib/desktop/pages/desktop_home_page.dart",
          "Uri.parse('https://rustdesk.com/download')",
          f"Uri.parse('{RELEASES_LATEST_URL}')")
    patch("flutter/lib/desktop/pages/desktop_home_page.dart",
          "'https://github.com/rustdesk/rustdesk/releases/tag/${bind.mainGetNewVersion()}'",
          f"'https://github.com/{FORK}/releases/tag/${{bind.mainGetNewVersion()}}'")
    patch("flutter/lib/mobile/pages/connection_page.dart",
          "final url = 'https://rustdesk.com/download';",
          f"final url = '{RELEASES_LATEST_URL}';")
    patch("src/ui/index.tis",
          'handler.open_url("https://rustdesk.com/download");',
          f'handler.open_url("{RELEASES_LATEST_URL}");',
          required=False)
    # MSI: la versión puede llevar sufijo -N; WiX exige numérica con puntos.
    patch("res/msi/preprocess.py",
          """    if g_version == "":
        g_version = read_process_output("--version")
""",
          """    if g_version == "":
        g_version = read_process_output("--version")
    g_version = g_version.replace("-", ".")
""")


def finish(version=None):
    print()
    if warnings:
        print(f"{len(warnings)} avisos (parches opcionales sin efecto)")
    if errors:
        print(f"FALLO: {len(errors)} parches obligatorios no aplicaron:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Kit VEXEO aplicado correctamente{f' para la versión {version}' if version else ''}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="Versión/tag completo, p.ej. 1.4.10 o 1.4.9-2 (no aplica en --mode update-check)")
    ap.add_argument("--hbb-pin", help="SHA del fork jesusfromero/hbb_common a pinear (no aplica en --mode update-check)")
    ap.add_argument("--mode", choices=["full", "update-check"], default="full",
                    help="full: branding completo sobre árbol limpio. "
                         "update-check: solo redirección de updates + workflows (bootstrap sobre master ya branded).")
    args = ap.parse_args()
    full = args.mode == "full"
    version = args.version
    if full:
        if not version or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(-[1-9])?", version):
            print(f"Versión inválida: {version} (formato X.Y.Z o X.Y.Z-N con N de 1 a 9; "
                  "N>9 rompería la comparación con la siguiente versión minor)", file=sys.stderr)
            sys.exit(2)
        if not args.hbb_pin:
            print("--hbb-pin es obligatorio en --mode full", file=sys.stderr)
            sys.exit(2)

    repo_root = os.getcwd()
    if not os.path.exists(os.path.join(repo_root, "Cargo.toml")):
        print("Ejecuta desde la raíz del repo rustdesk", file=sys.stderr)
        sys.exit(2)

    print("== [1/6] Kit + assets + workflows ==")
    install_kit_and_assets(repo_root)

    if not full:
        print("== [modo update-check: salto branding, CI, versión y submódulo] ==")
        apply_update_check()
        finish()
        return

    print("== [2/6] Branding de nombres ==")
    patch("Cargo.toml",
          r'^description = ".*"$',
          'description = "VEXEO Soporte Remoto - Soporte tecnico privado"',
          is_regex=True)
    patch("Cargo.toml", 'ProductName = "RustDesk"', f'ProductName = "{APP_NAME}"')
    patch("libs/portable/Cargo.toml", 'ProductName = "RustDesk"', f'ProductName = "{APP_NAME}"')
    patch("flutter/windows/runner/Runner.rc",
          'VALUE "FileDescription", "RustDesk Remote Desktop" "\\0"',
          f'VALUE "FileDescription", "{APP_NAME}" "\\0"')
    patch("flutter/windows/runner/Runner.rc",
          'VALUE "ProductName", "RustDesk" "\\0"',
          f'VALUE "ProductName", "{APP_NAME}" "\\0"')
    patch("flutter/windows/runner/Runner.rc",
          r'VALUE "CompanyName", "[^"]*" "\\0"',
          f'VALUE "CompanyName", "{COMPANY}" "\\0"',
          is_regex=True)
    patch("flutter/windows/runner/main.cpp",
          'std::wstring app_name = L"RustDesk";',
          f'std::wstring app_name = L"{APP_NAME}";')
    patch("flutter/android/app/src/main/AndroidManifest.xml",
          r'android:label="[^"]*"',
          f'android:label="{APP_NAME}"',
          is_regex=True, count=2)
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig",
          "PRODUCT_NAME = RustDesk", "PRODUCT_NAME = rustdesk")
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig",
          r"^PRODUCT_BUNDLE_IDENTIFIER = .*$",
          f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID}",
          is_regex=True)
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig",
          r"^PRODUCT_COPYRIGHT = .*$",
          "PRODUCT_COPYRIGHT = Basado en RustDesk - Configurado por VEXEO Digital Solutions, S.L.",
          is_regex=True)
    patch_plist("flutter/macos/Runner/Info.plist",
                {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME})
    patch_plist("flutter/ios/Runner/Info.plist",
                {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME})
    patch("flutter/pubspec.yaml",
          r"^description: .*$",
          f"description: {APP_NAME} - VEXEO Digital Solutions",
          is_regex=True)
    patch("flutter/lib/desktop/widgets/tabbar_widget.dart",
          '"RustDesk",', f'"{APP_NAME}",')
    patch("src/lang/en.rs",
          "Connecting to the RustDesk network...",
          "Connecting to the VEXEO network...",
          required=False)

    # Cadenas de UI residuales que dicen "RustDesk" (visibles al usuario).
    # Español (es.rs) e inglés (en.rs) — los idiomas de los clientes VEXEO.
    patch("src/lang/es.rs",
          '("connecting_status", "Conexión a la red RustDesk en progreso..."),',
          '("connecting_status", "Conexión a la red VEXEO en progreso..."),',
          required=False)
    patch("src/lang/es.rs",
          '("powered_by_me", "Con tecnología de RustDesk"),',
          '("powered_by_me", "Con tecnología de VEXEO"),')
    patch("src/lang/en.rs",
          '("powered_by_me", "Powered by RustDesk"),',
          '("powered_by_me", "Powered by VEXEO"),')
    patch("src/lang/es.rs",
          '("About RustDesk", "Acerca de RustDesk"),',
          f'("About RustDesk", "Acerca de {APP_NAME}"),')
    patch("src/lang/es.rs",
          '("Show RustDesk", "Mostrar RustDesk"),',
          f'("Show RustDesk", "Mostrar {APP_NAME}"),')
    patch("src/lang/es.rs",
          '("Keep RustDesk background service", "Dejar RustDesk como Servicio en 2do plano"),',
          '("Keep RustDesk background service", "Dejar VEXEO en segundo plano"),')
    # Inglés: About/Show/Keep no tienen entrada en en.rs (caen al literal de la
    # key). Insertamos overrides anclando a la 1ª entrada estable del mapa.
    patch("src/lang/en.rs",
          '        ("desk_tip", "Your desktop can be accessed with this ID and password."),\n',
          '        ("desk_tip", "Your desktop can be accessed with this ID and password."),\n'
          f'        ("About RustDesk", "About {APP_NAME}"),\n'
          f'        ("Show RustDesk", "Show {APP_NAME}"),\n'
          '        ("Keep RustDesk background service", "Keep VEXEO background service"),\n')
    # El clic en "Con tecnología de..." abría rustdesk.com
    patch("flutter/lib/common.dart",
          "launchUrl(Uri.parse('https://rustdesk.com'));",
          "launchUrl(Uri.parse('https://vexeo.es'));",
          required=False)

    # Servicio de sistema en macOS: los scripts construyen rutas SIN comillas.
    # Con "VEXEO Soporte Remoto" (con espacios) el shell parte la ruta y el
    # .plist del servicio nunca se crea → "Instalar" no funciona. Entrecomillamos
    # las rutas en install.scpt, daemon.plist y update.scpt.
    _D = "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist"
    _A = "/Library/LaunchAgents/com.carriez.RustDesk_server.plist"
    _isc = "src/platform/privileges_scripts/install.scpt"
    patch(_isc, f'" > {_D} && chown root:wheel {_D};"',
          f'" > \'{_D}\' && chown root:wheel \'{_D}\';"')
    patch(_isc, f'" > {_A} && chown root:wheel {_A};"',
          f'" > \'{_A}\' && chown root:wheel \'{_A}\';"')
    patch(_isc,
          '"cp -rf /Users/" & user & "/Library/Preferences/com.carriez.RustDesk/RustDesk.toml /var/root/Library/Preferences/com.carriez.RustDesk/;"',
          '"cp -rf \'/Users/" & user & "/Library/Preferences/com.carriez.RustDesk/RustDesk.toml\' \'/var/root/Library/Preferences/com.carriez.RustDesk/\';"')
    patch(_isc,
          '"cp -rf /Users/" & user & "/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml /var/root/Library/Preferences/com.carriez.RustDesk/;"',
          '"cp -rf \'/Users/" & user & "/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml\' \'/var/root/Library/Preferences/com.carriez.RustDesk/\';"')
    patch(_isc, f'"launchctl load -w {_D};"', f'"launchctl load -w \'{_D}\';"')
    patch("src/platform/privileges_scripts/daemon.plist",
          "<string>/Applications/RustDesk.app/Contents/MacOS/service</string>",
          "<string>'/Applications/RustDesk.app/Contents/MacOS/service'</string>")
    _up = "src/platform/privileges_scripts/update.scpt"
    patch(_up, 'set unload_service to "launchctl unload -w " & daemon_plist & " || true;"',
          'set unload_service to "launchctl unload -w " & quoted form of daemon_plist & " || true;"')
    patch(_up, 'set write_daemon_plist to "echo " & quoted form of daemon_file & " > " & daemon_plist & " && chown root:wheel " & daemon_plist & ";"',
          'set write_daemon_plist to "echo " & quoted form of daemon_file & " > " & quoted form of daemon_plist & " && chown root:wheel " & quoted form of daemon_plist & ";"')
    patch(_up, 'set write_agent_plist to "echo " & quoted form of agent_file & " > " & agent_plist & " && chown root:wheel " & agent_plist & ";"',
          'set write_agent_plist to "echo " & quoted form of agent_file & " > " & quoted form of agent_plist & " && chown root:wheel " & quoted form of agent_plist & ";"')
    patch(_up, 'set load_service to "launchctl load -w " & daemon_plist & ";"',
          'set load_service to "launchctl load -w " & quoted form of daemon_plist & ";"')

    # ORG: hbb_common pasa a ORG="es.vexeo" (ver autoupdate.sh), así que
    # get_full_name() = "es.vexeo.<APP_NAME>" y los .plist del servicio deben
    # llamarse igual. Los scripts hardcodean "com.carriez.RustDesk_*", hay que
    # cambiarlos A LA VEZ que ORG o el instalador escribiría un nombre distinto
    # al que comprueba is_installed_daemon() y el servicio no se detectaría.
    # OJO: NO tocar "com.carriez.rustdesk" (minúscula, AssociatedBundleIdentifiers):
    # correct_app_name() lo sustituye en runtime por el bundle id real.
    # Debe ir DESPUÉS del entrecomillado (esos patrones aún llevan com.carriez).
    for _f in ("install.scpt", "daemon.plist", "agent.plist", "update.scpt", "uninstall.scpt"):
        _p = f"src/platform/privileges_scripts/{_f}"
        _c = open(_p, encoding="utf-8").read()
        _n = _c.count("com.carriez.RustDesk")
        if _n == 0:
            fail(f"{_p}: no se encontró 'com.carriez.RustDesk' (¿cambió upstream?)")
            continue
        open(_p, "w", encoding="utf-8").write(_c.replace("com.carriez.RustDesk", "es.vexeo.RustDesk"))
        print(f"  ✓ {_f}: {_n}x com.carriez.RustDesk → es.vexeo.RustDesk")

    apply_update_check()

    print("== [4/6] Ajustes de CI del fork ==")
    patch(".github/workflows/fdroid.yml",
          """on:
  workflow_dispatch:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'
      - '[0-9]+.[0-9]+.[0-9]+'
      - 'v[0-9]+.[0-9]+.[0-9]+-[0-9]+'
      - '[0-9]+.[0-9]+.[0-9]+-[0-9]+'
""",
          """on:
  # Desactivado en el fork VEXEO: no distribuimos por F-Droid
  workflow_dispatch:
""")
    patch(".github/workflows/flutter-nightly.yml",
          """on:
  schedule:
    # schedule build every night
    - cron: "0 0 * * *"
  workflow_dispatch:""",
          """on:
  # Nightly desactivada en el fork VEXEO: se compila por tag (flutter-tag.yml)
  workflow_dispatch:""")
    patch(".github/workflows/flutter-build.yml",
          "  build-for-windows-sciter:\n    name:",
          "  build-for-windows-sciter:\n    if: false\n    name:")
    patch(".github/workflows/flutter-tag.yml",
          "\njobs:\n  run-flutter-tag-build:",
          """

# El token por defecto del repo es de solo lectura; el paso "Publish Release"
# necesita crear releases y subir assets.
permissions:
  contents: write

jobs:
  run-flutter-tag-build:""")
    # DMG sin firmar: el paso Rename añadía el arch dos veces
    patch(".github/workflows/flutter-build.yml",
          """          for name in rustdesk*??.dmg; do
              mv "$name" "${name%%.dmg}-${{ matrix.job.arch }}.dmg"
          done""",
          """          for name in rustdesk*??.dmg; do
              case "$name" in *-${{ matrix.job.arch }}.dmg) continue;; esac
              mv "$name" "${name%%.dmg}-${{ matrix.job.arch }}.dmg"
          done""")
    # Firma macOS: entrecomillar password e identidad. Upstream los interpola
    # sin comillas y un password con metacaracteres de shell (p.ej. &) o una
    # identidad con espacios rompería el paso de firma.
    patch(".github/workflows/flutter-build.yml",
          "security unlock-keychain -p ${{ secrets.MACOS_P12_PASSWORD }} rustdesk.keychain",
          'security unlock-keychain -p "${{ secrets.MACOS_P12_PASSWORD }}" rustdesk.keychain')
    patch(".github/workflows/flutter-build.yml",
          "-s ${{ secrets.MACOS_CODESIGN_IDENTITY }} --deep",
          '-s "${{ secrets.MACOS_CODESIGN_IDENTITY }}" --deep',
          count=2)
    # Renombrar la .app Y el ejecutable de macOS a la marca VEXEO. build.py
    # genera RustDesk.app con ejecutable 'rustdesk'; el instalador de servicio
    # (agent.plist) lanza /Applications/<app>.app/Contents/MacOS/<app>, es decir
    # el ejecutable POR NOMBRE = get_app_name() = "VEXEO Soporte Remoto". Si no
    # coincide, el servicio/agente no arranca (acceso desatendido roto).
    patch(".github/workflows/flutter-build.yml",
          "          ./build.py --flutter --hwcodec --unix-file-copy-paste ${{ matrix.job.extra-build-args }}\n",
          "          ./build.py --flutter --hwcodec --unix-file-copy-paste ${{ matrix.job.extra-build-args }}\n"
          '          # VEXEO: renombrar la .app y el ejecutable a la marca (instalador, servicio y agente)\n'
          '          RELDIR="./flutter/build/macos/Build/Products/Release"\n'
          '          app="$(ls -d "$RELDIR"/*.app 2>/dev/null | head -1)"\n'
          '          if [ -n "$app" ] && [ "$app" != "$RELDIR/VEXEO Soporte Remoto.app" ]; then mv "$app" "$RELDIR/VEXEO Soporte Remoto.app"; fi\n'
          '          APP="$RELDIR/VEXEO Soporte Remoto.app"\n'
          '          EXE="$(/usr/libexec/PlistBuddy -c \'Print :CFBundleExecutable\' "$APP/Contents/Info.plist" 2>/dev/null || echo rustdesk)"\n'
          '          if [ "$EXE" != "VEXEO Soporte Remoto" ] && [ -f "$APP/Contents/MacOS/$EXE" ]; then mv "$APP/Contents/MacOS/$EXE" "$APP/Contents/MacOS/VEXEO Soporte Remoto"; /usr/libexec/PlistBuddy -c "Set :CFBundleExecutable \'VEXEO Soporte Remoto\'" "$APP/Contents/Info.plist"; fi\n')
    patch(".github/workflows/flutter-build.yml",
          'create-dmg --icon "RustDesk.app" 200 190 --hide-extension "RustDesk.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{ env.VERSION }}-${{ matrix.job.arch }}.dmg ./flutter/build/macos/Build/Products/Release/RustDesk.app',
          'create-dmg --volname "VEXEO Soporte Remoto" --icon "VEXEO Soporte Remoto.app" 200 190 --hide-extension "VEXEO Soporte Remoto.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{ env.VERSION }}-${{ matrix.job.arch }}.dmg "./flutter/build/macos/Build/Products/Release/VEXEO Soporte Remoto.app"')
    patch(".github/workflows/flutter-build.yml",
          'codesign --force --options runtime -s "${{ secrets.MACOS_CODESIGN_IDENTITY }}" --deep --strict ./flutter/build/macos/Build/Products/Release/RustDesk.app -vvv',
          'codesign --force --options runtime -s "${{ secrets.MACOS_CODESIGN_IDENTITY }}" --deep --strict "./flutter/build/macos/Build/Products/Release/VEXEO Soporte Remoto.app" -vvv')
    patch(".github/workflows/flutter-build.yml",
          'create-dmg --icon "RustDesk.app" 200 190 --hide-extension "RustDesk.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{ env.VERSION }}.dmg ./flutter/build/macos/Build/Products/Release/RustDesk.app',
          'create-dmg --volname "VEXEO Soporte Remoto" --icon "VEXEO Soporte Remoto.app" 200 190 --hide-extension "VEXEO Soporte Remoto.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{ env.VERSION }}.dmg "./flutter/build/macos/Build/Products/Release/VEXEO Soporte Remoto.app"')
    # Quitar macOS Intel (x86_64-apple-darwin): no lo distribuimos y es el build
    # más lento. Se elimina de la matriz build-for-macOS y su descarga en
    # publish_unsigned (que si no fallaría al no existir el artefacto x86_64).
    wf = ".github/workflows/flutter-build.yml"
    _c = open(wf, encoding="utf-8").read()
    _c2 = re.sub(r"\n          - \{\n              target: x86_64-apple-darwin,.*?\n            \}",
                 "", _c, count=1, flags=re.S)
    if _c2 == _c:
        fail("no se pudo quitar la entrada macOS Intel de la matriz")
    _c = _c2
    _c2 = re.sub(r"      - name: Download [Aa]rtifacts\n        uses: actions/download-artifact@[0-9a-f]+ # v8\.0\.1\n        with:\n          name: rustdesk-unsigned-macos-x86_64\n          path: \./\n\n",
                 "", _c, count=1)
    if _c2 == _c:
        note("no se encontró la descarga unsigned-macos-x86_64 en publish_unsigned")
    open(wf, "w", encoding="utf-8").write(_c2)
    print("  ✓ macOS Intel eliminado (matriz + publish_unsigned)")

    print("== [5/6] Sincronizar versión (tag = Cargo.toml = env VERSION) ==")
    patch("Cargo.toml",
          r'^version = "[0-9][^"]*"$',
          f'version = "{version}"',
          is_regex=True)
    with open("Cargo.lock", encoding="utf-8") as f:
        lock = f.read()
    m = re.search(r'(name = "rustdesk"\nversion = ")[^"]*(")', lock)
    if not m:
        fail("Cargo.lock: no se encontró el paquete rustdesk")
    else:
        lock = lock[:m.start(1)] + m.group(1) + version + m.group(2) + lock[m.end(2):]
        with open("Cargo.lock", "w", encoding="utf-8") as f:
            f.write(lock)
        print("  ✓ Cargo.lock")
    patch(".github/workflows/flutter-build.yml",
          r'^  VERSION: "[0-9][^"]*"$',
          f'  VERSION: "{version}"',
          is_regex=True)

    print("== [6/6] Submódulo hbb_common → fork ==")
    with open(".gitmodules", "w", encoding="utf-8") as f:
        f.write("""[submodule "libs/hbb_common"]
\tpath = libs/hbb_common
\turl = https://github.com/jesusfromero/hbb_common.git
\tbranch = main
""")
    print(f"  ✓ .gitmodules (pin {args.hbb_pin} lo fija autoupdate.sh en el índice git)")

    finish(version)


if __name__ == "__main__":
    main()
