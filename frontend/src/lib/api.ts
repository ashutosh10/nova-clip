import type { Clip, Job, Project } from "./types";

export const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const API = `${API_ORIGIN}/api/v1`;

export function assetUrl(path: string | null): string | null {
  if (!path) return null;
  return path.startsWith("http") ? path : `${API_ORIGIN}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      message = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
    } catch { /* retain status message */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/projects", { cache: "no-store" }),
  getProject: (id: string) => request<Project>(`/projects/${id}`, { cache: "no-store" }),
  createProject: (body: { name: string; description?: string | null; width: number; height: number; fps: number }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  updateProject: (id: string, body: { name: string; description: string | null }) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),
  generate: (projectId: string, body: Record<string, unknown>) =>
    request<{ clip: Clip; job: Job }>(`/projects/${projectId}/generate-clip`, { method: "POST", body: JSON.stringify(body) }),
  generateVideo: (projectId: string, body: Record<string, unknown>) =>
    request<{ clips: Clip[]; job: Job }>(`/projects/${projectId}/generate-video`, { method: "POST", body: JSON.stringify(body) }),
  upload: (projectId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Clip>(`/projects/${projectId}/clips/upload`, { method: "POST", body });
  },
  reorder: (projectId: string, clipIds: string[]) =>
    request<Project>(`/projects/${projectId}/reorder`, { method: "POST", body: JSON.stringify({ clip_ids: clipIds }) }),
  trim: (projectId: string, clipId: string, trim_start: number, trim_end: number | null) =>
    request<Clip>(`/projects/${projectId}/clips/${clipId}/trim`, { method: "PATCH", body: JSON.stringify({ trim_start, trim_end }) }),
  deleteClip: (projectId: string, clipId: string) =>
    request<void>(`/projects/${projectId}/clips/${clipId}`, { method: "DELETE" }),
  stitch: (projectId: string, transition: "cut" | "crossfade", transitionSeconds: number) =>
    request<Job>(`/projects/${projectId}/stitch`, {
      method: "POST",
      body: JSON.stringify({ transition, transition_seconds: transitionSeconds, codec: "h264" }),
    }),
};

