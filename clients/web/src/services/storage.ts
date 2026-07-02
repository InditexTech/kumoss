function isStorageAvailable(storage: Storage): boolean {
  const testKey = "__nebula_storage_test__";
  try {
    storage.setItem(testKey, "1");
    storage.removeItem(testKey);
    return true;
  } catch {
    return false;
  }
}

let _localAvailable: boolean | null = null;
let _sessionAvailable: boolean | null = null;

function localAvailable(): boolean {
  if (_localAvailable === null) {
    _localAvailable = isStorageAvailable(localStorage);
  }
  return _localAvailable;
}

function sessionAvailable(): boolean {
  if (_sessionAvailable === null) {
    _sessionAvailable = isStorageAvailable(sessionStorage);
  }
  return _sessionAvailable;
}

export function getLocalItem(key: string): string | null {
  if (!localAvailable()) return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setLocalItem(key: string, value: string): void {
  if (!localAvailable()) return;
  try {
    localStorage.setItem(key, value);
  } catch {
    // Quota exceeded or other write failure
  }
}

export function getSessionItem(key: string): string | null {
  if (!sessionAvailable()) return null;
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setSessionItem(key: string, value: string): void {
  if (!sessionAvailable()) return;
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // Quota exceeded or other write failure
  }
}

