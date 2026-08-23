"use client";

import { Activity, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { useStudio } from "@/store/studio";

export function QueueStatus() {
  const jobsById = useStudio((state) => state.jobs);
  const jobs = Object.values(jobsById);
  const active = jobs.filter((job) => job.status === "QUEUED" || job.status === "RUNNING");
  const recent = (active.length ? active : jobs).slice(-3).reverse();
  return <section className="panel overflow-hidden">
    <div className="flex items-center justify-between border-b border-line px-4 py-3"><div className="flex items-center gap-2"><Activity size={14} className="text-acid"/><h2 className="text-sm font-semibold">Render queue</h2></div><span className="rounded-full bg-white/5 px-2 py-1 text-[9px] font-bold tracking-wider text-white/35">{active.length} ACTIVE</span></div>
    <div className="divide-y divide-line">
      {!recent.length && <p className="px-4 py-5 text-xs text-white/30">No renders in this session.</p>}
      {recent.map((job) => <div key={job.id} className="px-4 py-3">
        <div className="mb-2 flex items-center gap-2">
          {job.status === "SUCCEEDED" ? <CheckCircle2 size={13} className="text-acid"/> : job.status === "FAILED" ? <XCircle size={13} className="text-coral"/> : <CircleDashed size={13} className="animate-spin text-acid"/>}
          <span className="flex-1 truncate text-[11px] font-semibold">{job.message}</span><span className="text-[10px] tabular-nums text-white/40">{Math.round(job.progress)}%</span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-white/[.06]"><div className={`h-full transition-all duration-500 ${job.status === "FAILED" ? "bg-coral" : "bg-acid"}`} style={{ width: `${job.progress}%` }}/></div>
        {job.status === "RUNNING" && <div className="mt-2 flex justify-between text-[9px] text-white/25"><span>{job.current_step && job.total_steps ? `Step ${job.current_step}/${job.total_steps}` : job.kind}</span><span>{job.speed ? `${job.speed.toFixed(2)} it/s` : ""}{job.eta_seconds ? ` · ${Math.ceil(job.eta_seconds)}s left` : ""}</span></div>}
      </div>)}
    </div>
  </section>;
}

