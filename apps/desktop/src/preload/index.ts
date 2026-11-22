import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("os1", {
  getConfig: () => ipcRenderer.invoke("os1:config") as Promise<{ orchestratorUrl: string; clientToken?: string }>,
  cua: {
    revokeAll: () => ipcRenderer.invoke("os1:cua:revoke"),
    status: () => ipcRenderer.invoke("os1:cua:status"),
  },
});
