#!/bin/bash
#
# VeloFetch — installer / uninstaller
# Works on any Linux distribution.
#
# Usage:
#   ./install.sh              install
#   ./install.sh --uninstall  remove completely
#   ./install.sh --lang=en    force a language (en | tr)
#
# The interface follows your system locale, like the app itself.
#

set -e

APP_NAME="VeloFetch"
APP_ID="vf"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/velofetch"
ICON_DIR="$HOME/.local/share/icons"
DESKTOP_DIR="$HOME/.local/share/applications"
VENV_DIR="$APP_DIR/venv"
# Token-bearing copies of the browser extensions live here, never in the repo.
STAGE_DIR="$HOME/.local/share/velofetch/browser"

# Lowest Python the package itself accepts (pyproject: requires-python).
PY_MIN_MAJOR=3
PY_MIN_MINOR=10

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ═══════════════════════════════════════════════════════════════
#  LANGUAGE
#  Mirrors vf/i18n.py: follow the system locale, fall back to English.
#  Add a language by adding one array and one case branch.
# ═══════════════════════════════════════════════════════════════

VF_LANG=""
for arg in "$@"; do
    case "$arg" in
        --lang=*) VF_LANG="${arg#--lang=}" ;;
    esac
done
if [ -z "$VF_LANG" ]; then
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
        tr*|TR*) VF_LANG=tr ;;
        *)       VF_LANG=en ;;
    esac
fi
[ "$VF_LANG" = "tr" ] || VF_LANG=en

declare -A MSG_EN=(
    [checking]="Checking your system..."
    [installing]="Installing..."
    [py_missing]="Python 3 not found."
    [py_hint]="Please install Python %s.%s or newer."
    [py_old]="Python %s.%s+ required. Found: %s"
    [py_found]="Python %s found"
    [venv_new]="Virtual environment created"
    [venv_old]="Virtual environment already present"
    [deps]="Dependencies installed"
    [app]="Application installed"
    [icons]="Icons installed (velofetch)"
    [launcher]="Launcher: %s"
    [desktop]="Application menu entry created"
    [cfg_new]="Configuration created"
    [cfg_old]="Configuration already present"
    [token_fail]="Could not generate the API token"
    [ext_staged]="Extensions prepared: %s"
    [ext_no_token]="Could not read the API token; extensions prepared without one"
    [noninteractive]="No terminal available, so this was skipped: %s"

    [fx_title]="Firefox extension"
    [fx_missing]="Firefox not found, skipping"
    [fx_ask]="Install the VeloFetch extension into Firefox?"
    [fx_skip]="Firefox extension skipped"
    [fx_no_profile]="Firefox profile directory not found"
    [fx_profile_hint]="Open and close Firefox once, then try again"
    [fx_profile]="Firefox profile: %s"
    [fx_no_stage]="Prepared extension not found, skipping"
    [fx_no_zip]="'zip' command not found, the .xpi could not be built"
    [fx_temp1]="Temporary install: %s →"
    [fx_temp2]="\"Load Temporary Add-on\" → %s"
    [fx_no_tmp]="Could not create a temporary directory, skipping"
    [fx_zip_fail]="Could not package the extension, skipping"
    [fx_copied]="Extension copied into the Firefox profile"
    [fx_unsigned]="Unsigned add-ons are not loaded automatically by release Firefox."
    [fx_bm1]="For a permanent setup the bookmarklet is recommended:"
    [fx_bm2]="With the app running, open the URL printed by %s"

    [cr_title]="Chrome / Chromium extension"
    [cr_none]="No Chrome-based browser found, skipping"
    [cr_skip_label]="Skip"
    [cr_prompt]="Which browser should it be installed into? (number or S): "
    [cr_skipped]="Chrome extension skipped"
    [cr_invalid]="Invalid choice, skipping"
    [cr_selected]="Selected: %s"
    [cr_opened]="Opened chrome://extensions in the browser"
    [cr_manual]="Manual setup for %s:"
    [cr_s1]="Open %s"
    [cr_s2]="Type %s into the address bar"
    [cr_s3]="Turn on %s (top right)"
    [cr_s4]="Click %s (top left)"
    [cr_s5]="Pick this folder (the API token lives in this copy):"

    [sum_done]="Installation complete!"
    [sum_start]="To start the application:"
    [sum_bm_title]="Browser integration (bookmarklet):"
    [sum_bm1]="With the app running, run %s and open the URL it prints"
    [sum_bm2]="(the page embeds your token, so the URL is token-protected)"
    [sum_ext_title]="Browser extensions (the copies holding your API token):"
    [sum_ext_warn]="The browser/ folder in the repository holds no token — do not load that one."
    [sum_uninstall]="To remove it again:"

    [un_warn]="The application will be removed completely."
    [un_confirm]="Do you want to continue?"
    [un_cancel]="Uninstall cancelled."
    [un_running]="Removing..."
    [un_launcher]="Launcher removed"
    [un_desktop]="Application menu entry removed"
    [un_icons]="Icons removed"
    [un_ext]="Staged browser extensions removed"
    [un_firefox]="Firefox extension removed"
    [un_config]="Configuration removed"
    [un_venv]="Virtual environment removed"
    [un_done]="Removal complete!"

    [help_usage]="Usage:"
    [help_install]="  ./install.sh              install VeloFetch"
    [help_uninstall]="  ./install.sh --uninstall  remove VeloFetch completely"
    [help_lang]="  ./install.sh --lang=tr    force a language (en | tr)"
    [help_help]="  ./install.sh --help       show this message"
)

declare -A MSG_TR=(
    [checking]="Sistem kontrol ediliyor..."
    [installing]="Kurulum yapılıyor..."
    [py_missing]="Python 3 bulunamadı."
    [py_hint]="Lütfen Python %s.%s veya üzerini kurun."
    [py_old]="Python %s.%s+ gerekli. Bulunan: %s"
    [py_found]="Python %s bulundu"
    [venv_new]="Sanal ortam oluşturuldu"
    [venv_old]="Sanal ortam zaten var"
    [deps]="Bağımlılıklar kuruldu"
    [app]="Uygulama kuruldu"
    [icons]="İkonlar kuruldu (velofetch)"
    [launcher]="Başlatıcı: %s"
    [desktop]="Uygulama menüsü girdisi oluşturuldu"
    [cfg_new]="Yapılandırma oluşturuldu"
    [cfg_old]="Yapılandırma zaten var"
    [token_fail]="API anahtarı oluşturulamadı"
    [ext_staged]="Eklentiler hazırlandı: %s"
    [ext_no_token]="API anahtarı okunamadı, eklentiler anahtarsız hazırlandı"
    [noninteractive]="Terminal yok, bu adım atlandı: %s"

    [fx_title]="Firefox eklentisi"
    [fx_missing]="Firefox bulunamadı, atlanıyor"
    [fx_ask]="Firefox'e VeloFetch eklentisi kurulsun mu?"
    [fx_skip]="Firefox eklentisi atlandı"
    [fx_no_profile]="Firefox profil dizini bulunamadı"
    [fx_profile_hint]="Firefox'u bir kez açıp kapatın, sonra tekrar deneyin"
    [fx_profile]="Firefox profili: %s"
    [fx_no_stage]="Hazırlanmış eklenti bulunamadı, atlanıyor"
    [fx_no_zip]="'zip' komutu bulunamadı, .xpi paketi oluşturulamadı"
    [fx_temp1]="Geçici kurulum: %s →"
    [fx_temp2]="\"Geçici Eklenti Yükle\" → %s"
    [fx_no_tmp]="Geçici klasör oluşturulamadı, atlanıyor"
    [fx_zip_fail]="Eklenti paketlenemedi, atlanıyor"
    [fx_copied]="Eklenti Firefox profiline kopyalandı"
    [fx_unsigned]="Yayın sürümü Firefox imzasız eklentileri otomatik yüklemez."
    [fx_bm1]="Kalıcı çözüm için yer imi (bookmarklet) önerilir:"
    [fx_bm2]="Uygulama açıkken %s komutunun yazdırdığı adresi açın"

    [cr_title]="Chrome / Chromium eklentisi"
    [cr_none]="Chrome tabanlı tarayıcı bulunamadı, atlanıyor"
    [cr_skip_label]="Atla"
    [cr_prompt]="Hangi tarayıcıya kurulsun? (numara veya A): "
    [cr_skipped]="Chrome eklentisi atlandı"
    [cr_invalid]="Geçersiz seçim, atlanıyor"
    [cr_selected]="Seçilen: %s"
    [cr_opened]="Tarayıcıda chrome://extensions sayfası açıldı"
    [cr_manual]="%s için elle kurulum:"
    [cr_s1]="%s tarayıcısını açın"
    [cr_s2]="Adres çubuğuna %s yazın"
    [cr_s3]="%s seçeneğini açın (sağ üst)"
    [cr_s4]="%s düğmesine tıklayın (sol üst)"
    [cr_s5]="Şu klasörü seçin (API anahtarı bu kopyada):"

    [sum_done]="Kurulum tamamlandı!"
    [sum_start]="Uygulamayı başlatmak için:"
    [sum_bm_title]="Tarayıcı entegrasyonu (yer imi):"
    [sum_bm1]="Uygulama açıkken %s komutunu çalıştırın, yazdırdığı adresi açın"
    [sum_bm2]="(sayfa anahtarınızı gömdüğü için adres anahtarla korunur)"
    [sum_ext_title]="Tarayıcı eklentileri (API anahtarınızı taşıyan kopyalar):"
    [sum_ext_warn]="Depodaki browser/ klasörü anahtar taşımaz, onu yüklemeyin."
    [sum_uninstall]="Kaldırmak için:"

    [un_warn]="Uygulama tamamen kaldırılacak."
    [un_confirm]="Devam etmek istiyor musunuz?"
    [un_cancel]="Kaldırma iptal edildi."
    [un_running]="Kaldırılıyor..."
    [un_launcher]="Başlatıcı silindi"
    [un_desktop]="Uygulama menüsü girdisi silindi"
    [un_icons]="İkonlar silindi"
    [un_ext]="Hazırlanmış tarayıcı eklentileri silindi"
    [un_firefox]="Firefox eklentisi silindi"
    [un_config]="Yapılandırma silindi"
    [un_venv]="Sanal ortam silindi"
    [un_done]="Kaldırma tamamlandı!"

    [help_usage]="Kullanım:"
    [help_install]="  ./install.sh              VeloFetch'i kurar"
    [help_uninstall]="  ./install.sh --uninstall  VeloFetch'i tamamen kaldırır"
    [help_lang]="  ./install.sh --lang=en    dili sabitler (en | tr)"
    [help_help]="  ./install.sh --help       bu mesajı gösterir"
)

# msg <key> [printf args...] — active language, falling back to English.
msg() {
    local key="$1"; shift
    local text="${MSG_EN[$key]}"
    if [ "$VF_LANG" = "tr" ] && [ -n "${MSG_TR[$key]+set}" ]; then
        text="${MSG_TR[$key]}"
    fi
    if [ "$#" -gt 0 ]; then
        # shellcheck disable=SC2059  # the format string is ours, not user input
        printf "$text" "$@"
    else
        printf '%s' "$text"
    fi
}

print_header() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  🚀 ${GREEN}$APP_NAME${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() { echo -e "  ${GREEN}✓${NC} $1"; }
print_warning() { echo -e "  ${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "  ${RED}✗${NC} $1"; }
print_info() { echo -e "  ${CYAN}ℹ${NC} $1"; }

ask_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local reply hint

    # Both languages' letters are accepted whichever language is showing: an
    # English speaker typing "y" at a Turkish prompt means yes, not no.
    if [ "$default" = "y" ]; then
        [ "$VF_LANG" = "tr" ] && hint="(E/h)" || hint="(Y/n)"
    else
        [ "$VF_LANG" = "tr" ] && hint="(e/H)" || hint="(y/N)"
    fi

    # A piped answer is honoured, so the installer stays scriptable. Only a
    # closed stdin falls back to the default — and says so, because silently
    # taking it once made the installer report success while skipping steps.
    if ! read -r -p "  $prompt $hint " reply; then
        echo ""
        print_info "$(msg noninteractive "$prompt")"
        [ "$default" = "y" ]
        return
    fi
    reply="${reply:-$default}"
    [[ "$reply" =~ ^([eEyY]|[eE]vet|[yY]es)$ ]]
}

# ═══════════════════════════════════════════════════════════════
#  KURULUM
# ═══════════════════════════════════════════════════════════════

do_install() {
    print_header
    echo "  $(msg checking)"
    check_python
    echo ""
    echo "  $(msg installing)"
    create_venv
    install_deps
    install_app
    install_icon
    create_launcher
    create_desktop_entry
    create_config
    echo ""

    # Browser extensions
    stage_extensions
    install_firefox_extension
    install_chrome_extension

    echo ""
    print_summary
}

check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON=python3
    elif command -v python &> /dev/null; then
        PYTHON=python
    else
        print_error "$(msg py_missing)"
        echo "  $(msg py_hint "$PY_MIN_MAJOR" "$PY_MIN_MINOR")"
        exit 1
    fi
    PYTHON_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')
    if [ "$PYTHON_MAJOR" -lt "$PY_MIN_MAJOR" ] || \
       { [ "$PYTHON_MAJOR" -eq "$PY_MIN_MAJOR" ] && [ "$PYTHON_MINOR" -lt "$PY_MIN_MINOR" ]; }; then
        print_error "$(msg py_old "$PY_MIN_MAJOR" "$PY_MIN_MINOR" "$PYTHON_VERSION")"
        exit 1
    fi
    print_step "$(msg py_found "$PYTHON_VERSION")"
}

create_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        $PYTHON -m venv "$VENV_DIR"
        print_step "$(msg venv_new)"
    else
        print_step "$(msg venv_old)"
    fi
}

install_deps() {
    "$VENV_DIR/bin/pip" install -q --upgrade pip
    "$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"
    print_step "$(msg deps)"
}

install_app() {
    "$VENV_DIR/bin/pip" install -q -e "$APP_DIR"
    print_step "$(msg app)"
}

install_icon() {
    # Theme-name based ("velofetch") under the hicolor layout — portable,
    # no absolute user paths in the desktop entry.
    for size in 16 32 48 64 128 256; do
        mkdir -p "$ICON_DIR/hicolor/${size}x${size}/apps"
        cp "$APP_DIR/vf/assets/icon-${size}.png" "$ICON_DIR/hicolor/${size}x${size}/apps/velofetch.png"
    done

    # Remove leftovers from older installs (legacy layout + old name/svg)
    for size in 16 32 48 64 128 256; do
        rm -f "$ICON_DIR/${size}x${size}/apps/$APP_ID.png"
    done
    rm -f "$ICON_DIR/scalable/apps/$APP_ID.svg" "$ICON_DIR/scalable/apps/velofetch.svg"

    if command -v gtk-update-icon-cache &> /dev/null; then
        gtk-update-icon-cache -f -t "$ICON_DIR/hicolor" 2>/dev/null || true
    fi
    print_step "$(msg icons)"
}

create_launcher() {
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/$APP_ID" << LAUNCHER
#!/bin/bash
cd "$APP_DIR"
"$VENV_DIR/bin/python" -m vf "\$@"
LAUNCHER
    chmod +x "$BIN_DIR/$APP_ID"
    print_step "$(msg launcher "$BIN_DIR/$APP_ID")"
}

create_desktop_entry() {
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/velofetch.desktop" << DESKTOP
[Desktop Entry]
Name=VeloFetch
GenericName=Download Manager
GenericName[tr]=İndirme Yöneticisi
Comment=A lightweight, feature-rich download manager
Comment[tr]=Hafif ve özellikli indirme yöneticisi
Exec=$BIN_DIR/$APP_ID %u
Icon=velofetch
Terminal=false
Type=Application
Categories=Network;FileTools;
Keywords=download;manager;internet;file;
StartupNotify=true
StartupWMClass=VeloFetch
MimeType=x-scheme-handler/vf;
DESKTOP
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi
    print_step "$(msg desktop)"
}

create_config() {
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$HOME/Downloads"

    if [ ! -f "$CONFIG_DIR/config.json" ]; then
        cat > "$CONFIG_DIR/config.json" << CONFIG
{
  "download_dir": "$HOME/Downloads",
  "max_concurrent": 3,
  "retry_count": 5,
  "retry_delay": 3,
  "chunk_size": 8192,
  "timeout": 30,
  "auto_rename": true,
  "overwrite_existing": false
}
CONFIG
        print_step "$(msg cfg_new)"
    else
        print_step "$(msg cfg_old)"
    fi

    # Loading the config mints and persists the API token when it is missing,
    # so the local server is never open.
    "$VENV_DIR/bin/python" -c "from vf.core.config import Config; Config()" \
        >/dev/null 2>&1 || print_warning "$(msg token_fail)"
    chmod 600 "$CONFIG_DIR/config.json" 2>/dev/null || true
}

read_api_token() {
    # Print the configured API token (empty when it cannot be read)
    "$VENV_DIR/bin/python" -c "
import json, os
path = os.path.expanduser('~/.config/velofetch/config.json')
try:
    print(json.load(open(path)).get('api_token', ''))
except Exception:
    print('')" 2>/dev/null || true
}

stage_extensions() {
    # The token must never be written into the tracked repo files (that is how
    # it leaked into git). Copy both bundles to a private staging directory and
    # patch only the staged token.js.
    local token
    token=$(read_api_token)

    mkdir -p "$STAGE_DIR"
    chmod 700 "$STAGE_DIR" 2>/dev/null || true

    local name
    for name in chromium firefox; do
        [ -d "$APP_DIR/browser/$name" ] || continue
        rm -rf "${STAGE_DIR:?}/$name"
        mkdir -p "$STAGE_DIR/$name"
        cp -r "$APP_DIR/browser/$name/." "$STAGE_DIR/$name/"
        cat > "$STAGE_DIR/$name/token.js" << TOKENJS
// Generated by install.sh — contains the local API token. Do not share.
self.VELFETCH_TOKEN = "$token";
TOKENJS
        chmod 600 "$STAGE_DIR/$name/token.js" 2>/dev/null || true
    done

    if [ -z "$token" ]; then
        print_warning "$(msg ext_no_token)"
    fi
    print_step "$(msg ext_staged "$STAGE_DIR")"
}

# ═══════════════════════════════════════════════════════════════
#  FIREFOX EKLENTİ KURULUMU
# ═══════════════════════════════════════════════════════════════

install_firefox_extension() {
    echo -e "\n  ${CYAN}── $(msg fx_title) ──${NC}"

    # Check if Firefox is installed
    local firefox_found=false
    if command -v firefox &> /dev/null || [ -d "$HOME/.mozilla/firefox" ]; then
        firefox_found=true
    fi

    if [ "$firefox_found" = false ]; then
        print_info "$(msg fx_missing)"
        return
    fi

    if ! ask_yes_no "$(msg fx_ask)"; then
        print_info "$(msg fx_skip)"
        return
    fi

    echo ""

    # Find Firefox profiles
    local profiles_ini="$HOME/.mozilla/firefox/profiles.ini"
    if [ ! -f "$profiles_ini" ]; then
        print_warning "$(msg fx_no_profile)"
        print_info "$(msg fx_profile_hint)"
        return
    fi

    # Parse profiles.ini to find profile directories
    local profile_dir=""
    local in_profile=false
    local is_relative=0
    local profile_path=""

    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^\[Profile ]]; then
            in_profile=true
            is_relative=0
            profile_path=""
        elif [[ "$line" =~ ^\[ ]] && [ "$in_profile" = true ]; then
            # End of profile section, check if it's default
            if [ -n "$profile_path" ]; then
                if [ "$is_relative" -eq 1 ]; then
                    profile_dir="$HOME/.mozilla/firefox/$profile_path"
                else
                    profile_dir="$profile_path"
                fi
                break
            fi
            in_profile=false
        elif [ "$in_profile" = true ]; then
            if [[ "$line" =~ ^Path= ]]; then
                profile_path="${line#Path=}"
            elif [[ "$line" =~ ^IsRelative= ]]; then
                is_relative="${line#IsRelative=}"
            elif [[ "$line" =~ ^Default=1 ]] || [[ "$line" =~ ^Default=true ]]; then
                # Found default profile, prefer this one
                if [ -n "$profile_path" ]; then
                    if [ "$is_relative" -eq 1 ]; then
                        profile_dir="$HOME/.mozilla/firefox/$profile_path"
                    else
                        profile_dir="$profile_path"
                    fi
                fi
            fi
        fi
    done < "$profiles_ini"

    # Fallback: use first profile found
    if [ -z "$profile_dir" ] || [ ! -d "$profile_dir" ]; then
        profile_dir=$(find "$HOME/.mozilla/firefox" -maxdepth 1 -type d -name "*.default*" | head -1)
    fi

    if [ -z "$profile_dir" ] || [ ! -d "$profile_dir" ]; then
        print_warning "$(msg fx_no_profile)"
        print_info "$(msg fx_profile_hint)"
        return
    fi

    print_step "$(msg fx_profile "$(basename "$profile_dir")")"

    # Create extensions directory
    local extensions_dir="$profile_dir/extensions"
    mkdir -p "$extensions_dir"

    # Generate extension ID (hash of the directory path)
    local ext_id="velofetch@local"
    local ext_id_file="$extensions_dir/$ext_id.xpi"

    # Package the STAGED extension (the one carrying the token) as .xpi
    if [ ! -d "$STAGE_DIR/firefox" ]; then
        print_warning "$(msg fx_no_stage)"
        return 0
    fi

    if ! command -v zip &> /dev/null; then
        print_warning "$(msg fx_no_zip)"
        print_info "$(msg fx_temp1 "${CYAN}about:debugging#/runtime/this-firefox${NC}")"
        print_info "$(msg fx_temp2 "$STAGE_DIR/firefox/manifest.json")"
        return 0
    fi

    # The .xpi carries token.js with the real API token, so it must never sit
    # in a shared /tmp under a PID-guessable name with the umask's 0644: build
    # it inside a private mktemp directory, under umask 077.
    local tmp_dir
    if ! tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/velofetch-xpi-XXXXXX"); then
        print_warning "$(msg fx_no_tmp)"
        return 0
    fi
    chmod 700 "$tmp_dir" 2>/dev/null || true

    local tmp_xpi="$tmp_dir/velofetch.xpi"
    if ! (umask 077 && cd "$STAGE_DIR/firefox" && \
          zip -q -r "$tmp_xpi" manifest.json background.js token.js icons/ -x "*.DS_Store"); then
        print_warning "$(msg fx_zip_fail)"
        rm -rf "$tmp_dir"
        return 0
    fi

    # Copy to extensions directory
    cp "$tmp_xpi" "$ext_id_file"
    rm -rf "$tmp_dir"
    chmod 600 "$ext_id_file" 2>/dev/null || true

    print_step "$(msg fx_copied)"
    echo ""
    echo -e "  ${YELLOW}⚠ $(msg fx_unsigned)${NC}"
    echo -e "  $(msg fx_bm1)"
    echo -e "  $(msg fx_bm2 "${CYAN}vf integration${NC}")"
    echo -e "  $(msg fx_temp1 "${CYAN}about:debugging#/runtime/this-firefox${NC}")"
    echo -e "  $(msg fx_temp2 "${GREEN}$STAGE_DIR/firefox/manifest.json${NC}")"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  CHROME / CHROMIUM EKLENTİ KURULUMU
# ═══════════════════════════════════════════════════════════════

install_chrome_extension() {
    echo -e "\n  ${CYAN}── $(msg cr_title) ──${NC}"

    # Find Chrome-based browsers
    local chrome_browsers=()
    local chrome_names=()

    for dir in \
        "$HOME/.config/google-chrome" \
        "$HOME/.config/chromium" \
        "$HOME/.config/vivaldi" \
        "$HOME/.config/BraveSoftware/Brave-Browser"; do
        if [ -d "$dir" ]; then
            local name=$(basename "$dir")
            case "$name" in
                "google-chrome") name="Google Chrome" ;;
                "chromium") name="Chromium" ;;
                "vivaldi") name="Vivaldi" ;;
                "Brave-Browser") name="Brave" ;;
            esac
            chrome_browsers+=("$dir")
            chrome_names+=("$name")
        fi
    done

    if [ ${#chrome_browsers[@]} -eq 0 ]; then
        print_info "$(msg cr_none)"
        return
    fi

    echo ""
    for i in "${!chrome_names[@]}"; do
        echo -e "    ${GREEN}$((i+1)).${NC} ${chrome_names[$i]}"
    done
    echo -e "    ${RED}S.${NC} $(msg cr_skip_label)"
    echo ""
    if ! read -r -p "  $(msg cr_prompt)" choice; then
        echo ""
        choice="s"
        print_info "$(msg noninteractive "$(msg cr_prompt)")"
    fi

    # s = skip / a = atla, and h/n for anyone reaching for the old key
    if [[ "$choice" =~ ^[sSaAhHnN]$ ]] || [ -z "$choice" ]; then
        print_info "$(msg cr_skipped)"
        return
    fi

    # Validate choice
    local idx=$((choice - 1))
    if [ "$idx" -lt 0 ] || [ "$idx" -ge ${#chrome_browsers[@]} ]; then
        print_warning "$(msg cr_invalid)"
        return
    fi

    local browser_dir="${chrome_browsers[$idx]}"
    local browser_name="${chrome_names[$idx]}"

    echo ""
    echo -e "  $(msg cr_selected "${GREEN}$browser_name${NC}")"

    # ── Method 1: Enterprise policy (silent install, needs sudo) ──
    echo ""
    # Local-folder extensions cannot be force-installed via enterprise policy;
    # guide the user through Developer mode and open the right page for them.
    local bin_name=""
    case "$browser_name" in
        "Google Chrome") bin_name="google-chrome" ;;
        "Chromium") bin_name="chromium" ;;
        "Brave") bin_name="brave-browser" ;;
    esac
    if [ -n "$bin_name" ] && command -v "$bin_name" &> /dev/null; then
        "$bin_name" "chrome://extensions/" >/dev/null 2>&1 &
        print_info "$(msg cr_opened)"
    fi
    install_chrome_manual "$browser_name" "$STAGE_DIR/chromium"
}

install_chrome_manual() {
    local browser_name="$1"
    local ext_path="$2"

    echo ""
    echo -e "  ${CYAN}$(msg cr_manual "$browser_name")${NC}"
    echo ""
    echo -e "    1. $(msg cr_s1 "${CYAN}$browser_name${NC}")"
    echo -e "    2. $(msg cr_s2 "${CYAN}chrome://extensions${NC}")"
    echo -e "    3. $(msg cr_s3 "${CYAN}\"Developer mode\"${NC}")"
    echo -e "    4. $(msg cr_s4 "${CYAN}\"Load unpacked\"${NC}")"
    echo -e "    5. $(msg cr_s5)"
    echo -e "       ${GREEN}$ext_path${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  ÖZET
# ═══════════════════════════════════════════════════════════════

print_summary() {
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  ✅ ${GREEN}$(msg sum_done)${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  $(msg sum_start)"
    echo -e "    ${CYAN}vf${NC}"
    echo ""
    echo -e "  $(msg sum_bm_title)"
    echo -e "    $(msg sum_bm1 "${CYAN}vf integration${NC}")"
    echo -e "    $(msg sum_bm2)"
    echo ""
    echo -e "  $(msg sum_ext_title)"
    echo -e "    ${GREEN}$STAGE_DIR/chromium${NC}"
    echo -e "    ${GREEN}$STAGE_DIR/firefox${NC}"
    echo -e "    ${YELLOW}$(msg sum_ext_warn)${NC}"
    echo ""
    echo -e "  $(msg sum_uninstall)"
    echo -e "    ${YELLOW}./install.sh --uninstall${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  KALDIRMA
# ═══════════════════════════════════════════════════════════════

do_uninstall() {
    print_header
    echo -e "  ${YELLOW}$(msg un_warn)${NC}"
    echo ""
    if ! ask_yes_no "$(msg un_confirm)"; then
        echo "  $(msg un_cancel)"
        exit 0
    fi
    echo ""
    echo "  $(msg un_running)"

    [ -f "$BIN_DIR/$APP_ID" ] && rm -f "$BIN_DIR/$APP_ID" && print_step "$(msg un_launcher)"
    [ -f "$DESKTOP_DIR/velofetch.desktop" ] && rm -f "$DESKTOP_DIR/velofetch.desktop" && print_step "$(msg un_desktop)"

    # Mirror exactly what install_icon writes, plus the legacy layout
    for size in 16 32 48 64 128 256; do
        rm -f "$ICON_DIR/hicolor/${size}x${size}/apps/velofetch.png"
        rm -f "$ICON_DIR/${size}x${size}/apps/$APP_ID.png"
    done
    rm -f "$ICON_DIR/scalable/apps/$APP_ID.svg" "$ICON_DIR/scalable/apps/velofetch.svg"
    if command -v gtk-update-icon-cache &> /dev/null; then
        gtk-update-icon-cache -f -t "$ICON_DIR/hicolor" 2>/dev/null || true
    fi
    print_step "$(msg un_icons)"

    # Staged browser extensions (they carry the API token)
    if [ -d "$STAGE_DIR" ]; then
        rm -rf "${STAGE_DIR:?}"
        rmdir "$HOME/.local/share/velofetch" 2>/dev/null || true
        print_step "$(msg un_ext)"
    fi

    # Remove Firefox extension
    local profiles_ini="$HOME/.mozilla/firefox/profiles.ini"
    if [ -f "$profiles_ini" ]; then
        local ext_id="velofetch@local"
        find "$HOME/.mozilla/firefox" -path "*/extensions/$ext_id.xpi" -delete 2>/dev/null || true
        print_step "$(msg un_firefox)"
    fi

    [ -d "$CONFIG_DIR" ] && rm -rf "$CONFIG_DIR" && print_step "$(msg un_config)"
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR" && print_step "$(msg un_venv)"

    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi

    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  🗑️  ${GREEN}$(msg un_done)${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  ANA AKIŞ
# ═══════════════════════════════════════════════════════════════

ACTION="install"
for arg in "$@"; do
    case "$arg" in
        --uninstall|-u) ACTION="uninstall" ;;
        --help|-h)      ACTION="help" ;;
        --lang=*)       ;;  # already consumed by the language detection above
        *) if [ -n "$arg" ]; then
               print_error "Unknown option: $arg"
               ACTION="help"
           fi ;;
    esac
done

case "$ACTION" in
    uninstall) do_uninstall ;;
    help)
        echo "$(msg help_usage)"
        echo "$(msg help_install)"
        echo "$(msg help_uninstall)"
        echo "$(msg help_lang)"
        echo "$(msg help_help)"
        ;;
    *) do_install ;;
esac
