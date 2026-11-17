"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** Analysis state lives in the URL so every view is shareable. */
export function useUrlState() {
  const sp = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const get = useCallback((k: string) => sp.get(k) ?? "", [sp]);
  const set = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(sp.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      router.replace(`${path}?${next.toString()}`, { scroll: false });
    },
    [sp, router, path],
  );
  return { get, set };
}
