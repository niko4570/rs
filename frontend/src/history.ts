import type { SummaryResult } from "./types";

export type ResearchRecord = {
  id: string;
  createdAt: number;
  inputType: "topic" | "url" | "file";
  inputName: string;
  result: SummaryResult;
};

const DATABASE = "rs-research-history";
const STORE = "summaries";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    let blocked = false;
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore(STORE, { keyPath: "id" });
      store.createIndex("createdAt", "createdAt");
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => {
      blocked = true;
      reject(new Error("Close other RS tabs and reload to access history."));
    };
    request.onsuccess = () => {
      const database = request.result;
      if (blocked) {
        database.close();
        return;
      }
      database.onversionchange = () => database.close();
      resolve(database);
    };
  });
}

async function transact<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const database = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = database.transaction(STORE, mode);
      const request = operation(transaction.objectStore(STORE));
      // A successful request can still be followed by a failed commit.
      transaction.oncomplete = () => resolve(request.result);
      transaction.onabort = () =>
        reject(transaction.error ?? new Error("History transaction aborted."));
      transaction.onerror = () => reject(transaction.error ?? request.error);
    });
  } finally {
    database.close();
  }
}

export async function loadHistory(): Promise<ResearchRecord[]> {
  const records = await transact<ResearchRecord[]>("readonly", (store) =>
    store.index("createdAt").getAll(),
  );
  return records.reverse();
}

export async function saveRecord(record: ResearchRecord): Promise<void> {
  await transact("readwrite", (store) => store.put(record));
}

export async function deleteRecord(id: string): Promise<void> {
  await transact("readwrite", (store) => store.delete(id));
}
