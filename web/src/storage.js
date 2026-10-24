let db;
export async function openStorage() {
  db = await new Promise((resolve, reject) => {
    const req = indexedDB.open("transcribe-workbench", 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore("documents", { keyPath: "id" });
      req.result.createObjectStore("settings");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () =>
      reject(
        new Error("Close another Transcribe tab to upgrade local storage."),
      );
  });
  return db;
}
function transaction(store, mode, fn) {
  return new Promise((resolve, reject) => {
    if (!db)
      return reject(
        new Error(
          "Local storage is unavailable. Export a backup before closing.",
        ),
      );
    let result;
    const tx = db.transaction(store, mode);
    const request = fn(tx.objectStore(store));
    request.onsuccess = () => (result = request.result);
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error || request.error);
    tx.onabort = () => reject(tx.error || new Error("Local save failed."));
  });
}
export const allDocuments = () =>
  transaction("documents", "readonly", (s) => s.getAll());
export const saveDocument = (doc) =>
  transaction("documents", "readwrite", (s) => s.put(doc));
export const deleteDocument = (id) =>
  transaction("documents", "readwrite", (s) => s.delete(id));
export const getSettings = () =>
  transaction("settings", "readonly", (s) => s.get("preferences"));
export const saveSettings = (data) =>
  transaction("settings", "readwrite", (s) => s.put(data, "preferences"));
