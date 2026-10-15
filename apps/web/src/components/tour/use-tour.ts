"use client";

/* Tour state: the viewer's persisted record, start/close controls, viewport. */

import { useCallback, useSyncExternalStore } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNextStep } from "nextstepjs";
import type { TourRecord, TourStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { TOUR_NAME, TOUR_VERSION } from "./steps";

export interface TourPreference {
  record: TourRecord | undefined;
  /** The current tour version was already completed or skipped. */
  seen: boolean;
  persist: (status: TourStatus) => void;
}

export function useTourPreference(): TourPreference {
  const { me, updatePreferences } = useAuth();
  const tours = me?.preferences?.tours;
  const record = tours?.[TOUR_NAME];

  const mutation = useMutation({
    mutationFn: (status: TourStatus) =>
      updatePreferences({
        // The server merges top-level keys only: spread, or other tours' records are lost.
        tours: {
          ...(tours ?? {}),
          [TOUR_NAME]: { status, version: TOUR_VERSION, at: new Date().toISOString() },
        },
      }),
  });
  // `mutate` never throws: a failed save cannot block closing the tour (it is offered again).
  const { mutate } = mutation;
  const persist = useCallback((status: TourStatus) => mutate(status), [mutate]);

  return { record, seen: record?.version === TOUR_VERSION, persist };
}

export interface TourControls {
  start: () => void;
  close: () => void;
  isOpen: boolean;
}

export function useTourControls(): TourControls {
  const { startNextStep, closeNextStep, isNextStepVisible } = useNextStep();
  const start = useCallback(() => startNextStep(TOUR_NAME), [startNextStep]);
  return { start, close: closeNextStep, isOpen: isNextStepVisible };
}

const DESKTOP_QUERY = "(min-width: 768px)"; // Tailwind `md`, where #app-menu is always shown

function subscribeDesktop(onChange: () => void): () => void {
  const query = window.matchMedia(DESKTOP_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribeDesktop,
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => true,
  );
}
