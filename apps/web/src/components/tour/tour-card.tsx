"use client";

/* The tour's card, rendered by NextStep for every step.
 *
 * NextStep ships no ARIA roles and no focus management, so the card supplies
 * them: a labelled modal dialog that takes focus on each step, keeps Tab
 * inside itself, and hands focus back to whatever opened it. */

import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import type { CardComponentProps } from "nextstepjs";
import { ArrowLeft, ArrowRight, Check, ExternalLink } from "lucide-react";
import { useBranding } from "@/lib/runtime-config";

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";
const PRESS = "transition-[transform,background-color,color] duration-150 active:scale-[0.97]";

/** Minimal focus trap: wrap Tab / Shift+Tab among the dialog's own controls. */
function wrapTab(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key !== "Tab") return;
  const dialog = event.currentTarget;
  const nodes = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
  if (nodes.length === 0) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || active === dialog)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

/** Focus the dialog on every step; restore the opener's focus when the tour closes. */
function useDialogFocus(currentStep: number) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      // The opener may be gone by now (banner replaced, mobile menu closed):
      // land on <main> rather than letting focus fall to <body>.
      const openerVisible = opener?.isConnected === true && opener.offsetParent !== null;
      const target = openerVisible ? opener : document.querySelector<HTMLElement>("main");
      target?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    dialogRef.current?.focus({ preventScroll: true });
  }, [currentStep]);

  return dialogRef;
}

function Progress({ current, total }: { current: number; total: number }) {
  return (
    <div className="mt-5 flex gap-1" aria-hidden>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`h-1 flex-1 rounded-full transition-colors duration-300 ${
            i <= current ? "bg-primary" : "bg-zinc-200"
          }`}
        />
      ))}
    </div>
  );
}

function DocsLink({ href }: { href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`mt-3 inline-flex items-center gap-1 rounded-md text-sm font-medium text-zinc-900 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-900 ${FOCUS_RING}`}
    >
      Read the docs
      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
    </a>
  );
}

export function TourCard({
  step,
  currentStep,
  totalSteps,
  nextStep,
  prevStep,
  skipTour,
  arrow,
}: CardComponentProps) {
  const titleId = useId();
  const bodyId = useId();
  const dialogRef = useDialogFocus(currentStep);
  const docs = useBranding().links.docs;
  const isFirst = currentStep === 0;
  const isLast = currentStep === totalSteps - 1;
  // The step list is frozen while the tour is open, but never render past its end.
  if (!step) return null;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      tabIndex={-1}
      onKeyDown={wrapTab}
      className="relative w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-zinc-200 bg-white p-5 text-zinc-900 shadow-xl shadow-zinc-950/10 outline-none"
    >
      {arrow}
      <div className="flex items-start gap-3">
        {step.icon && (
          <span className="shrink-0 rounded-lg bg-zinc-100 p-2 text-zinc-700 ring-1 ring-inset ring-zinc-200/80">
            {step.icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="text-base font-semibold leading-snug tracking-tight">
            {step.title}
          </h2>
          <p className="mt-0.5 text-xs font-medium tabular-nums text-zinc-400">
            Step {currentStep + 1} of {totalSteps}
          </p>
        </div>
      </div>

      <div id={bodyId} className="mt-3 text-sm leading-relaxed text-zinc-600">
        {step.content}
      </div>
      {isLast && docs && <DocsLink href={docs} />}

      <Progress current={currentStep} total={totalSteps} />

      <div className="mt-4 flex items-center justify-between gap-3">
        {!isLast && skipTour ? (
          <button
            type="button"
            onClick={skipTour}
            className={`-ml-1.5 rounded-md px-1.5 py-1 text-sm text-zinc-500 hover:text-zinc-900 ${FOCUS_RING} ${PRESS}`}
          >
            Skip tour
          </button>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          {!isFirst && (
            <button
              type="button"
              onClick={prevStep}
              className={`inline-flex items-center gap-1 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:text-zinc-900 ${FOCUS_RING} ${PRESS}`}
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              Back
            </button>
          )}
          <button
            type="button"
            onClick={nextStep}
            className={`inline-flex items-center gap-1 rounded-lg bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 ${FOCUS_RING} ${PRESS}`}
          >
            {isLast ? "Done" : "Next"}
            {isLast ? (
              <Check className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
