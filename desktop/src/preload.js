'use strict';
// Minimal, explicit bridge. The renderer gets no Node.js or Electron APIs.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bopDesktop', {
  platform: process.platform,
  appVersion: (process.argv.find((a) => a.startsWith('--bop-evolve-version=')) || '').split('=')[1] || '',
  getServerUrl: () => ipcRenderer.invoke('settings:get-server-url'),
  setServerUrl: (url) => ipcRenderer.invoke('settings:set-server-url', String(url)),
  testServer: (url) => ipcRenderer.invoke('settings:test-server', String(url)),
});
