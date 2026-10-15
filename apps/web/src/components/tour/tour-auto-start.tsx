"use client";

/* Auto-starts the tour once, right after org creation (/dashboard?welcome=1).
 * The flag is stripped before the tour starts, so a reload never re-triggers
 * it; a viewer who already completed or skipped this version is not shown it,
 * and neither is anyone while the tour is unavailable (disabled or empty). */

import { Suspense, useEffect, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTourControls, useTourPreference } from "./use-tour";

const WELCOME_PARAM = "welcome";

function TourAutoStartInner() {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const { start, available } = useTourControls();
  const { seen } = useTourPreference();
  const fired = useRef(false);
  const welcome = params.get(WELCOME_PARAM) === "1";

  useEffect(() => {
    if (!welcome || fired.current) return;
    fired.current = true;
    const remaining = new URLSearchParams(params.toString());
    remaining.delete(WELCOME_PARAM);
    const query = remaining.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    // Next frame: the dashboard's anchors are laid out before the first spotlight.
    // Not cancelled on cleanup: the URL change re-runs this effect (as does
    // StrictMode), and the latch above has already spent the one start.
    if (!seen && available) requestAnimationFrame(start);
  }, [welcome, params, pathname, router, seen, available, start]);

  return null;
}

export function TourAutoStart() {
  return (
    <Suspense fallback={null}>
      <TourAutoStartInner />
    </Suspense>
  );
}
