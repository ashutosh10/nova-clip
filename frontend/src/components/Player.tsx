"use client";

import { Download, Film } from "lucide-react";
import { assetUrl } from "@/lib/api";
import { useStudio } from "@/store/studio";

export function Player() {
  const project = useStudio((state) => state.project);
  const selected = useStudio((state) => state.selectedClipId);
  const clip = project?.clips.find((item) => item.id === selected);
  const source = assetUrl(project?.master_url || clip?.media_url || null);
  return <section className="panel relative flex min-h-[310px] overflow-hidden bg-black">
    {source ? <video key={source} src={source} controls className="h-full w-full object-contain"/> : <div className="m-auto flex flex-col items-center gap-3 text-white/20"><div className="grid size-16 place-items-center rounded-full border border-white/10"><Film size={24}/></div><p className="text-xs">Your selected clip will appear here</p></div>}
    <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-black/65 px-2 py-1 text-[9px] font-bold uppercase tracking-[.16em] text-white/60">{project?.master_url ? "Master preview" : "Source monitor"}</div>
    {source && <a href={source} download className="absolute right-3 top-3 grid size-8 place-items-center rounded-md bg-black/65 text-white/60 transition hover:text-acid" title="Download video"><Download size={14}/></a>}
  </section>;
}

