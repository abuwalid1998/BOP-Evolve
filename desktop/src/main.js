'use strict';
/**
 * BOP Evolve desktop shell.
 *
 * Serves the bundled React UI from the privileged `app://bop-evolve` origin and
 * talks to the Dockerized BOP Evolve API at a configurable server URL. All data,
 * access control and audit stay on the server; the desktop app stores only the
 * server URL (and the session token in session storage, cleared on exit).
 */
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { app, BrowserWindow, Menu, ipcMain, net, protocol, session, shell } = require('electron');
const { Settings, normaliseServerUrl } = require('./settings');

const APP_SCHEME = 'app';
const APP_HOST = 'bop-evolve';
const APP_ORIGIN = `${APP_SCHEME}://${APP_HOST}`;
const RENDERER_DIR = path.join(__dirname, '..', 'renderer');
const DEV_URL = process.env.BOP_EVOLVE_DEV_URL; // e.g. http://localhost:5173 while developing the UI
const isMac = process.platform === 'darwin';

protocol.registerSchemesAsPrivileged([
  { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

if (!app.requestSingleInstanceLock()) {
  app.quit();
}

let mainWindow = null;
let settings = null;

function registerAppProtocol() {
  protocol.handle(APP_SCHEME, (request) => {
    const url = new URL(request.url);
    if (url.host !== APP_HOST) return new Response('Not found', { status: 404 });
    const relative = decodeURIComponent(url.pathname).replace(/^\/+/, '') || 'index.html';
    const filePath = path.normalize(path.join(RENDERER_DIR, relative));
    // Block path traversal outside the bundled renderer folder.
    if (filePath !== RENDERER_DIR && !filePath.startsWith(RENDERER_DIR + path.sep)) {
      return new Response('Forbidden', { status: 403 });
    }
    return net.fetch(pathToFileURL(filePath).toString());
  });
}

function isAllowedNavigation(target) {
  try {
    const url = new URL(target);
    if (url.origin === APP_ORIGIN) return true;
    return !!DEV_URL && url.origin === new URL(DEV_URL).origin;
  } catch {
    return false;
  }
}

function openExternalSafely(target) {
  try {
    const url = new URL(target);
    if (url.protocol === 'https:' || url.protocol === 'http:') shell.openExternal(url.toString());
  } catch {
    /* ignore malformed links */
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1024,
    minHeight: 680,
    title: 'BOP Evolve',
    backgroundColor: '#f5f5f7',
    show: false,
    icon: path.join(__dirname, '..', 'build', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
      additionalArguments: [`--bop-evolve-version=${app.getVersion()}`],
      devTools: !app.isPackaged || process.env.BOP_EVOLVE_DEVTOOLS === '1',
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafely(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url)) {
      event.preventDefault();
      openExternalSafely(url);
    }
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.loadURL(DEV_URL || `${APP_ORIGIN}/index.html`);
}

function registerIpc() {
  ipcMain.handle('settings:get-server-url', () => settings.serverUrl);
  ipcMain.handle('settings:set-server-url', (_event, value) => settings.setServerUrl(value));
  ipcMain.handle('settings:test-server', async (_event, value) => {
    let base;
    try {
      base = normaliseServerUrl(value);
    } catch (err) {
      return { ok: false, error: err.message };
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await net.fetch(`${base}/api/health`, { signal: controller.signal });
      return { ok: response.ok, status: response.status };
    } catch (err) {
      return { ok: false, error: err.name === 'AbortError' ? 'Timed out' : err.message };
    } finally {
      clearTimeout(timer);
    }
  });
}

function buildMenu() {
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    { role: 'fileMenu' },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        ...(!app.isPackaged ? [{ role: 'toggleDevTools' }] : []),
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    { role: 'windowMenu' },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

app.whenReady().then(() => {
  settings = new Settings(app.getPath('userData'));
  // The UI needs no device permissions (camera, microphone, notifications, ...).
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  registerAppProtocol();
  registerIpc();
  buildMenu();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => event.preventDefault());
});

app.on('window-all-closed', () => {
  if (!isMac) app.quit();
});
