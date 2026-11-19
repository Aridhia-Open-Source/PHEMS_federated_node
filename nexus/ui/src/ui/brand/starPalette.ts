// Each dataset gets a star colour from its position in the catalogue, so neighbours differ
// and a dataset keeps its colour wherever it appears. The colours are decorative only
// and are not used for anything else.
export const STAR_PALETTE = [
  "#E3A6E4",
  "#A3DDB9",
  "#A9B0EA",
  "#F4BBA3",
  "#C3AEEC",
  "#A2D1EA",
  "#9ED6CB",
  "#EEAABB",
  "#C6DD9E",
  "#D3A3D3",
] as const;

/** The star colour for a position in the list. Wraps after the last colour. */
export function starColour(index: number): string {
  const n = STAR_PALETTE.length;
  const i = Number.isFinite(index) ? Math.trunc(index) : 0;
  return STAR_PALETTE[((i % n) + n) % n]!;
}

/** A stable position derived from an id, for when the list position is not known. */
export function starIndexFromId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return hash % STAR_PALETTE.length;
}
