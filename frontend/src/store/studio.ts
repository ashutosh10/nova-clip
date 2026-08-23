import { create } from "zustand";
import type { Clip, Job, Project } from "@/lib/types";

interface StudioState {
  projects: Project[];
  project: Project | null;
  selectedClipId: string | null;
  jobs: Record<string, Job>;
  busy: boolean;
  error: string | null;
  setProjects: (projects: Project[]) => void;
  setProject: (project: Project | null) => void;
  setSelectedClip: (id: string | null) => void;
  setBusy: (busy: boolean) => void;
  setError: (error: string | null) => void;
  upsertClip: (clip: Clip) => void;
  removeClip: (id: string) => void;
  reorderLocal: (oldIndex: number, newIndex: number) => void;
  upsertJob: (job: Job) => void;
}

export const useStudio = create<StudioState>((set) => ({
  projects: [], project: null, selectedClipId: null, jobs: {}, busy: false, error: null,
  setProjects: (projects) => set({ projects }),
  setProject: (project) => set((state) => {
    const selectedStillExists = project?.clips.some((clip) => clip.id === state.selectedClipId);
    const firstPlayable = project?.clips.find((clip) => clip.status === "READY" && clip.media_url);
    const projects = project
      ? state.projects.map((item) => item.id === project.id ? project : item)
      : state.projects;
    return {
      project,
      projects,
      selectedClipId: selectedStillExists ? state.selectedClipId : firstPlayable?.id ?? project?.clips[0]?.id ?? null,
    };
  }),
  setSelectedClip: (selectedClipId) => set({ selectedClipId }),
  setBusy: (busy) => set({ busy }),
  setError: (error) => set({ error }),
  upsertClip: (clip) => set((state) => {
    if (!state.project) return state;
    const exists = state.project.clips.some((item) => item.id === clip.id);
    const clips = exists ? state.project.clips.map((item) => item.id === clip.id ? clip : item) : [...state.project.clips, clip];
    return { project: { ...state.project, clips: clips.sort((a, b) => a.position - b.position) } };
  }),
  removeClip: (id) => set((state) => state.project ? {
    project: { ...state.project, clips: state.project.clips.filter((clip) => clip.id !== id).map((clip, position) => ({ ...clip, position })) },
    selectedClipId: state.selectedClipId === id ? null : state.selectedClipId,
  } : state),
  reorderLocal: (oldIndex, newIndex) => set((state) => {
    if (!state.project) return state;
    const clips = [...state.project.clips];
    const [moved] = clips.splice(oldIndex, 1);
    clips.splice(newIndex, 0, moved);
    return { project: { ...state.project, clips: clips.map((clip, position) => ({ ...clip, position })) } };
  }),
  upsertJob: (job) => set((state) => ({ jobs: { ...state.jobs, [job.id]: job } })),
}));

