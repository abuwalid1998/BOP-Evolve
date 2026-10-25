'use strict';
// Persisted desktop settings (server URL) in the per-user app data folder.
const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_SERVER_URL = process.env.BOP_EVOLVE_SERVER_URL || 'http://localhost:8000';

/** Accept only plain http(s) origins (optionally with a path prefix); no credentials or query. */
function normaliseServerUrl(value) {
  let url;
  try {
    url = new URL(String(value).trim());
  } catch {
    throw new Error('Invalid URL');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Only http and https are allowed');
  if (url.username || url.password) throw new Error('Credentials in the URL are not allowed');
  url.search = '';
  url.hash = '';
  return url.toString().replace(/\/+$/, '');
}

class Settings {
  constructor(userDataDir) {
    this.file = path.join(userDataDir, 'settings.json');
    this.values = { serverUrl: DEFAULT_SERVER_URL };
    try {
      const stored = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (stored.serverUrl) this.values.serverUrl = normaliseServerUrl(stored.serverUrl);
    } catch {
      /* first run or unreadable file: keep defaults */
    }
  }

  get serverUrl() {
    return this.values.serverUrl;
  }

  setServerUrl(value) {
    this.values.serverUrl = normaliseServerUrl(value);
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, JSON.stringify(this.values, null, 2), 'utf8');
    return this.values.serverUrl;
  }
}

module.exports = { Settings, normaliseServerUrl, DEFAULT_SERVER_URL };
