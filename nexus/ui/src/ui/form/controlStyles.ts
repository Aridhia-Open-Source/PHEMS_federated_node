// Shared looks for the native checkbox, radio button and switch. The inputs stay native
// (default look removed) so keyboard and screen reader behaviour comes for free.

const base =
  "peer shrink-0 appearance-none border-2 border-ink-3 bg-card transition-colors hover:border-blue disabled:cursor-not-allowed disabled:border-blue-tint-80 disabled:bg-blue-tint-90 disabled:hover:border-blue-tint-80 aria-invalid:border-destructive";

const baseOnBlue =
  "peer shrink-0 appearance-none border-2 border-white bg-transparent transition-colors disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-error";

export function checkboxClass(onBlue: boolean): string {
  return onBlue
    ? `${baseOnBlue} size-[22px] rounded-[6px] checked:border-yellow checked:bg-yellow`
    : `${base} size-[22px] rounded-[6px] checked:border-blue checked:bg-brand`;
}

// The dot is drawn by ::before: 10px, centred, grown in when checked (no shadow).
const radioDot =
  "grid size-[22px] place-content-center rounded-full before:size-2.5 before:scale-0 before:rounded-full before:transition-transform before:content-[''] checked:before:scale-100";

export function radioClass(onBlue: boolean): string {
  return onBlue
    ? `${baseOnBlue} ${radioDot} before:bg-yellow checked:border-yellow`
    : `${base} ${radioDot} before:bg-blue checked:border-blue disabled:before:bg-ink-3`;
}

export function toggleClass(onBlue: boolean): string {
  const knob =
    "relative h-7 w-12 rounded-full before:absolute before:top-[3px] before:left-[3px] before:size-[18px] before:rounded-full before:transition-transform before:content-[''] checked:before:translate-x-5";
  return onBlue
    ? `${baseOnBlue} ${knob} before:bg-white checked:border-yellow checked:bg-yellow checked:before:bg-blue`
    : `${base} ${knob} before:bg-ink-3 checked:border-blue checked:bg-brand checked:before:bg-yellow disabled:before:bg-blue-tint-80`;
}
