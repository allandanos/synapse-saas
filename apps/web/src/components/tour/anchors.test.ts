/* Drift guard: the tour enums in lib/tour-config.ts (mirrored by the API's
 * branding models) must match the `data-tour` anchors the console renders
 * and the built-in steps in steps.tsx. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { BUILTIN_STEP_IDS, TOUR_ANCHORS } from "@/lib/tour-config";
import { builtinStepOrder } from "./steps";

const SOURCES = ["../app-shell.tsx", "../../app/dashboard/page.tsx", "./tour-button.tsx"];

function source(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");
}

/** Literal `data-tour="x"` attributes plus the shell's NAV `tour: "x"` entries (rendered as nav-x). */
function renderedAnchors(): readonly string[] {
  const text = SOURCES.map(source).join("\n");
  const literal = [...text.matchAll(/data-tour="([a-z-]+)"/g)].map((m) => m[1]);
  const nav = [...text.matchAll(/\btour: "([a-z-]+)"/g)].map((m) => `nav-${m[1]}`);
  return [...new Set([...literal, ...nav])].sort();
}

describe("tour enums", () => {
  it("TOUR_ANCHORS equals the data-tour anchors the console renders", () => {
    expect(renderedAnchors()).toEqual([...TOUR_ANCHORS].sort());
  });

  it("BUILTIN_STEP_IDS equals the built-in steps, in tour order", () => {
    expect(builtinStepOrder()).toEqual([...BUILTIN_STEP_IDS]);
  });
});
