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
import glob
import os
import plistlib
import re
import shutil
import sys

# APP_NAME NO PUEDE LLEVAR ESPACIOS. Upstream lo interpola sin comillas en ~35
# comandos (`sc create {app_name}`, `reg add {subkey}`, `taskkill /F /IM
# {app_name}.exe`) y además deriva de él el esquema URL y la extensión de
# fichero (get_uri_prefix() en common.rs, `ext` en windows.rs). Con espacios:
# el servicio de Windows no se crea, la app no aparece en Programas y
# características, y el esquema "vexeo soporte remoto://" es inválido (RFC 3986)
# → Uri.tryParse() devuelve null y la conexión se descarta EN SILENCIO.
# Sin espacios todo eso funciona con el código de upstream sin parchear nada.
APP_NAME = "VexeoSoporte"
# Nombre comercial. SOLO para campos de texto libre que el SO nunca mete en una
# ruta ni en un comando (descripción del .exe, volumen del DMG, etiqueta de
# Android, texto de notificaciones). Nunca para APP_NAME ni para nada que
# derive de él.
BRAND = "VEXEO Soporte Remoto"
COMPANY = "VEXEO Digital Solutions, S.L."
BUNDLE_ID = "es.vexeo.soporte"
FORK = "jesusfromero/vexeo-soporte-remoto"
RELEASES_LATEST_URL = f"https://github.com/{FORK}/releases/latest"

# Lo que registra el SO como esquema URL y extensión debe coincidir con lo que
# la app construye y parsea en runtime: get_uri_prefix() = APP_NAME.lower().
URI_SCHEME = APP_NAME.lower()

WEB_URL = "https://vexeo.es"
PRIVACY_URL = "https://www.vexeo.es/politica-de-privacidad/"

# AGPL-3.0: §4 obliga a conservar íntegros los avisos de copyright y licencia,
# §5(a) a indicar que la obra se ha modificado y cuándo, y §6/§13 a ofrecer el
# código fuente. NO se puede borrar el copyright de Purslane. Lo que sí se puede
# (y se debe) quitar es la MARCA "RustDesk", que es marca registrada y ajena.
# La clave: el titular se llama "Purslane Tech Pte. Ltd.", no "RustDesk" — se
# cumple la licencia al 100% sin que la marca aparezca en ningún sitio.
_COPYRIGHT_BASE = (
    "Copyright © 2026 Purslane Tech Pte. Ltd. "
    f"Modificado por {COMPANY} (2026). Licencia AGPL-3.0, sin garantía. "
    "Código fuente: "
)
COPYRIGHT = _COPYRIGHT_BASE + f"https://github.com/{FORK}"
# En los .xcconfig, "//" ABRE UN COMENTARIO: con la URL completa, Xcode dejaba
# el valor en "...Código fuente: https:" y se comía la oferta de código que
# exige la AGPL. No hay forma de escaparlo, así que aquí la URL va sin esquema.
# Verificado sobre el .app compilado de 1.4.9-8, no por lectura de código.
COPYRIGHT_XCCONFIG = _COPYRIGHT_BASE + f"github.com/{FORK}"

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


# Formato verificado sobre 1.4.9: en los 51 src/lang/*.rs, TODA entrada es una
# tupla de una sola línea `("key", "valor"),` dentro de un lazy_static!. Cero
# valores multilínea, cero líneas comentadas (comprobado: ninguna línea con la
# marca queda fuera de este patrón).
#
# El 1er literal entrecomillado es la KEY: translate() la usa como índice del
# HashMap Y como texto de respaldo cuando no hay traducción, y Dart/Sciter la
# pasan literal (translate('About RustDesk')). Tocarla rompe la traducción en
# los 51 ficheros a la vez. El 2º literal es el VALOR: es lo único que se toca.
LANG_ENTRY_RE = re.compile(
    r'^(?P<head>\s*\("(?P<key>(?:[^"\\]|\\.)*)"\s*,\s*")'
    r'(?P<value>(?:[^"\\]|\\.)*)'
    r'(?P<tail>"\s*\),?\s*)$'
)

# Sin \b a propósito: en et/fi/hu/ko la marca lleva la declinación pegada
# ("RustDeskile", "RustDesk를") y una frontera de palabra la dejaría pasar. La
# variante "Rustdesk" (8 casos en da/el/it/nl/uk) se escapa del replace() de
# runtime, que distingue mayúsculas — de ahí [Rr] y [Dd].
LANG_BRAND_RE = re.compile(r"[Rr]ust[Dd]esk")

# Estos dos valores son URLs, no texto: sustituir dentro rompería el enlace.
LANG_SKIP_KEYS = {"doc_mac_permission", "doc_fix_wayland"}


def patch_all_langs():
    """Quita la marca de los VALORES de todos los src/lang/*.rs. Nunca de las keys."""
    total, nfiles = 0, 0
    for path in sorted(glob.glob("src/lang/*.rs")):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        n = 0
        for i, line in enumerate(lines):
            m = LANG_ENTRY_RE.match(line)
            if not m or m.group("key") in LANG_SKIP_KEYS:
                continue
            new_value, k = LANG_BRAND_RE.subn(APP_NAME, m.group("value"))
            if k:
                lines[i] = m.group("head") + new_value + m.group("tail")
                n += k
        if n:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            total += n
            nfiles += 1
    print(f"  ✓ i18n: {total} sustituciones en {nfiles} ficheros")
    # Guarda: si upstream cambiara el formato de src/lang/*.rs, el regex dejaría
    # de casar y la marca pasaría entera sin que nadie se entere. Preferimos
    # romper el build. Medido en 1.4.9: ~1180.
    if total < 1000:
        fail(f"patch_all_langs solo sustituyó {total} (esperadas ~1180): "
             "¿cambió el formato de src/lang/*.rs?")


def patch_lang_doc_urls():
    """Las 2 keys doc_* son URLs a rustdesk.com que se abren en el navegador."""
    patch("src/lang/en.rs",
          '("doc_mac_permission", "https://rustdesk.com/docs/en/client/mac/#enable-permissions"),',
          f'("doc_mac_permission", "{WEB_URL}"),',
          required=False)
    patch("src/lang/en.rs",
          '("doc_fix_wayland", "https://rustdesk.com/docs/en/client/linux/#x11-required"),',
          f'("doc_fix_wayland", "{WEB_URL}"),',
          required=False)


def verify_no_brand_in_lang_values():
    """Auditoría post-parche: ningún valor de i18n puede conservar la marca."""
    bad = []
    for path in sorted(glob.glob("src/lang/*.rs")):
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                m = LANG_ENTRY_RE.match(line.rstrip("\n"))
                if m and "rustdesk" in m.group("value").lower():
                    bad.append(f"{path}:{i} [{m.group('key')}]")
    if bad:
        fail("marca residual en valores i18n: " + ", ".join(bad[:5])
             + (f" (+{len(bad) - 5} más)" if len(bad) > 5 else ""))
    else:
        print("  ✓ i18n: 0 residuos de la marca en los valores")


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
    # Metadatos winres del .exe. FileDescription es lo que Windows muestra en el
    # prompt de UAC al instalar: sin esto el cliente lee "RustDesk Remote
    # Desktop" justo al arrancar la instalación. El resto se ve en clic derecho
    # > Propiedades > Detalles. Bloques completos (no líneas sueltas) porque el
    # orden de las claves difiere entre los dos Cargo.toml.
    patch("Cargo.toml",
          'LegalCopyright = "Copyright © 2026 Purslane Tech Pte. Ltd. All rights reserved."\n'
          'ProductName = "RustDesk"\n'
          'FileDescription = "RustDesk Remote Desktop"\n'
          'OriginalFilename = "rustdesk.exe"',
          f'LegalCopyright = "{COPYRIGHT}"\n'
          f'ProductName = "{APP_NAME}"\n'
          f'FileDescription = "{BRAND}"\n'
          f'OriginalFilename = "{APP_NAME}.exe"')
    patch("libs/portable/Cargo.toml",
          'LegalCopyright = "Copyright © 2026 Purslane Tech Pte. Ltd. All rights reserved."\n'
          'ProductName = "RustDesk"\n'
          'OriginalFilename = "rustdesk.exe"\n'
          'FileDescription = "RustDesk Remote Desktop"',
          f'LegalCopyright = "{COPYRIGHT}"\n'
          f'ProductName = "{APP_NAME}"\n'
          f'OriginalFilename = "{APP_NAME}.exe"\n'
          f'FileDescription = "{BRAND}"')
    patch("libs/portable/Cargo.toml",
          'description = "RustDesk Remote Desktop"',
          f'description = "{BRAND}"')
    # Runner.rc gobierna el .exe que se distribuye (--silent-install).
    patch("flutter/windows/runner/Runner.rc",
          '            VALUE "CompanyName", "Purslane Tech Pte. Ltd." "\\0"\n'
          '            VALUE "FileDescription", "RustDesk Remote Desktop" "\\0"\n'
          '            VALUE "FileVersion", VERSION_AS_STRING "\\0"\n'
          '            VALUE "InternalName", "rustdesk" "\\0"\n'
          '            VALUE "LegalCopyright", "Copyright © 2026 Purslane Tech Pte. Ltd. All rights reserved." "\\0"\n'
          '            VALUE "OriginalFilename", "rustdesk.exe" "\\0"\n'
          '            VALUE "ProductName", "RustDesk" "\\0"',
          f'            VALUE "CompanyName", "{COMPANY}" "\\0"\n'
          f'            VALUE "FileDescription", "{BRAND}" "\\0"\n'
          '            VALUE "FileVersion", VERSION_AS_STRING "\\0"\n'
          f'            VALUE "InternalName", "{APP_NAME}" "\\0"\n'
          f'            VALUE "LegalCopyright", "{COPYRIGHT}" "\\0"\n'
          f'            VALUE "OriginalFilename", "{APP_NAME}.exe" "\\0"\n'
          f'            VALUE "ProductName", "{APP_NAME}" "\\0"')
    patch("flutter/windows/runner/main.cpp",
          'std::wstring app_name = L"RustDesk";',
          f'std::wstring app_name = L"{APP_NAME}";')
    patch("flutter/android/app/src/main/AndroidManifest.xml",
          r'android:label="[^"]*"',
          f'android:label="{BRAND}"',
          is_regex=True, count=2)
    # applicationId: se ve en Ajustes > Aplicaciones > Detalles y en la ruta de
    # datos /data/user/0/<id>. Verificado que NO rompe el puente Rust↔Kotlin
    # (los símbolos JNI son Java_ffi_FFI_*, del paquete `ffi`, no de carriez) ni
    # hay FileProvider ni permisos custom. En AGP el applicationId es
    # independiente del `package` del manifest, así que no hay que tocar ningún
    # .kt. Es DE POR VIDA: cambiarlo más adelante obliga a desinstalar y
    # reinstalar móvil por móvil (INSTALL_FAILED_UPDATE_INCOMPATIBLE).
    patch("flutter/android/app/build.gradle",
          'applicationId "com.carriez.flutter_hbb"',
          f'applicationId "{BUNDLE_ID}"')
    # Este texto es el que Android muestra DENTRO del diálogo "¿Permitir que
    # <app> tenga control total de tu dispositivo?" — lectura obligatoria al
    # conceder el permiso. Decía "when RustDesk screen sharing is established".
    patch("flutter/android/app/src/main/res/values/strings.xml",
          '<string name="accessibility_service_description">Allow other devices to control your phone using virtual touch, when RustDesk screen sharing is established</string>',
          '<string name="accessibility_service_description">Permite al técnico controlar este dispositivo mediante toques virtuales durante una sesión de VEXEO Soporte Remoto.</string>')
    patch("flutter/android/app/src/main/res/values/strings.xml",
          '<string name="app_name">RustDesk</string>',
          f'<string name="app_name">{BRAND}</string>')
    _ms = "flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/MainService.kt"
    # Título de la notificación PERSISTENTE: está en la barra de estado todo el
    # rato mientras el servicio corre.
    patch(_ms, 'const val DEFAULT_NOTIFY_TITLE = "RustDesk"',
          f'const val DEFAULT_NOTIFY_TITLE = "{BRAND}"')
    # Canal de notificación: visible en Ajustes > Aplicaciones > Notificaciones.
    patch(_ms,
          '            val channelId = "RustDesk"\n'
          '            val channelName = "RustDesk Service"',
          f'            val channelId = "{BUNDLE_ID}"\n'
          f'            val channelName = "{BRAND}"')
    patch(_ms, 'description = "RustDesk Service Channel"',
          f'description = "Servicio de {BRAND}"')
    patch(_ms, '"RustDeskVD",', '"VexeoVD",')
    # Toast de 3,5 s en cada arranque del móvil si se activa "iniciar al encender".
    patch("flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/BootReceiver.kt",
          'Toast.makeText(context, "RustDesk is Open", Toast.LENGTH_LONG).show()',
          f'Toast.makeText(context, "{BRAND} está activo", Toast.LENGTH_LONG).show()')
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig",
          "PRODUCT_NAME = RustDesk", "PRODUCT_NAME = rustdesk")
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig",
          r"^PRODUCT_BUNDLE_IDENTIFIER = .*$",
          f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID}",
          is_regex=True)
    # PRODUCT_COPYRIGHT alimenta NSHumanReadableCopyright, visible en Finder >
    # Obtener información. Ojo: aquí NO puede decir "RustDesk" (es justo lo que
    # se quiere eliminar) pero SÍ debe conservar a Purslane (AGPL §4).
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig",
          r"^PRODUCT_COPYRIGHT = .*$",
          f"PRODUCT_COPYRIGHT = {COPYRIGHT_XCCONFIG}",
          is_regex=True)
    # El bundle id REAL sale de aquí, no del xcconfig: en Xcode los build
    # settings del target ganan sobre los del proyecto. Parchear solo el
    # xcconfig (como se hacía antes) no tenía ningún efecto y el .app firmado
    # salía como com.carriez.rustdesk. Verificado sobre la app ya instalada.
    patch("flutter/macos/Runner.xcodeproj/project.pbxproj",
          "PRODUCT_BUNDLE_IDENTIFIER = com.carriez.rustdesk;",
          f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID};",
          count=3)
    patch_plist("flutter/macos/Runner/Info.plist",
                {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME})
    patch_plist("flutter/ios/Runner/Info.plist",
                {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME})
    # Esquema URL: el SO debe registrar exactamente el mismo que la app
    # construye y parsea en runtime (get_uri_prefix() = APP_NAME.lower()). Si no
    # coinciden, los enlaces de conexión entran pero no se resuelven.
    _url_types = [{
        "CFBundleTypeRole": "Editor",
        "CFBundleURLIconFile": "",
        "CFBundleURLName": BUNDLE_ID,
        "CFBundleURLSchemes": [URI_SCHEME],
    }]
    patch_plist("flutter/macos/Runner/Info.plist", {"CFBundleURLTypes": _url_types})
    patch_plist("flutter/ios/Runner/Info.plist", {"CFBundleURLTypes": _url_types})
    patch("flutter/android/app/src/main/AndroidManifest.xml",
          '<data android:scheme="rustdesk" />',
          f'<data android:scheme="{URI_SCHEME}" />')
    patch("flutter/pubspec.yaml",
          r"^description: .*$",
          f"description: {APP_NAME} - VEXEO Digital Solutions",
          is_regex=True)
    patch("flutter/lib/desktop/widgets/tabbar_widget.dart",
          '"RustDesk",', f'"{APP_NAME}",')
    # --- i18n ---------------------------------------------------------------
    # translate() (src/lang.rs) YA sustituye "RustDesk"→APP_NAME en runtime
    # cuando is_rustdesk()==false, en los 50 idiomas y también en el fallback al
    # literal de la key. Así que casi todo esto es redundante HOY. Se hace
    # igualmente por dos motivos:
    #   1. Tres casos se escapan del runtime: powered_by_me y
    #      upgrade_rustdesk_server_pro están excluidos a propósito en lang.rs, y
    #      la sustitución distingue mayúsculas (no pilla las 8 "Rustdesk").
    #   2. Todo ese rebranding automático cuelga de UNA línea del submódulo
    #      hbb_common (APP_NAME). Si alguien reapunta el submódulo a upstream,
    #      is_rustdesk() pasa a true y la marca reaparece de golpe en 43 textos
    #      × 50 idiomas, en silencio. La sustitución estática es el seguro.
    # Redacciones curadas primero (las hace patch_all_langs() innecesarias sobre
    # esas líneas, porque ya no contienen la marca):
    patch("src/lang/en.rs",
          "Connecting to the RustDesk network...",
          "Connecting to the VEXEO network...",
          required=False)
    patch("src/lang/es.rs",
          '("connecting_status", "Conexión a la red RustDesk en progreso..."),',
          '("connecting_status", "Conexión a la red VEXEO en progreso..."),',
          required=False)
    # powered_by_me: excluido en lang.rs, no hay runtime que lo salve. Además va
    # con fontSize 9 y TextOverflow.clip bajo el ID de la pantalla principal, así
    # que aquí interesa "VEXEO" a secas y no el nombre largo.
    patch("src/lang/es.rs",
          '("powered_by_me", "Con tecnología de RustDesk"),',
          '("powered_by_me", "Con tecnología de VEXEO"),')
    patch("src/lang/en.rs",
          '("powered_by_me", "Powered by RustDesk"),',
          '("powered_by_me", "Powered by VEXEO"),')
    # Slogan_tip es el eslogan de marca de RustDesk (la frase más reconocible
    # que tiene). No lo exige ninguna licencia: es marketing, no un aviso legal.
    patch("src/lang/es.rs",
          '("Slogan_tip", "¡Hecho con corazón en este mundo caótico!"),',
          f'("Slogan_tip", "Soporte técnico privado de {COMPANY}"),')
    patch("src/lang/en.rs",
          '("Slogan_tip", "Made with heart in this chaotic world!"),',
          f'("Slogan_tip", "Private remote support by {COMPANY}"),')
    patch_all_langs()
    patch_lang_doc_urls()
    verify_no_brand_in_lang_values()

    # --- URLs y textos hardcodeados que no pasan por translate() -------------
    # El clic en "Con tecnología de..." abría rustdesk.com
    patch("flutter/lib/common.dart",
          "launchUrl(Uri.parse('https://rustdesk.com'));",
          f"launchUrl(Uri.parse('{WEB_URL}'));",
          required=False)
    # PANTALLA DE INSTALACIÓN: el enlace va etiquetado "Acuerdo de licencia de
    # usuario final" y la URL se ve en el tooltip con solo pasar el ratón, sin
    # hacer clic. El cliente estaría aceptando el EULA de otra empresa.
    patch("flutter/lib/desktop/pages/install_page.dart",
          "                            onTap: () => launchUrlString(\n"
          "                                'https://rustdesk.com/privacy.html'),\n"
          "                            child: Tooltip(\n"
          "                              message: 'https://rustdesk.com/privacy.html',",
          f"                            onTap: () => launchUrlString(\n"
          f"                                '{PRIVACY_URL}'),\n"
          f"                            child: Tooltip(\n"
          f"                              message: '{PRIVACY_URL}',")
    # Ajustes > Acerca de: enlaces "Declaración de privacidad" y "Sitio web".
    _dsp = "flutter/lib/desktop/pages/desktop_setting_page.dart"
    patch(_dsp, "launchUrlString('https://rustdesk.com/privacy.html');",
          f"launchUrlString('{PRIVACY_URL}');")
    patch(_dsp, "launchUrlString('https://rustdesk.com');",
          f"launchUrlString('{WEB_URL}');")
    # La tarjeta azul del About. Conserva a Purslane (AGPL §4/§5(d): la UI
    # interactiva debe mostrar los avisos legales porque el original ya lo
    # hacía) y añade el aviso de modificación y la oferta de código fuente.
    # El año va fijo: es el de la obra, no el del reloj del cliente.
    patch(_dsp,
          "                            'Copyright © ${DateTime.now().toString().substring(0, 4)} Purslane Tech Pte. Ltd.\\n$license',",
          "                            'Copyright © 2026 Purslane Tech Pte. Ltd.\\n'\n"
          f"                            'Modificado por {COMPANY} (2026).\\n'\n"
          "                            'Licencia AGPL-3.0. SIN GARANTÍA de ningún tipo.\\n'\n"
          f"                            'Código fuente: https://github.com/{FORK}\\n$license',")
    # Móvil > Ajustes > Acerca de: "rustdesk.com" se LEE en pantalla como valor
    # de la fila Versión, no hace falta ni pinchar.
    _msp = "flutter/lib/mobile/pages/settings_page.dart"
    patch(_msp, "const url = 'https://rustdesk.com/';", f"const url = '{WEB_URL}/';", count=2)
    patch(_msp, "child: Text('rustdesk.com',", "child: Text('vexeo.es',", count=2)
    patch(_msp, "launchUrlString('https://rustdesk.com/privacy.html'),",
          f"launchUrlString('{PRIVACY_URL}'),")
    patch("flutter/lib/desktop/pages/connection_page.dart",
          'const url = "https://rustdesk.com/pricing";',
          f'const url = "{WEB_URL}";',
          required=False)

    # --- Cadenas de Rust visibles ------------------------------------------
    # Título del MessageBox de error en Windows: el cliente lo ve justo cuando
    # algo falla en la instalación, o sea en el peor momento posible.
    patch("src/platform/windows.rs",
          'let caption = "RustDesk Output"',
          f'let caption = "{BRAND}"')
    # Nombre que aparece en la app de autenticación del cliente (Google
    # Authenticator, etc.) si activa la verificación en dos pasos.
    patch("src/auth_2fa.rs",
          'const ISSUER: &str = "RustDesk";',
          f'const ISSUER: &str = "{BRAND}";')
    # RuntimeBroker_rustdesk.exe: es el RuntimeBroker.exe de Windows copiado y
    # renombrado. Queda como fichero en la carpeta de instalación y como proceso
    # en el Administrador de tareas al usar el modo privacidad. SIN espacios: se
    # usa en `taskkill /F /IM {broker_exe}` sin comillas. Los tres literales
    # deben coincidir o el packer mataría un proceso que ya no existe.
    patch("src/privacy_mode/win_topmost_window.rs",
          'pub const WIN_TOPMOST_INJECTED_PROCESS_EXE: &\'static str = "RuntimeBroker_rustdesk.exe";',
          'pub const WIN_TOPMOST_INJECTED_PROCESS_EXE: &\'static str = "RuntimeBroker_vexeo.exe";')
    patch("libs/portable/src/main.rs",
          'pub const WIN_TOPMOST_INJECTED_PROCESS_EXE: &\'static str = "RuntimeBroker_rustdesk.exe";',
          'pub const WIN_TOPMOST_INJECTED_PROCESS_EXE: &\'static str = "RuntimeBroker_vexeo.exe";')
    patch("libs/portable/src/main.rs",
          '.args(&["/F", "/IM", "RuntimeBroker_rustdesk.exe"])',
          '.args(&["/F", "/IM", "RuntimeBroker_vexeo.exe"])')
    # El packer portable extrae los binarios a %LOCALAPPDATA%\<APP_PREFIX>\ —
    # carpeta visible en el perfil del usuario.
    patch("libs/portable/src/main.rs",
          'const APP_PREFIX: &str = "rustdesk";',
          'const APP_PREFIX: &str = "vexeo";')

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
          f'          if [ -n "$app" ] && [ "$app" != "$RELDIR/{APP_NAME}.app" ]; then mv "$app" "$RELDIR/{APP_NAME}.app"; fi\n'
          f'          APP="$RELDIR/{APP_NAME}.app"\n'
          '          EXE="$(/usr/libexec/PlistBuddy -c \'Print :CFBundleExecutable\' "$APP/Contents/Info.plist" 2>/dev/null || echo rustdesk)"\n'
          f'          if [ "$EXE" != "{APP_NAME}" ] && [ -f "$APP/Contents/MacOS/$EXE" ]; then mv "$APP/Contents/MacOS/$EXE" "$APP/Contents/MacOS/{APP_NAME}"; /usr/libexec/PlistBuddy -c "Set :CFBundleExecutable \'{APP_NAME}\'" "$APP/Contents/Info.plist"; fi\n')
    patch(".github/workflows/flutter-build.yml",
          'create-dmg --icon "RustDesk.app" 200 190 --hide-extension "RustDesk.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{ env.VERSION }}-${{ matrix.job.arch }}.dmg ./flutter/build/macos/Build/Products/Release/RustDesk.app',
          f'create-dmg --volname "{BRAND}" --icon "{APP_NAME}.app" 200 190 --hide-extension "{APP_NAME}.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{{{ env.VERSION }}}}-${{{{ matrix.job.arch }}}}.dmg "./flutter/build/macos/Build/Products/Release/{APP_NAME}.app"')
    patch(".github/workflows/flutter-build.yml",
          'codesign --force --options runtime -s "${{ secrets.MACOS_CODESIGN_IDENTITY }}" --deep --strict ./flutter/build/macos/Build/Products/Release/RustDesk.app -vvv',
          f'codesign --force --options runtime -s "${{{{ secrets.MACOS_CODESIGN_IDENTITY }}}}" --deep --strict "./flutter/build/macos/Build/Products/Release/{APP_NAME}.app" -vvv')
    patch(".github/workflows/flutter-build.yml",
          'create-dmg --icon "RustDesk.app" 200 190 --hide-extension "RustDesk.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{ env.VERSION }}.dmg ./flutter/build/macos/Build/Products/Release/RustDesk.app',
          f'create-dmg --volname "{BRAND}" --icon "{APP_NAME}.app" 200 190 --hide-extension "{APP_NAME}.app" --window-size 800 400 --app-drop-link 600 185 rustdesk-${{{{ env.VERSION }}}}.dmg "./flutter/build/macos/Build/Products/Release/{APP_NAME}.app"')
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
