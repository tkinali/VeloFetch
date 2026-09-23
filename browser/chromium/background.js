// VeloFetch Browser Extension - Background Script
// Adds "Download with VeloFetch" to context menu and sends URL + cookies to local server

// The API token lives in the sibling token.js, which install.sh fills in for
// the staged copy of this extension. It is never stored in this file.
try { importScripts("token.js"); } catch (e) {}

const VELFETCH_PORT = 9876;
const VELFETCH_URL = `http://127.0.0.1:${VELFETCH_PORT}`;
const VELFETCH_TOKEN = self.VELFETCH_TOKEN || "";

// Menu entries and notifications follow the browser's UI language, the same way
// the desktop app follows the system locale. Add a language by adding a pack.
const VELOFETCH_STRINGS = {
  en: {
    download: "\u{1F4E5} Download with VeloFetch",
    downloadVideo: "\u{1F3AC} Download video with VeloFetch",
    added: "Download added",
    errorPrefix: "Error: ",
    notRunning: "VeloFetch may not be running.\nStart it with: vf"
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
chrome.action.onClicked.addListener((tab) => {
  downloadWithCookies(tab.url, tab);
});

async function downloadWithCookies(url, tab, useYtDlp = false) {
  if (!url) return;

  try {
    // Get all cookies for the current tab's domain
    const cookies = await getCookiesForUrl(url, tab);

    // Send to VeloFetch local server
    const requestHeaders = { "Content-Type": "application/json" };
    if (VELFETCH_TOKEN) requestHeaders["X-VeloFetch-Token"] = VELFETCH_TOKEN;

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
  } else {
    // Badge text fallback
    chrome.action.setBadgeText({ text: "✓" });
    chrome.action.setBadgeBackgroundColor({ color: "#a6e3a1" });
    setTimeout(() => {
      chrome.action.setBadgeText({ text: "" });
    }, 2000);
  }
}
