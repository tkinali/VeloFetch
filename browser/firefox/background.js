// VeloFetch Browser Extension - Background Script
// Adds "Download with VeloFetch" to context menu and sends URL + cookies to local server

// The API token lives in token.js, loaded first by background.scripts in
// manifest.json (MV2 background pages have no importScripts). install.sh
// fills it in for the staged copy; it is never stored in this file.
const VELFETCH_PORT = 9876;
const VELFETCH_URL = `http://127.0.0.1:${VELFETCH_PORT}`;
const VELFETCH_TOKEN = (typeof self !== "undefined" && self.VELFETCH_TOKEN) || "";

// Menu entries and notifications follow the browser's UI language, the same way
// the desktop app follows the system locale. Add a language by adding a pack.
const VELOFETCH_STRINGS = {
  en: {
    download: "\u{1F4E5} Download with VeloFetch",
    downloadVideo: "\u{1F3AC} Download video with VeloFetch",
    added: "Download added",
    errorPrefix: "Error: ",
    notRunning: "VeloFetch may not be running.\nStart it with: vf",
    tokenHelp:
      "This is the repository copy, which carries no token; requests are rejected.\n" +
      "Run ./install.sh first, then load this folder instead:\n" +
      "~/.local/share/velofetch/browser/firefox"
  },
  tr: {
    download: "\u{1F4E5} VeloFetch ile \u0130ndir",
    downloadVideo: "\u{1F3AC} VeloFetch ile Video \u0130ndir",
    added: "\u0130ndirme eklendi",
    errorPrefix: "Hata: ",
    notRunning: "VeloFetch \u00e7al\u0131\u015fm\u0131yor olabilir.\nBa\u015flatmak i\u00e7in: vf"
  }
};

const T = (function () {
  const i18n = (typeof chrome !== "undefined" && chrome.i18n) || null;
  const tag = i18n && i18n.getUILanguage ? i18n.getUILanguage() : "en";
  return VELOFETCH_STRINGS[tag.slice(0, 2).toLowerCase()] || VELOFETCH_STRINGS.en;
})();


// This bundle is MV2, where the toolbar button is chrome.browserAction;
// chrome.action is MV3-only and reading .onClicked off it threw here, which
// killed the rest of this file (toolbar button and badge fallback both dead).
const velofetchAction = chrome.action || chrome.browserAction || null;

// Shown when token.js carries no token — i.e. the untouched repo copy was
// loaded instead of the one install.sh stages. Without this the server's raw
// 403 JSON was all the user got to go on.
const VELFETCH_TOKEN_HELP = T.tokenHelp;

// Create context menu item on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "velofetch-download",
    title: T.download,
    contexts: ["link", "page"]
  });

  chrome.contextMenus.create({
    id: "velofetch-download-video",
    title: T.downloadVideo,
    contexts: ["video", "audio"]
  });
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "velofetch-download") {
    downloadWithCookies(info.linkUrl || info.pageUrl, tab);
  } else if (info.menuItemId === "velofetch-download-video") {
    downloadWithCookies(info.linkUrl || info.srcUrl || info.pageUrl, tab, true);
  }
});

// Also handle browser action (toolbar button) click
if (velofetchAction && velofetchAction.onClicked) {
  velofetchAction.onClicked.addListener((tab) => {
    downloadWithCookies(tab.url, tab);
  });
}

async function downloadWithCookies(url, tab, useYtDlp = false) {
  if (!url) return;

  if (!VELFETCH_TOKEN) {
    showNotification("❌ VeloFetch", VELFETCH_TOKEN_HELP);
    return;
  }

  try {
    // Get all cookies for the current tab's domain
    const cookies = await getCookiesForUrl(url, tab);

    // Send to VeloFetch local server
    const requestHeaders = {
      "Content-Type": "application/json",
      "X-VeloFetch-Token": VELFETCH_TOKEN
    };

    const response = await fetch(`${VELFETCH_URL}/add`, {
      method: "POST",
      headers: requestHeaders,
      body: JSON.stringify({
        url: url,
        cookies: cookies,
        referrer: tab.url,
        title: tab.title || "",
        use_yt_dlp: useYtDlp
      })
    });

    if (response.ok) {
      showNotification("✅ VeloFetch", T.added);
    } else {
      const err = await response.text();
      showNotification("❌ VeloFetch", T.errorPrefix + err);
    }
  } catch (e) {
    // VeloFetch server might not be running
    showNotification("❌ VeloFetch", T.notRunning);
  }
}

async function getCookiesForUrl(url, tab) {
  try {
    // Use chrome.cookies API to get all cookies for the tab's domain
    const parsedUrl = new URL(url);
    const domain = parsedUrl.hostname;

    // Get cookies for the domain and its parent
    const cookies = await chrome.cookies.getAll({ domain: domain });

    // Also get cookies for parent domain (e.g., .archive.org)
    const parts = domain.split(".");
    let parentDomain = "";
    if (parts.length >= 2) {
      parentDomain = "." + parts.slice(-2).join(".");
      const parentCookies = await chrome.cookies.getAll({ domain: parentDomain });
      // Merge, avoiding duplicates
      const existingNames = new Set(cookies.map(c => c.name));
      for (const c of parentCookies) {
        if (!existingNames.has(c.name)) {
          cookies.push(c);
        }
      }
    }

    // Format as cookie header string: name=value; name2=value2
    return cookies
      .filter(c => c.value && c.value.length > 0)
      .map(c => `${c.name}=${c.value}`)
      .join("; ");
  } catch (e) {
    console.error("Failed to get cookies:", e);
    return "";
  }
}

function showNotification(title, message) {
  // Try to use chrome.notifications, fall back to badge text
  if (chrome.notifications) {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon-128.png",
      title: title,
      message: message
    });
  } else if (velofetchAction && velofetchAction.setBadgeText) {
    // Badge text fallback (this manifest asks for no "notifications" permission,
    // so in practice this is the path that runs).
    const failed = title.startsWith("❌");
    velofetchAction.setBadgeText({ text: failed ? "!" : "✓" });
    velofetchAction.setBadgeBackgroundColor({ color: failed ? "#f38ba8" : "#a6e3a1" });
    if (velofetchAction.setTitle) {
      velofetchAction.setTitle({ title: `${title}\n${message}` });
    }
    setTimeout(() => {
      velofetchAction.setBadgeText({ text: "" });
    }, failed ? 8000 : 2000);
  }
}
