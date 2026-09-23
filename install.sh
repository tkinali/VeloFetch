#!/bin/bash
#
# VeloFetch - Kurulum / Kaldırma Scripti
# Tüm Linux dağıtımlarında çalışır
#
# Kullanım:
#   ./install.sh              - Kurulum
#   ./install.sh --uninstall  - Tamamen kaldırma
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

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

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
    local reply
    if [ "$default" = "y" ]; then
        read -p "  $prompt (E/h): " reply
        reply="${reply:-E}"
    else
        read -p "  $prompt (e/H): " reply
        reply="${reply:-H}"
    fi
    [[ "$reply" =~ ^[eE]$ ]]
}

# ═══════════════════════════════════════════════════════════════
#  KURULUM
# ═══════════════════════════════════════════════════════════════

do_install() {
    print_header
    echo "  Sistem kontrol ediliyor..."
    check_python
    echo ""
    echo "  Kurulum yapılıyor..."
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
        print_error "Python3 bulunamadı!"
        echo "  Lütfen Python 3.8 veya üzeri kurun."
        exit 1
    fi
    PYTHON_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        print_error "Python 3.8+ gerekli. Bulunan: $PYTHON_VERSION"
        exit 1
    fi
    print_step "Python $PYTHON_VERSION bulundu"
}

create_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        $PYTHON -m venv "$VENV_DIR"
        print_step "Sanal ortam oluşturuldu"
    else
        print_step "Sanal ortam mevcut"
    fi
}

install_deps() {
    "$VENV_DIR/bin/pip" install -q --upgrade pip
    "$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"
    print_step "Bağımlılıklar kuruldu"
}

install_app() {
    "$VENV_DIR/bin/pip" install -q -e "$APP_DIR"
    print_step "Uygulama kuruldu"
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
    print_step "İkonlar kuruldu (velofetch)"
}

create_launcher() {
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/$APP_ID" << LAUNCHER
#!/bin/bash
cd "$APP_DIR"
"$VENV_DIR/bin/python" -m vf "\$@"
LAUNCHER
    chmod +x "$BIN_DIR/$APP_ID"
    print_step "Başlatıcı: $BIN_DIR/$APP_ID"
}

create_desktop_entry() {
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/velofetch.desktop" << DESKTOP
[Desktop Entry]
Name=VeloFetch
GenericName=Download Manager
Comment=Hafif ve özellikli indirme yöneticisi
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
    print_step "Masaüstü kısayolu oluşturuldu"
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
        print_step "Yapılandırma oluşturuldu"
    else
        print_step "Yapılandırma mevcut"
    fi

    # Loading the config mints and persists the API token when it is missing,
    # so the local server is never open.
    "$VENV_DIR/bin/python" -c "from vf.core.config import Config; Config()" \
        >/dev/null 2>&1 || print_warning "API anahtarı oluşturulamadı"
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
        print_warning "API anahtarı okunamadı, eklentiler anahtarsız hazırlandı"
    fi
    print_step "Eklentiler hazırlandı: $STAGE_DIR"
}

# ═══════════════════════════════════════════════════════════════
#  FIREFOX EKLENTİ KURULUMU
# ═══════════════════════════════════════════════════════════════

install_firefox_extension() {
    echo -e "\n  ${CYAN}── Firefox Eklentisi ──${NC}"

    # Check if Firefox is installed
    local firefox_found=false
    if command -v firefox &> /dev/null || [ -d "$HOME/.mozilla/firefox" ]; then
        firefox_found=true
    fi

    if [ "$firefox_found" = false ]; then
        print_info "Firefox bulunamadı, atlanıyor"
        return
    fi

    if ! ask_yes_no "Firefox'e VeloFetch eklentisi kurulsun mu?"; then
        print_info "Firefox eklentisi atlandı"
        return
    fi

    echo ""

    # Find Firefox profiles
    local profiles_ini="$HOME/.mozilla/firefox/profiles.ini"
    if [ ! -f "$profiles_ini" ]; then
        print_warning "Firefox profil dizini bulunamadı"
        print_info "Firefox'i bir kez açıp kapatın, tekrar deneyin"
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
        print_warning "Firefox profil dizini bulunamadı"
        print_info "Firefox'i bir kez açıp kapatın, tekrar deneyin"
        return
    fi

    print_step "Firefox profili: $(basename "$profile_dir")"

    # Create extensions directory
    local extensions_dir="$profile_dir/extensions"
    mkdir -p "$extensions_dir"

    # Generate extension ID (hash of the directory path)
    local ext_id="velofetch@local"
    local ext_id_file="$extensions_dir/$ext_id.xpi"

    # Package the STAGED extension (the one carrying the token) as .xpi
    if [ ! -d "$STAGE_DIR/firefox" ]; then
        print_warning "Hazırlanmış eklenti bulunamadı, atlanıyor"
        return 0
    fi

    if ! command -v zip &> /dev/null; then
        print_warning "zip komutu bulunamadı, .xpi paketi oluşturulamadı"
        print_info "Geçici kurulum: ${CYAN}about:debugging#/runtime/this-firefox${NC} →"
        print_info "\"Geçici Eklenti Yükle\" → $STAGE_DIR/firefox/manifest.json"
        return 0
    fi

    # The .xpi carries token.js with the real API token, so it must never sit
    # in a shared /tmp under a PID-guessable name with the umask's 0644: build
    # it inside a private mktemp directory, under umask 077.
    local tmp_dir
    if ! tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/velofetch-xpi-XXXXXX"); then
        print_warning "Geçici klasör oluşturulamadı, atlanıyor"
        return 0
    fi
    chmod 700 "$tmp_dir" 2>/dev/null || true

    local tmp_xpi="$tmp_dir/velofetch.xpi"
    if ! (umask 077 && cd "$STAGE_DIR/firefox" && \
          zip -q -r "$tmp_xpi" manifest.json background.js token.js icons/ -x "*.DS_Store"); then
        print_warning "Eklenti paketlenemedi, atlanıyor"
        rm -rf "$tmp_dir"
        return 0
    fi

    # Copy to extensions directory
    cp "$tmp_xpi" "$ext_id_file"
    rm -rf "$tmp_dir"
    chmod 600 "$ext_id_file" 2>/dev/null || true

    print_step "Eklenti Firefox profiline kopyalandı"
    echo ""
    echo -e "  ${YELLOW}⚠ İmzasız eklentiler release Firefox'ta otomatik yüklenmez.${NC}"
    echo -e "  Kalıcı kurulum için yer imi (bookmarklet) önerilir:"
    echo -e "  Uygulama açıkken ${CYAN}vf integration${NC} komutunun yazdırdığı adresi açın."
    echo -e "  Geçici kurulum: ${CYAN}about:debugging#/runtime/this-firefox${NC} →"
    echo -e "  \"Geçici Eklenti Yükle\" → ${GREEN}$STAGE_DIR/firefox/manifest.json${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  CHROME / CHROMIUM EKLENTİ KURULUMU
# ═══════════════════════════════════════════════════════════════

install_chrome_extension() {
    echo -e "\n  ${CYAN}── Chrome / Chromium Eklentisi ──${NC}"

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
        print_info "Chrome/Chromium tabanlı tarayıcı bulunamadı, atlanıyor"
        return
    fi

    echo ""
    for i in "${!chrome_names[@]}"; do
        echo -e "    ${GREEN}$((i+1)).${NC} ${chrome_names[$i]}"
    done
    echo -e "    ${RED}H.${NC} Atla"
    echo ""
    read -p "  Hangi tarayıcıya eklenti kurulsun? (numara veya H): " choice || choice="H"

    if [[ "$choice" =~ ^[hH]$ ]] || [ -z "$choice" ]; then
        print_info "Chrome eklentisi atlandı"
        return
    fi

    # Validate choice
    local idx=$((choice - 1))
    if [ "$idx" -lt 0 ] || [ "$idx" -ge ${#chrome_browsers[@]} ]; then
        print_warning "Geçersiz seçim, atlanıyor"
        return
    fi

    local browser_dir="${chrome_browsers[$idx]}"
    local browser_name="${chrome_names[$idx]}"

    echo ""
    echo -e "  Seçilen: ${GREEN}$browser_name${NC}"

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
        print_info "Tarayıcıda chrome://extensions sayfası açıldı"
    fi
    install_chrome_manual "$browser_name" "$STAGE_DIR/chromium"
}

install_chrome_manual() {
    local browser_name="$1"
    local ext_path="$2"

    echo ""
    echo -e "  ${CYAN}$browser_name için Manuel Kurulum:${NC}"
    echo ""
    echo -e "    1. ${CYAN}$browser_name${NC} açın"
    echo -e "    2. Adres çubuğuna ${CYAN}chrome://extensions${NC} yazın"
    echo -e "    3. ${CYAN}\"Developer mode\"${NC} açın (sağ üst)"
    echo -e "    4. ${CYAN}\"Load unpacked\"${NC} tıklayın (sol üst)"
    echo -e "    5. Şu klasörü seçin (API anahtarı bu kopyada):"
    echo -e "       ${GREEN}$ext_path${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  ÖZET
# ═══════════════════════════════════════════════════════════════

print_summary() {
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  ✅ ${GREEN}Kurulum Tamamlandı!${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Uygulamayı başlatmak için:"
    echo -e "    ${CYAN}vf${NC}"
    echo ""
    echo -e "  Tarayıcı entegrasyonu (yer imi):"
    echo -e "    Uygulama açıkken ${CYAN}vf integration${NC} — yazdırdığı adresi tarayıcıda açın"
    echo -e "    (sayfa token içerdiği için adres token ile korunur)"
    echo ""
    echo -e "  Tarayıcı eklentileri (API anahtarı içeren kopyalar):"
    echo -e "    ${GREEN}$STAGE_DIR/chromium${NC}"
    echo -e "    ${GREEN}$STAGE_DIR/firefox${NC}"
    echo -e "    ${YELLOW}Depodaki browser/ klasörü anahtar içermez, onu yüklemeyin.${NC}"
    echo ""
    echo -e "  Kaldırmak için:"
    echo -e "    ${YELLOW}./install.sh --uninstall${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  KALDIRMA
# ═══════════════════════════════════════════════════════════════

do_uninstall() {
    print_header
    echo -e "  ${YELLOW}Uygulama tamamen kaldırılacak.${NC}"
    echo ""
    read -p "  Devam etmek istiyor musunuz? (e/H): " confirm || confirm="H"
    if [[ ! "$confirm" =~ ^[eE]$ ]]; then
        echo "  Kaldırma iptal edildi."
        exit 0
    fi
    echo ""
    echo "  Kaldırılıyor..."

    [ -f "$BIN_DIR/$APP_ID" ] && rm -f "$BIN_DIR/$APP_ID" && print_step "Başlatıcı silindi"
    [ -f "$DESKTOP_DIR/velofetch.desktop" ] && rm -f "$DESKTOP_DIR/velofetch.desktop" && print_step "Desktop entry silindi"

    # Mirror exactly what install_icon writes, plus the legacy layout
    for size in 16 32 48 64 128 256; do
        rm -f "$ICON_DIR/hicolor/${size}x${size}/apps/velofetch.png"
        rm -f "$ICON_DIR/${size}x${size}/apps/$APP_ID.png"
    done
    rm -f "$ICON_DIR/scalable/apps/$APP_ID.svg" "$ICON_DIR/scalable/apps/velofetch.svg"
    if command -v gtk-update-icon-cache &> /dev/null; then
        gtk-update-icon-cache -f -t "$ICON_DIR/hicolor" 2>/dev/null || true
    fi
    print_step "İkonlar silindi"

    # Staged browser extensions (they carry the API token)
    if [ -d "$STAGE_DIR" ]; then
        rm -rf "${STAGE_DIR:?}"
        rmdir "$HOME/.local/share/velofetch" 2>/dev/null || true
        print_step "Tarayıcı eklenti kopyaları silindi"
    fi

    # Remove Firefox extension
    local profiles_ini="$HOME/.mozilla/firefox/profiles.ini"
    if [ -f "$profiles_ini" ]; then
        local ext_id="velofetch@local"
        find "$HOME/.mozilla/firefox" -path "*/extensions/$ext_id.xpi" -delete 2>/dev/null || true
        print_step "Firefox eklentisi silindi"
    fi

    [ -d "$CONFIG_DIR" ] && rm -rf "$CONFIG_DIR" && print_step "Yapılandırma silindi"
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR" && print_step "Sanal ortam silindi"

    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi

    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  🗑️  ${GREEN}Kaldırma Tamamlandı!${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
#  ANA AKIŞ
# ═══════════════════════════════════════════════════════════════

case "${1:-}" in
    --uninstall|-u) do_uninstall ;;
    --help|-h)
        echo "Kullanım:"
        echo "  ./install.sh              VeloFetch'i kur"
        echo "  ./install.sh --uninstall  VeloFetch'i tamamen kaldır"
        echo "  ./install.sh --help       Bu mesajı göster"
        ;;
    *) do_install ;;
esac
