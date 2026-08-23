"use client";

import { useEffect, useState } from "react";
import { Scissors } from "lucide-react";
import { api } from "@/lib/api";
import { useStudio } from "@/store/studio";

export function Inspector() {
  const project = useStudio((state) => state.project);
  const selectedId = useStudio((state) => state.selectedClipId);
  const upsertClip = useStudio((state) => state.upsertClip);
  const setError = useStudio((state) => state.setError);
  const clip = project?.clips.find((item) => item.id === selectedId);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  useEffect(() => { if (clip) { setStart(clip.trim_start); setEnd(clip.trim_end ?? clip.duration_seconds ?? 0); } }, [clip]);
  if (!project || !clip) return <section className="panel grid h-full min-h-48 place-items-center p-6 text-center text-xs text-white/30">Select a clip to inspect its prompt and trim range.</section>;
  const projectId = project.id, clipId = clip.id;
  async function save() {
    try { upsertClip(await api.trim(projectId, clipId, start, end)); }
    catch (error) { setError(error instanceof Error ? error.message : "Trim failed"); }
  }
  const max = clip.duration_seconds ?? 0;
  return <section className="panel h-full overflow-y-auto p-4">
    <div className="mb-5 flex items-center gap-2"><Scissors size={14} className="text-acid"/><h2 className="text-sm font-semibold">Clip inspector</h2></div>
    <div className="space-y-5">
      <div><p className="eyebrow mb-2">Original direction</p><p className="text-xs leading-relaxed text-white/55">{clip.prompt || "Imported media"}</p></div>
      {clip.expanded_prompt && <div><p className="eyebrow mb-2">Enhanced prompt</p><p className="text-[11px] leading-relaxed text-white/35">{clip.expanded_prompt}</p></div>}
      {clip.status === "READY" && <div className="space-y-3 border-t border-line pt-4">
        <div className="flex justify-between"><p className="eyebrow">Trim range</p><span className="text-[10px] text-acid">{start.toFixed(1)} — {end.toFixed(1)} sec</span></div>
        <label className="block text-[10px] text-white/35">In point<input type="range" min={0} max={Math.max(0, end - .1)} step="0.1" value={start} onChange={(e) => setStart(Number(e.target.value))} className="mt-2 w-full"/></label>
        <label className="block text-[10px] text-white/35">Out point<input type="range" min={Math.min(max, start + .1)} max={max} step="0.1" value={end} onChange={(e) => setEnd(Number(e.target.value))} className="mt-2 w-full"/></label>
        <button onClick={save} className="w-full rounded-lg border border-line py-2 text-xs font-semibold text-white/60 transition hover:border-acid/40 hover:text-acid">Save trim</button>
      </div>}
      {clip.error && <p className="rounded-lg bg-coral/10 p-3 text-[11px] text-coral">{clip.error}</p>}
    </div>
  </section>;
}

