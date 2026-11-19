import { shellMessages } from "./messages";

/** Yellow asterisk (from the EHDS Relay artwork) and the app name in white, for the blue header and card. */
export function Logo() {
  return (
    <span data-slot="logo" className="inline-flex items-center gap-3 text-white">
      <svg viewBox="166 0 31 31" aria-hidden="true" className="h-7 w-auto">
        <path
          d="M192.859 4.20256L196.715 10.7948L187.525 15.0798L196.715 19.2823L192.859 25.957L184.572 20.1064L185.556 30.1595H177.925L178.91 20.1064L170.623 25.957L166.766 19.2823L175.956 15.0798L166.766 10.7948L170.623 4.20256L178.91 10.0532L177.925 0H185.556L184.572 9.97078L192.859 4.20256Z"
          fill="#f8f121"
        />
      </svg>
      <span className="text-xl leading-none font-semibold">{shellMessages.appName}</span>
    </span>
  );
}
