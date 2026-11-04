import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach the class merger the brand radii and shadows from the theme, so a radius or
// shadow passed in `className` replaces the component's own instead of sitting beside it.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      radius: ["card", "field", "modal", "signin"],
      shadow: ["card", "card-hover", "overlay"],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Smooth scrolling, or an instant jump when the person prefers reduced motion. */
export function scrollBehavior(): ScrollBehavior {
  const reduce =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reduce ? "auto" : "smooth";
}
