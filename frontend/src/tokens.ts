/** A semantic token's current value (docs/design.md, "Theming seams"), for canvas/SVG code that can't use `var()`. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
