"use client";

/* Mounts NextStep around the dashboard shell with the viewer's tour.
 * Lives inside the dashboard layout's `ready` gate: `me` and the active org
 * are known, and the subtree is client-only (no hydration mismatch). */

import { useMemo, useState, type ReactNode } from "react";
import { NextStep, NextStepProvider, useNextStep } from "nextstepjs";
import { MotionConfig, useReducedMotion, type Transition } from "motion/react";
import { useAuth } from "@/lib/auth-context";
import { useBranding } from "@/lib/runtime-config";
import { buildTour } from "./steps";
import { TourCard } from "./tour-card";
import { TourAvailabilityContext, useIsDesktop, useTourPreference } from "./use-tour";

// Expo-out: the card settles into place instead of NextStep's overshooting default.
const CARD_TRANSITION: Transition = { ease: [0.16, 1, 0.3, 1], duration: 0.45 };
const INSTANT: Transition = { duration: 0 };
// Spotlight dim: zinc-950 at 40%, matching the console's neutrals.
const SHADOW_RGB = "9, 9, 11";
const SHADOW_OPACITY = "0.4";
const ARROW_STYLE = { color: "white" } as const; // matches the card's bg-white

function TourHost({ children }: { children: ReactNode }) {
  const { me, activeOrgId } = useAuth();
  const { isNextStepVisible } = useNextStep();
  const { name: brandName, tour } = useBranding();
  const isDesktop = useIsDesktop();
  const reduceMotion = useReducedMotion();
  const { persist } = useTourPreference();

  // Memo on the joined keys, not the array: `me` is replaced on every preferences save.
  const roleKey = me?.orgs.find((org) => org.id === activeOrgId)?.role_keys.join(",") ?? "";
  const roleKeys = useMemo(() => (roleKey ? roleKey.split(",") : []), [roleKey]);
  const permissionKey =
    me?.orgs.find((org) => org.id === activeOrgId)?.permission_keys?.join(",") ?? "";
  const permissions = useMemo<ReadonlySet<string>>(
    () => new Set(permissionKey ? permissionKey.split(",") : []),
    [permissionKey],
  );
  const isPlatformAdmin = me?.is_platform_admin ?? false;
  const tours = useMemo(
    () => [buildTour({ roleKeys, permissions, isPlatformAdmin, isDesktop, brandName, tour })],
    [roleKeys, permissions, isPlatformAdmin, isDesktop, brandName, tour],
  );
  // Disabled by the deployment, or nothing left for this viewer: offer no tour at all.
  const available = tour.enabled && tours[0].steps.length > 0;

  // Freeze the step list while the tour is open: a rebuild (viewport crossing
  // `md`, role change) could leave NextStep's step index past the new end.
  // Adjusting state during render is React's documented way to track a changed input.
  const [activeTours, setActiveTours] = useState(tours);
  if (!isNextStepVisible && activeTours !== tours) setActiveTours(tours);

  return (
    <NextStep
      steps={activeTours}
      cardComponent={TourCard}
      cardTransition={reduceMotion ? INSTANT : CARD_TRANSITION}
      onComplete={() => persist("completed")}
      onSkip={() => persist("skipped")}
      displayArrow
      arrowStyle={ARROW_STYLE}
      shadowRgb={SHADOW_RGB}
      shadowOpacity={SHADOW_OPACITY}
      disableConsoleLogs
    >
      <TourAvailabilityContext.Provider value={available}>{children}</TourAvailabilityContext.Provider>
    </NextStep>
  );
}

export function TourProvider({ children }: { children: ReactNode }) {
  return (
    <NextStepProvider>
      <MotionConfig reducedMotion="user">
        <TourHost>{children}</TourHost>
      </MotionConfig>
    </NextStepProvider>
  );
}
