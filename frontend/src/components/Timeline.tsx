"use client";

import { useRef } from "react";
import { closestCenter, DndContext, DragEndEvent, MouseSensor, TouchSensor, useSensor, useSensors } from "@dnd-kit/core";
import { arrayMove, horizontalListSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Film, GripVertical, Plus, Trash2, Upload } from "lucide-react";
import { api, assetUrl } from "@/lib/api";
import type { Clip } from "@/lib/types";
import { useStudio } from "@/store/studio";

function time(value: number | null) { return `${(value ?? 0).toFixed(1)}s`; }

function SortableClip({ clip, selected, onSelect, onDelete }: { clip: Clip; selected: boolean; onSelect: () => void; onDelete: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: clip.id });
  return <button
    ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} onClick={onSelect}
    className={`group relative h-24 w-40 shrink-0 overflow-hidden rounded-xl border text-left transition sm:h-28 sm:w-48 ${selected ? "border-acid shadow-glow" : "border-line hover:border-white/25"} ${isDragging ? "z-20 opacity-60" : ""}`}
  >
    {clip.thumbnail_url ? <img src={assetUrl(clip.thumbnail_url) ?? ""} alt="" className="h-full w-full object-cover"/> : <div className="grid h-full place-items-center bg-white/[.03]"><Film className="text-white/15"/></div>}
    <div className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-black/15"/>
    <div {...attributes} {...listeners} className="absolute left-2 top-2 cursor-grab rounded bg-black/55 p-1 text-white/60 active:cursor-grabbing"><GripVertical size={13}/></div>
    <button aria-label="Delete clip" onClick={(event) => { event.stopPropagation(); onDelete(); }} className="absolute right-2 top-2 rounded bg-black/70 p-2 text-white/70 opacity-100 transition hover:text-coral sm:p-1.5 sm:opacity-0 sm:group-hover:opacity-100"><Trash2 size={12}/></button>
    <div className="absolute inset-x-2 bottom-2 flex items-end justify-between gap-2">
      <span className={`rounded px-1.5 py-1 text-[9px] font-bold tracking-wider ${clip.status === "READY" ? "bg-acid text-ink" : clip.status === "FAILED" ? "bg-coral text-white" : "bg-white/15 text-white"}`}>{clip.status}</span>
      <span className="text-[10px] font-semibold text-white/65">{time(clip.duration_seconds)}</span>
    </div>
  </button>;
}

export function Timeline() {
  const project = useStudio((state) => state.project);
  const selected = useStudio((state) => state.selectedClipId);
  const setSelected = useStudio((state) => state.setSelectedClip);
  const upsertClip = useStudio((state) => state.upsertClip);
  const removeClip = useStudio((state) => state.removeClip);
  const reorderLocal = useStudio((state) => state.reorderLocal);
  const setError = useStudio((state) => state.setError);
  const inputRef = useRef<HTMLInputElement>(null);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 8 } }),
  );
  if (!project) return null;
  const activeProject = project;

  async function dragEnd(event: DragEndEvent) {
    if (!event.over || event.active.id === event.over.id) return;
    const oldIndex = activeProject.clips.findIndex((clip) => clip.id === event.active.id);
    const newIndex = activeProject.clips.findIndex((clip) => clip.id === event.over?.id);
    const ordered = arrayMove(activeProject.clips, oldIndex, newIndex);
    reorderLocal(oldIndex, newIndex);
    try { await api.reorder(activeProject.id, ordered.map((clip) => clip.id)); }
    catch (error) { reorderLocal(newIndex, oldIndex); setError(error instanceof Error ? error.message : "Reorder failed"); }
  }

  async function upload(file?: File) {
    if (!file) return;
    try { upsertClip(await api.upload(activeProject.id, file)); }
    catch (error) { setError(error instanceof Error ? error.message : "Upload failed"); }
    if (inputRef.current) inputRef.current.value = "";
  }

  async function remove(id: string) {
    try { await api.deleteClip(activeProject.id, id); removeClip(id); }
    catch (error) { setError(error instanceof Error ? error.message : "Delete failed"); }
  }

  return <section className="panel overflow-hidden">
    <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-3 sm:px-4">
      <div className="min-w-0"><h2 className="truncate text-sm font-semibold">Sequence timeline</h2><span className="text-[10px] text-white/30">{project.clips.length} clips · {project.fps} fps</span></div>
      <button onClick={() => inputRef.current?.click()} className="flex min-h-10 shrink-0 items-center gap-2 rounded-lg border border-line px-3 text-xs text-white/60 transition hover:bg-white/5 hover:text-white"><Upload size={13}/> Import</button>
      <input ref={inputRef} type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska" hidden onChange={(e) => upload(e.target.files?.[0])}/>
    </div>
    <div className="overflow-x-auto overscroll-x-contain p-3 sm:p-4">
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dragEnd}>
        <SortableContext items={project.clips.map((clip) => clip.id)} strategy={horizontalListSortingStrategy}>
          <div className="flex min-h-24 items-stretch gap-2 sm:min-h-28 sm:gap-3">
            {project.clips.map((clip, index) => <div className="flex items-center gap-2 sm:gap-3" key={clip.id}>
              <SortableClip clip={clip} selected={selected === clip.id} onSelect={() => setSelected(clip.id)} onDelete={() => remove(clip.id)}/>
              {index < project.clips.length - 1 && <div className="h-px w-3 bg-white/15 sm:w-4"/>}
            </div>)}
            <button onClick={() => inputRef.current?.click()} className="grid h-24 w-24 shrink-0 place-items-center rounded-xl border border-dashed border-line text-white/25 transition hover:border-acid/50 hover:text-acid sm:h-28 sm:w-28"><span className="flex flex-col items-center gap-2 text-[10px] uppercase tracking-wider"><Plus size={18}/> Add media</span></button>
          </div>
        </SortableContext>
      </DndContext>
    </div>
  </section>;
}

