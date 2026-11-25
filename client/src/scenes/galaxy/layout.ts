// Star-chart geometry (no Phaser), unit-tested in layout.test.ts. Generic camera maths
// lives in ../shared/viewport.ts; this adds only what's specific to the galaxy.
// "Galaxy units" are the server's coordinates; "chart units" are the same scale, but
// rotated 90° in portrait so the ellipse's long axis runs along the long screen side.

import { type Size, type Vec, centredRect, clampToRect, screenToWorld } from "../shared/viewport";

export {
  MAX_ZOOM_FACTOR,
  TAP_RADIUS_PX,
  type Size,
  type Vec,
  clamp,
  fitZoom,
  isPortrait,
  nearestWithin,
  zoomAt,
} from "../shared/viewport";

export function toChart(p: Vec, portrait: boolean): Vec {
  return portrait ? { x: -p.y, y: p.x } : { x: p.x, y: p.y };
}

/** Full width/height of the galaxy ellipse in chart units. */
export function chartExtent(semiA: number, semiB: number, portrait: boolean): Size {
  return portrait
    ? { width: 2 * semiB, height: 2 * semiA }
    : { width: 2 * semiA, height: 2 * semiB };
}

/** Keep the camera centre over the chart (centred on the origin). */
export const clampCenter = (center: Vec, extent: Size): Vec =>
  clampToRect(center, centredRect(extent));

/** Chart point under a screen point. */
export const screenToChart = screenToWorld;
