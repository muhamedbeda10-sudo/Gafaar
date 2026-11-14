const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

function detail(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((e: { msg?: string; loc?: unknown[] }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`.replace(/^: /, ""))
      .join("; ");
  }
  return fallback;
}

export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const opts: RequestInit = { ...init, cache: "no-store" };
  if (init?.json !== undefined) {
    opts.body = JSON.stringify(init.json);
    opts.headers = { "Content-Type": "application/json", ...(init.headers || {}) };
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, opts);
  } catch {
    throw new ApiError(`Cannot reach the API at ${BASE}. Is the backend running?`, 0);
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {}
    throw new ApiError(detail(body, `Request failed (${res.status})`), res.status);
  }
  return res.json();
}

export const apiUrl = (path: string) => `${BASE}${path}`;
