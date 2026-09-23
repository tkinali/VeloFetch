// VeloFetch API token.
//
// The copy tracked in the repository is intentionally EMPTY — no secret is
// ever committed. install.sh stages a private copy of this extension in
// ~/.local/share/velofetch/browser/chromium/ and writes the real token into
// that copy's token.js. Load the staged folder in the browser, not this one.
self.VELFETCH_TOKEN = "";

// Loading this folder directly cannot work: the server answers 403 to every
// request, and all the user would otherwise see is the raw JSON of that error.
// Say what is actually wrong, as soon as the worker starts. The staged
// token.js install.sh writes carries a token and never reaches this branch.
self.VELFETCH_TOKEN_HELP =
  (navigator.language || "en").slice(0, 2).toLowerCase() === "tr"
    ? "Bu, deponun anahtarsız kopyası; istekler reddedilir. " +
      "Önce ./install.sh çalıştırın, sonra ~/.local/share/velofetch/browser/chromium " +
      "klasörünü yükleyin."
    : "This is the repository copy, which carries no token; requests are rejected. " +
      "Run ./install.sh first, then load the ~/.local/share/velofetch/browser/chromium " +
      "folder instead.";

if (!self.VELFETCH_TOKEN) {
  console.error("VeloFetch: " + self.VELFETCH_TOKEN_HELP);

  // token.js is imported before background.js runs, so this is the one place
  // the anonymous copy can stop itself. Every call it could make is already
  // lost — the server answers 403 — so answer them here instead, with the
  // help text in the body that background.js shows the user.
  const realFetch = self.fetch;
  self.fetch = function (resource, options) {
    const target = typeof resource === "string" ? resource : (resource && resource.url) || "";
    if (target.indexOf("127.0.0.1:9876") === -1) {
      return realFetch.call(self, resource, options);
    }
    return Promise.resolve({
      ok: false,
      status: 403,
      text: async () => self.VELFETCH_TOKEN_HELP,
      json: async () => ({ error: self.VELFETCH_TOKEN_HELP })
    });
  };

  try {
    const action =
      (typeof chrome !== "undefined" && (chrome.action || chrome.browserAction)) || null;
    if (action && action.setBadgeText) {
      // Pin the badge to a warning: nothing this copy does can succeed, so a
      // later "✓" would be a lie.
      const setBadgeText = action.setBadgeText.bind(action);
      action.setBadgeText = () => setBadgeText({ text: "!" });
      setBadgeText({ text: "!" });
      action.setBadgeBackgroundColor({ color: "#f38ba8" });
      if (action.setTitle) {
        action.setTitle({ title: "VeloFetch\n" + self.VELFETCH_TOKEN_HELP });
      }
    }
    if (typeof chrome !== "undefined" && chrome.notifications) {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icons/icon-128.png",
        title: "⚠ VeloFetch",
        message: self.VELFETCH_TOKEN_HELP
      });
    }
  } catch (e) {
    // Best effort: the badge is only a hint, never a reason to fail loading.
  }
}
