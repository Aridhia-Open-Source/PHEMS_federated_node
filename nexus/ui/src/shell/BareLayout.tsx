import type { ReactNode } from "react";

import { BrandCard } from "@/ui";

import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";

/**
 * The ring of stars: fixed to the window centre, about 88% of the window width (at least
 * 1100px). The artwork is neutral yellow at varying strength, not the dataset star palette.
 */
function StarRing() {
  return (
    <img
      src={`${import.meta.env.BASE_URL}stars.svg`}
      alt=""
      aria-hidden="true"
      data-slot="star-ring"
      className="star-ring pointer-events-none fixed top-1/2 left-1/2 aspect-[2266/2165] w-[max(88vw,1100px)] max-w-none -translate-x-1/2 -translate-y-1/2"
    />
  );
}

/** Plain page without the app header, for login. */
export function BareLayout({
  children,
  title,
  description,
  width = "narrow",
}: {
  children: ReactNode;
  /** When given, the content sits on the blue card under this title. */
  title?: string;
  description?: ReactNode;
  width?: "narrow" | "wide";
}) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      <StarRing />
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle />
      </div>
      <main
        id="content"
        className={`relative mx-auto flex min-h-screen w-full flex-col justify-center gap-6 px-4 py-12 sm:px-6 ${width === "wide" ? "max-w-2xl" : "max-w-xl"}`}
      >
        {title ? (
          <BrandCard logo={<Logo />} title={title} description={description}>
            {children}
          </BrandCard>
        ) : (
          children
        )}
      </main>
    </div>
  );
}
