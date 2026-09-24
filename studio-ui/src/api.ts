import type { Job, LaunchMode, LaunchPlan, Snapshot } from "./types";

export class ApiError extends Error {
  status: number;
  problems: string[];

  constructor(message: string, status: number, problems: string[] = []) {
    super(message);
    this.status = status;
    this.problems = problems;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail = `${init?.method ?? "GET"} ${path} -> ${res.status}`;
    let problems: string[] = [];
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
      problems = body.problems ?? [];
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status, problems);
  }
  return res.json() as Promise<T>;
}

const stagePath = (slug: string, key: string) => `/studio/projects/${slug}/stages/${key}`;

export const api = {
  snapshot: (project?: string) =>
    request<Snapshot>(`/studio/snapshot${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  reimport: () => request<unknown>("/studio/import", { method: "POST" }),
  activate: (slug: string) => request<unknown>(`/studio/projects/${slug}/activate`, { method: "POST" }),
  decide: (slug: string, key: string, decision: "approve" | "reject", note?: string) =>
    request<{ status: string }>(`${stagePath(slug, key)}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  launchPreview: (slug: string, key: string, mode: LaunchMode) =>
    request<LaunchPlan>(`${stagePath(slug, key)}/launch-preview?mode=${mode}`),
  launch: (
    slug: string,
    key: string,
    body: { mode: LaunchMode; request_id: string; confirmed: true; approve_first?: boolean; note?: string },
  ) => request<Job>(`${stagePath(slug, key)}/launch`, { method: "POST", body: JSON.stringify(body) }),
};
