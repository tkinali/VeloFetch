// VeloFetch API token.
//
// The copy tracked in the repository is intentionally EMPTY — no secret is
// ever committed. install.sh stages a private copy of this extension in
// ~/.local/share/velofetch/browser/firefox/ and writes the real token into
// that copy's token.js. Load the staged folder in the browser, not this one.
self.VELFETCH_TOKEN = "";
