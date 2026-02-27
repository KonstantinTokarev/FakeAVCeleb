const KEY = "df_uid";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const cookies = document.cookie ? document.cookie.split(";") : [];
  for (const c of cookies) {
    const [k, ...rest] = c.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function writeCookie(name: string, value: string, days: number) {
  if (typeof document === "undefined") return;
  const expires = new Date(Date.now() + days * 86400_000).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; Expires=${expires}; Path=/; SameSite=Lax`;
}

export function getAnonymousId(): string | null {
  if (typeof window === "undefined") return null;
  const fromLs = window.localStorage.getItem(KEY);
  if (fromLs) return fromLs;
  const fromCookie = readCookie(KEY);
  if (fromCookie) return fromCookie;
  return null;
}

export function setAnonymousId(id: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, id);
  writeCookie(KEY, id, 365);
}

export function getOrCreateAnonymousId(): string {
  const existing = getAnonymousId();
  if (existing) return existing;
  const id = (typeof crypto !== "undefined" && "randomUUID" in crypto)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  setAnonymousId(id);
  return id;
}

