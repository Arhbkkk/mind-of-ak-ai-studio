(() => {
  "use strict";
  const DB_NAME = "mind-of-ak-local-library";
  const DB_VERSION = 1;
  const STORE = "media";
  const $ = (id) => document.getElementById(id);
  let dbPromise;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(STORE, { keyPath: "id" });
          store.createIndex("createdAt", "createdAt");
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Could not open local library."));
    });
    return dbPromise;
  }

  async function withStore(mode, action) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let result;
      try { result = action(store); } catch (error) { reject(error); return; }
      tx.oncomplete = () => resolve(result && result.result !== undefined ? result.result : result);
      tx.onerror = () => reject(tx.error || new Error("Local storage transaction failed."));
      tx.onabort = () => reject(tx.error || new Error("Local storage transaction was cancelled."));
    });
  }

  const formatBytes = (bytes) => {
    if (!Number.isFinite(bytes)) return "Unknown";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = bytes, index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
    return value.toFixed(index ? 1 : 0) + " " + units[index];
  };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const say = (message, isError = false) => {
    const node = $("localStorageStatus");
    if (!node) return;
    node.textContent = message;
    node.style.color = isError ? "#ffaaa0" : "";
  };

  async function refreshUsage() {
    if (!navigator.storage || !navigator.storage.estimate) {
      $("localStorageUsage").textContent = "This browser does not expose storage quota estimates.";
      return;
    }
    const estimate = await navigator.storage.estimate();
    const usage = estimate.usage || 0;
    const quota = estimate.quota || 0;
    $("localStorageUsage").textContent = "Browser storage used: " + formatBytes(usage) +
      (quota ? " · Estimated browser quota: " + formatBytes(quota) + " · " +
        Math.min(100, usage / quota * 100).toFixed(1) + "% used" : "") +
      ". This is a browser-managed quota, not a promise of 1 TB capacity.";
  }

  async function renderLibrary() {
    const items = await withStore("readonly", store => store.getAll());
    const list = $("localMediaList");
    list.replaceChildren();
    items.sort((a, b) => b.createdAt - a.createdAt);
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "notice";
      empty.textContent = "Your local media library is empty. Choose files above to save copies on this device.";
      list.append(empty);
    }
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "feature";
      const info = document.createElement("div");
      info.style.flex = "1";
      const title = document.createElement("strong");
      title.textContent = item.name;
      const details = document.createElement("span");
      details.textContent = formatBytes(item.size) + " · " + (item.type || "unknown type") + " · Saved " + new Date(item.createdAt).toLocaleString();
      info.append(title, details);
      const actions = document.createElement("div");
      actions.className = "actions";
      const download = document.createElement("button");
      download.type = "button";
      download.className = "btn secondary";
      download.textContent = "Export to Files";
      download.addEventListener("click", () => exportItem(item));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn secondary";
      remove.textContent = "Delete";
      remove.addEventListener("click", async () => {
        if (!window.confirm("Delete the saved local copy of " + item.name + "? This does not delete the original in Files.")) return;
        await withStore("readwrite", store => store.delete(item.id));
        await renderLibrary();
        await refreshUsage();
        say("Deleted local copy: " + item.name);
      });
      actions.append(download, remove);
      row.append(info, actions);
      list.append(row);
    }
    await refreshUsage();
  }

  function exportItem(item) {
    const url = URL.createObjectURL(item.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = item.name;
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    say("Export requested for " + item.name + ". On iPad, use the share/download flow to save it into Files if prompted.");
  }

  async function saveBlob(blob, name, type) {
    const id = (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2));
    await withStore("readwrite", store => store.put({
      id, name, type: type || blob.type || "application/octet-stream",
      size: blob.size, lastModified: Date.now(), createdAt: Date.now(), blob
    }));
    await renderLibrary();
    return id;
  }

  async function importFiles() {
    const files = Array.from($("localMediaFiles").files || []);
    if (!files.length) { say("Choose one or more files from Files first.", true); return; }
    const button = $("importLocalBtn");
    button.disabled = true;
    let saved = 0;
    try {
      if (navigator.storage && navigator.storage.persist) {
        try { await navigator.storage.persist(); } catch (_) { /* browser may deny persistent-storage request */ }
      }
      for (const file of files) {
        const id = (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2));
        await withStore("readwrite", store => store.put({
          id, name: file.name, type: file.type || "application/octet-stream",
          size: file.size, lastModified: file.lastModified || 0,
          createdAt: Date.now(), blob: file
        }));
        saved++;
      }
      $("localMediaFiles").value = "";
      await renderLibrary();
      say("Saved " + saved + " file(s) in this browser's local library. Keep a second copy in Files or backup storage for important footage.");
    } catch (error) {
      say("Could save " + saved + " of " + files.length + " files. Browser storage may be full or unavailable: " + (error.message || error), true);
      await renderLibrary().catch(() => {});
    } finally {
      button.disabled = false;
    }
  }

  async function init() {
    if (!("indexedDB" in window)) {
      say("This browser does not support the local media library.", true);
      $("importLocalBtn").disabled = true;
      return;
    }
    try {
      await openDb();
      $("importLocalBtn").addEventListener("click", importFiles);\n      $("videoFile").addEventListener("change", async () => {\n        const file = $("videoFile").files && $("videoFile").files[0];\n        if (!file) return;\n        try { await saveBlob(file, file.name, file.type); say("Source saved locally: " + file.name + ". Upload to the render server separately when you are ready."); }\n        catch (error) { say("Could not save a local copy of the source: " + (error.message || error), true); }\n      });\n      window.addEventListener("mindofak:export-ready", async event => {\n        const detail = event.detail || {};\n        const button = document.createElement("button");\n        button.type = "button"; button.className = "btn secondary"; button.textContent = "Save MP4 in local library";\n        button.addEventListener("click", async () => {\n          button.disabled = true; button.textContent = "Saving…";\n          try {\n            const response = await fetch(detail.url, { cache: "no-store" });\n            if (!response.ok) throw new Error("Could not download the rendered MP4 (HTTP " + response.status + ").");\n            const blob = await response.blob();\n            await saveBlob(blob, detail.name || "mind-of-ak-export.mp4", blob.type || "video/mp4");\n            say("Rendered MP4 saved in the local library.");\n            button.textContent = "Saved locally";\n          } catch (error) { button.disabled = false; button.textContent = "Save MP4 in local library"; say(error.message || String(error), true); }\n        });\n        $("exportResult").append(document.createElement("br"), button);\n      });
      $("refreshLocalBtn").addEventListener("click", () => renderLibrary().then(() => say("Local library refreshed.")).catch(e => say(e.message, true)));
      await renderLibrary();
      let persistent = false;
      try { persistent = navigator.storage && navigator.storage.persisted ? await navigator.storage.persisted() : false; } catch (_) {}
      say("Local library ready · " + (persistent ? "browser granted persistent storage" : "browser-managed storage; keep a separate copy in Files"));
    } catch (error) {
      say("Local library could not start: " + (error.message || error), true);
      $("importLocalBtn").disabled = true;
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
