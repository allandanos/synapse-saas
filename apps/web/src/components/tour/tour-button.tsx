"use client";

/* "Take the tour": replays the welcome tour on demand (shell footer).
 *
 * The page-anchored steps (plan, usage, features) live on /dashboard, so a
 * replay from any other console route navigates there first and starts the
 * tour once that route has rendered — otherwise NextStep would spotlight a
 * stale target for the anchors it cannot find. */

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Compass } from "lucide-react";
import { useTourControls } from "./use-tour";

const TOUR_HOME = "/dashboard";

export function TourButton({ onStart }: { onStart?: () => void }) {
  const { start } = useTourControls();
  const pathname = usePathname();
  const router = useRouter();
  const pendingStart = useRef(false);

  useEffect(() => {
    if (!pendingStart.current || pathname !== TOUR_HOME) return;
    pendingStart.current = false;
    // Next frame: the dashboard's anchors are laid out before the first spotlight.
    requestAnimationFrame(start);
  }, [pathname, start]);

  function onClick() {
    onStart?.();
    if (pathname === TOUR_HOME) {
      start();
      return;
    }
    pendingStart.current = true;
    router.push(TOUR_HOME);
  }

  return (
    <button
      type="button"
      data-tour="take-the-tour"
      onClick={onClick}
      className="mb-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm text-zinc-600 hover:bg-white hover:text-zinc-900"
    >
      <Compass className="h-4 w-4" aria-hidden />
      Take the tour
    </button>
  );
}
