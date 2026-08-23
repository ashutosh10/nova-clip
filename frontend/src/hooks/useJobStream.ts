"use client";

import { useEffect } from "react";
import { API_ORIGIN } from "@/lib/api";
import type { Job } from "@/lib/types";
import { useStudio } from "@/store/studio";

export function useJobStream(jobId: string | null, onTerminal?: () => void) {
  const upsertJob = useStudio((state) => state.upsertJob);
  useEffect(() => {
    if (!jobId) return;
    const base = API_ORIGIN.replace(/^http/, "ws");
    let terminal = false;
    const socket = new WebSocket(`${base}/api/v1/jobs/${jobId}/stream`);
    socket.onmessage = (event) => {
      const update = JSON.parse(event.data);
      if (update.type === "heartbeat") return;
      const current = useStudio.getState().jobs[jobId];
      if (current) upsertJob({ ...current, ...update });
      if (update.status === "SUCCEEDED" || update.status === "FAILED") {
        terminal = true;
        onTerminal?.();
        socket.close();
      }
    };
    socket.onerror = () => socket.close();
    return () => { if (!terminal) socket.close(); };
  }, [jobId, onTerminal, upsertJob]);
}

