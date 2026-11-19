import { cn } from "../lib/utils";
import { Icon } from "../icons";

type LoadingStarProps =
  | {
      /** Inside a button: follows the button's text colour. */
      size?: "button" | "large-button";
      message?: never;
      className?: string;
    }
  | {
      /** Standing in for a page or section. A message is required: the yellow star alone says nothing. */
      size: "page";
      message: string;
      className?: string;
    };

/** The only loading indicator: the brand asterisk, spinning (pulsing under reduced motion). */
export function LoadingStar({
  size = "button",
  message,
  className,
}: LoadingStarProps) {
  if (size === "page") {
    return (
      <div
        role="status"
        data-slot="loading-star"
        className={cn(
          "flex flex-col items-center justify-center gap-4 py-12 text-center",
          className,
        )}
      >
        <Icon name="star" size="display" className="loading-star text-yellow" />
        <p className="text-base font-semibold text-blue">{message}</p>
      </div>
    );
  }
  return (
    <span
      data-slot="loading-star"
      aria-hidden="true"
      className={cn("inline-flex", className)}
    >
      <Icon
        name="star"
        className="loading-star"
        style={{
          width: size === "button" ? 18 : 26,
          height: size === "button" ? 18 : 26,
        }}
      />
    </span>
  );
}
