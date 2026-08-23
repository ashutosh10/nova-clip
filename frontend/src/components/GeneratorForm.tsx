"use client";

import { useState } from "react";
import { Aperture, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useStudio } from "@/store/studio";

export function GeneratorForm({ onJob }: { onJob: (id: string) => void }) {
  const project = useStudio((state) => state.project);
  const upsertClip = useStudio((state) => state.upsertClip);
  const upsertJob = useStudio((state) => state.upsertJob);
  const setError = useStudio((state) => state.setError);
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(10);
  const [preset, setPreset] = useState<"fast" | "balanced" | "quality">("fast");
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    if (!project || prompt.trim().length < 3) return;
    setSubmitting(true); setError(null);
    try {
      const result = await api.generateVideo(project.id, {
        prompt: prompt.trim(), duration_seconds: duration, generation_preset: preset,
        inference_steps: preset === "quality" ? 10 : 4, guidance_scale: preset === "quality" ? 5 : 1,
      });
      result.clips.forEach(upsertClip); upsertJob(result.job); onJob(result.job.id); setPrompt("");
    } catch (error) { setError(error instanceof Error ? error.message : "Could not enqueue video"); }
    finally { setSubmitting(false); }
  }

  return <section className="panel flex h-full flex-col overflow-hidden">
    <div className="flex items-center justify-between border-b border-line px-4 py-3">
      <div><p className="eyebrow">AI video creator</p><h2 className="mt-1 text-sm font-semibold">Describe the video you want</h2></div>
      <div className="grid size-9 place-items-center rounded-full bg-acid/10 text-acid"><Aperture size={17}/></div>
    </div>
    <div className="flex flex-1 flex-col gap-4 p-4">
      <label className="flex flex-1 flex-col gap-2">
        <span className="eyebrow">Scene idea</span>
        <textarea
          value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={2000}
          placeholder="A lone astronaut walks through a field of silver grass at dawn..."
          className="input min-h-32 flex-1 resize-none leading-relaxed"
        />
        <span className="text-right text-[10px] text-white/25">{prompt.length} / 2000</span>
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-2"><span className="eyebrow">Video length</span><select className="input" value={duration} onChange={(e) => setDuration(Number(e.target.value))}><option value={5}>5 seconds</option><option value={10}>10 seconds</option><option value={15}>15 seconds</option><option value={20}>20 seconds</option><option value={30}>30 seconds</option></select></label>
        <label className="space-y-2"><span className="eyebrow">Quality</span><select className="input" value={preset} onChange={(e) => setPreset(e.target.value as "fast" | "balanced" | "quality")}><option value="fast">Quick draft</option><option value="balanced">Better quality</option><option value="quality">Best quality  -  slow</option></select></label>
      </div>
      <div className="rounded-xl border border-acid/15 bg-acid/[.04] px-3 py-2.5 text-[11px] leading-relaxed text-white/45">
        <p>{duration > 5 ? `Nova will plan ${duration / 5} shots and use the previous clip's last 5 frames to keep motion, subjects, and style continuous before combining them into one ${duration}-second video.` : "Nova will create one shot and prepare a ready-to-download video automatically."}</p>
        <p className="mt-1.5 text-white/30">{preset === "quality" ? "Highest detail. Allow considerably more processing time." : preset === "balanced" ? "A good balance of detail and processing time." : "Fastest option for trying an idea."}</p>
      </div>
      <button onClick={submit} disabled={submitting || prompt.trim().length < 3} className="flex items-center justify-center gap-2 rounded-xl bg-acid px-4 py-3 text-sm font-bold text-ink transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-35">
        <Sparkles size={16}/>{submitting ? "Joining GPU queue..." : "Generate " + duration + "-second video"}
      </button>
    </div>
  </section>;
}

