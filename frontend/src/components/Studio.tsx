"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Clapperboard, Download, Film, Pencil, Plus, Save, Sparkles, Trash2, X } from "lucide-react";
import { api, assetUrl } from "@/lib/api";
import { useJobStream } from "@/hooks/useJobStream";
import { useStudio } from "@/store/studio";
import { GeneratorForm } from "./GeneratorForm";
import { Inspector } from "./Inspector";
import { Player } from "./Player";
import { QueueStatus } from "./QueueStatus";
import { Timeline } from "./Timeline";

function ActiveStream({ jobId, onDone }: { jobId: string; onDone: () => void }) { useJobStream(jobId, onDone); return null; }

const PROJECT_STORAGE_KEY = "nova-clip:selected-project";

export function Studio() {
  const { projects, project, jobs, error, setProjects, setProject, upsertJob, setError } = useStudio();
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [projectEditorMode, setProjectEditorMode] = useState<"create" | "edit" | null>(null);
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [deletingProject, setDeletingProject] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [transition, setTransition] = useState<"cut" | "crossfade">("crossfade");

  const refresh = useCallback(async () => {
    if (!useStudio.getState().project) return;
    try { setProject(await api.getProject(useStudio.getState().project!.id)); }
    catch (err) { setError(err instanceof Error ? err.message : "Refresh failed"); }
  }, [setError, setProject]);

  useEffect(() => {
    let cancelled = false;
    api.listProjects().then((items) => {
      if (cancelled) return;
      setProjects(items);
      const rememberedId = window.localStorage.getItem(PROJECT_STORAGE_KEY);
      const next = items.find((item) => item.id === rememberedId)
        ?? items.find((item) => item.master_url || item.clips.some((clip) => clip.status === "READY" && clip.media_url))
        ?? items[0];
      if (next) {
        window.localStorage.setItem(PROJECT_STORAGE_KEY, next.id);
        setProject(next);
      }
    }).catch((err) => setError(err.message));
    return () => { cancelled = true; };
  }, [setError, setProject, setProjects]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = useStudio.getState().project;
      if (current?.clips.some((clip) => clip.status === "QUEUED" || clip.status === "GENERATING")) refresh();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  function chooseProject(next: NonNullable<typeof project>) {
    window.localStorage.setItem(PROJECT_STORAGE_KEY, next.id);
    setProject(next);
  }

  function openCreateProject() {
    setProjectEditorMode("create");
    setProjectName("");
    setProjectDescription("");
  }

  function openEditProject() {
    if (!project) return;
    setProjectEditorMode("edit");
    setProjectName(project.name);
    setProjectDescription(project.description ?? "");
  }

  async function saveProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) {
      setError("Give the project a name");
      return;
    }
    setSavingProject(true);
    try {
      if (projectEditorMode === "create") {
        const made = await api.createProject({
          name,
          description: projectDescription.trim() || null,
          width: 1280,
          height: 720,
          fps: 24,
        });
        setProjects([made, ...projects]);
        chooseProject(made);
      } else if (projectEditorMode === "edit" && project) {
        const saved = await api.updateProject(project.id, {
          name,
          description: projectDescription.trim() || null,
        });
        setProject(saved);
      }
      setProjectEditorMode(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save project");
    } finally {
      setSavingProject(false);
    }
  }

  async function deleteCurrentProject() {
    if (!project || !window.confirm(`Delete "${project.name}" and all of its clips?`)) return;
    setDeletingProject(true);
    try {
      await api.deleteProject(project.id);
      const remaining = projects.filter((item) => item.id !== project.id);
      setProjects(remaining);
      if (remaining[0]) chooseProject(remaining[0]);
      else {
        window.localStorage.removeItem(PROJECT_STORAGE_KEY);
        setProject(null);
      }
      setProjectEditorMode(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete project");
    } finally {
      setDeletingProject(false);
    }
  }

  async function exportProject() {
    if (!project) return;
    setExporting(true);
    try { const job = await api.stitch(project.id, transition, .6); upsertJob(job); setJobIds((ids) => [...ids, job.id]); }
    catch (err) { setError(err instanceof Error ? err.message : "Export failed"); setExporting(false); }
  }

  const master = assetUrl(project?.master_url ?? null);
  return <main className="min-h-screen">
    {jobIds.map((id) => <ActiveStream key={id} jobId={id} onDone={() => { setJobIds((items) => items.filter((item) => item !== id)); setExporting(false); refresh(); }}/>) }
    <header className="sticky top-0 z-30 flex min-h-16 flex-wrap items-center gap-2 border-b border-line bg-ink/90 px-3 py-2 backdrop-blur-xl sm:px-5 md:h-16 md:flex-nowrap md:gap-0 md:py-0">
      <div className="flex shrink-0 items-center gap-2 sm:gap-3"><div className="grid size-9 place-items-center rounded-xl bg-acid text-ink"><Clapperboard size={18}/></div><div><div className="text-sm font-black tracking-tight">NOVA CLIP</div><div className="hidden text-[8px] font-bold uppercase tracking-[.28em] text-white/30 sm:block">Generative film studio</div></div></div>
      <div className="mx-3 hidden h-6 w-px bg-line md:block md:mx-6"/>
      <label className="flex min-w-0 flex-1 items-center gap-2 sm:max-w-72">
        <span className="shrink-0 text-[9px] font-bold uppercase tracking-wider text-white/35">My projects</span>
        <select aria-label="My saved projects" value={project?.id ?? ""} onChange={(e) => { const next = projects.find((item) => item.id === e.target.value); if (next) chooseProject(next); }} className="min-w-0 flex-1 truncate bg-transparent text-xs font-semibold text-white/70 outline-none"><option value="" disabled>No saved projects</option>{projects.map((item) => { const saved = item.clips.filter((clip) => clip.status === "READY" && clip.media_url).length; return <option value={item.id} key={item.id}>{item.name} ({saved} clips)</option>; })}</select>
      </label>
      <button onClick={openCreateProject} className="icon-button shrink-0 md:ml-2" title="New project" aria-label="New project"><Plus size={15}/></button>
      {project && <button onClick={openEditProject} className="icon-button shrink-0" title="Project settings" aria-label="Edit project"><Pencil size={14}/></button>}{master && <a href={master} download className="icon-button shrink-0 md:hidden" title="Download master" aria-label="Download master"><Download size={15}/></a>}
      <div className="ml-auto hidden items-center gap-3 md:flex"><div className="hidden items-center gap-2 text-[9px] font-bold uppercase tracking-wider text-white/30 lg:flex"><span className="size-1.5 rounded-full bg-acid shadow-[0_0_10px_#d8ff5f]"/> L4 worker online</div>{master && <a href={master} download className="icon-button" title="Download master" aria-label="Download master"><Download size={15}/></a>}<select aria-label="Clip transition" value={transition} onChange={(e) => setTransition(e.target.value as "cut" | "crossfade")} className="min-h-10 rounded-lg border border-line bg-panel px-3 text-xs text-white/65"><option value="cut">Hard cut</option><option value="crossfade">Crossfade</option></select><button onClick={exportProject} disabled={exporting || !project?.clips.length || project.clips.some((clip) => clip.status !== "READY")} className="flex min-h-10 items-center gap-2 rounded-xl bg-white px-4 text-xs font-bold text-ink transition hover:bg-acid disabled:cursor-not-allowed disabled:opacity-30"><Film size={14}/>{exporting ? "Exporting…" : "Stitch & export"}</button></div>
      <div className="grid basis-full grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] gap-2 border-t border-line pt-2 md:hidden">
        <label className="flex min-h-11 min-w-0 items-center justify-between gap-2 rounded-xl border border-line bg-panel px-3"><span className="text-[9px] font-bold uppercase tracking-wider text-white/35">Transition</span><select aria-label="Clip transition" value={transition} onChange={(e) => setTransition(e.target.value as "cut" | "crossfade")} className="min-w-0 bg-transparent text-right text-xs font-semibold text-white/75 outline-none"><option value="cut">Hard cut</option><option value="crossfade">Crossfade</option></select></label>
        <button onClick={exportProject} disabled={exporting || !project?.clips.length || project.clips.some((clip) => clip.status !== "READY")} className="flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-xl bg-white px-3 text-xs font-bold text-ink transition active:bg-acid disabled:cursor-not-allowed disabled:opacity-30"><Film className="shrink-0" size={15}/><span className="truncate">{exporting ? "Exporting…" : "Stitch & export"}</span></button>
      </div>
    </header>

    {error && <div className="fixed left-3 right-3 top-32 z-50 flex max-w-sm items-start gap-3 rounded-xl border border-coral/30 bg-[#25130f] p-3 text-xs text-coral shadow-2xl md:left-auto md:right-5 md:top-20"><span className="flex-1">{error}</span><button onClick={() => setError(null)}><X size={14}/></button></div>}

    {!project ? <div className="grid min-h-[calc(100vh-4rem)] place-items-center p-8"><div className="max-w-md text-center"><div className="mx-auto mb-6 grid size-20 place-items-center rounded-3xl border border-acid/20 bg-acid/[.04] text-acid"><Sparkles size={30}/></div><p className="eyebrow mb-3">Start a production</p><h1 className="text-4xl font-black tracking-tight">Build a scene,<br/>one shot at a time.</h1><p className="mx-auto mt-4 max-w-sm text-sm leading-relaxed text-white/40">Generate cinematic video, shape the sequence, then deliver one seamless master.</p><button onClick={openCreateProject} className="mt-7 rounded-xl bg-acid px-5 py-3 text-sm font-bold text-ink">Create named project</button></div></div> :
    <div className="grid gap-4 p-3 sm:p-4 xl:grid-cols-[300px_minmax(0,1fr)_280px]">
      <div className="min-h-[500px]"><GeneratorForm onJob={(id) => setJobIds((items) => [...items, id])}/></div>
      <div className="min-w-0 space-y-4"><Player/><Timeline/></div>
      <div className="grid content-start gap-4"><QueueStatus/><div className="min-h-64"><Inspector/></div></div>
    </div>}
    {projectEditorMode && <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-editor-title"
      className="fixed inset-0 z-[70] flex items-end justify-center overflow-y-auto bg-black/75 p-3 backdrop-blur-sm sm:items-center sm:p-6"
      onMouseDown={(event) => { if (event.target === event.currentTarget && !savingProject && !deletingProject) setProjectEditorMode(null); }}
    >
      <form onSubmit={saveProject} className="w-full max-w-lg rounded-2xl border border-line bg-panel p-4 shadow-2xl sm:p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="eyebrow mb-2">{projectEditorMode === "create" ? "New project" : "Project settings"}</p>
            <h2 id="project-editor-title" className="text-xl font-black tracking-tight">
              {projectEditorMode === "create" ? "Name your production" : "Save project details"}
            </h2>
          </div>
          <button type="button" onClick={() => setProjectEditorMode(null)} disabled={savingProject || deletingProject} className="icon-button shrink-0" aria-label="Close project editor"><X size={15}/></button>
        </div>
        <label className="mb-4 block">
          <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-white/45">Project name</span>
          <input value={projectName} onChange={(event) => setProjectName(event.target.value)} required maxLength={120} autoFocus className="min-h-12 w-full rounded-xl border border-line bg-ink px-4 text-sm text-white outline-none transition focus:border-acid/60" placeholder="e.g. Mountain campaign"/>
        </label>
        <label className="mb-4 block">
          <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-white/45">Description <span className="normal-case text-white/25">optional</span></span>
          <textarea value={projectDescription} onChange={(event) => setProjectDescription(event.target.value)} maxLength={2000} rows={3} className="w-full resize-none rounded-xl border border-line bg-ink px-4 py-3 text-sm text-white outline-none transition focus:border-acid/60" placeholder="What are you making?"/>
        </label>
        <p className="mb-5 rounded-xl border border-acid/10 bg-acid/[.04] p-3 text-xs leading-relaxed text-white/45">Clips, ordering, trims, and exports are saved automatically to this project.</p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
          {projectEditorMode === "edit" && <button type="button" onClick={deleteCurrentProject} disabled={savingProject || deletingProject} className="flex min-h-11 items-center justify-center gap-2 rounded-xl border border-coral/30 px-4 text-xs font-bold text-coral transition hover:bg-coral/10 disabled:opacity-40"><Trash2 size={14}/>{deletingProject ? "Deleting..." : "Delete project"}</button>}
          <div className="flex flex-1 gap-2 sm:justify-end">
            <button type="button" onClick={() => setProjectEditorMode(null)} disabled={savingProject || deletingProject} className="min-h-11 flex-1 rounded-xl border border-line px-4 text-xs font-bold text-white/60 sm:flex-none">Cancel</button>
            <button type="submit" disabled={savingProject || deletingProject || !projectName.trim()} className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-acid px-5 text-xs font-bold text-ink disabled:opacity-40 sm:flex-none"><Save size={14}/>{savingProject ? "Saving..." : projectEditorMode === "create" ? "Start project" : "Save project"}</button>
          </div>
        </div>
      </form>
    </div>}

  </main>;
}

