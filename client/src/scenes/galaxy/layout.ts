// Pure star-chart geometry (no Phaser), unit-tested in layout.test.ts.
// "Galaxy units" are the server's coordinates; "chart units" are the same scale, but
// rotated 90° in portrait so the ellipse's long axis runs along the long screen side.

export interface Vec {
  readonly x: number;
  readonly y: number;
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

/** Half of a 44 px tap target, in screen pixels. */
export const TAP_RADIUS_PX = 22;
/** How far in the player may zoom, relative to the fit-to-screen zoom. */
export const MAX_ZOOM_FACTOR = 10;

export const isPortrait = (view: Size): boolean => view.height > view.width;

export function toChart(p: Vec, portrait: boolean): Vec {
  return portrait ? { x: -p.y, y: p.x } : { x: p.x, y: p.y };
}

/** Full width/height of the galaxy ellipse in chart units. */
export function chartExtent(semiA: number, semiB: number, portrait: boolean): Size {
  return portrait
    ? { width: 2 * semiB, height: 2 * semiA }
    : { width: 2 * semiA, height: 2 * semiB };
}

/** Zoom at which the whole chart fits the view, leaving `margin` (fraction) free. */
export function fitZoom(extent: Size, view: Size, margin = 0.06): number {
  const zoom = Math.min(view.width / extent.width, view.height / extent.height);
  return zoom * (1 - margin);
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * New camera centre after a zoom change, keeping the chart point under `screen` fixed
 * (pinch midpoint, mouse cursor).
 */
export function zoomAt(
  center: Vec,
  zoomOld: number,
  zoomNew: number,
  screen: Vec,
  view: Size,
): Vec {
  const dx = screen.x - view.width / 2;
  const dy = screen.y - view.height / 2;
  return {
    x: center.x + dx / zoomOld - dx / zoomNew,
    y: center.y + dy / zoomOld - dy / zoomNew,
  };
}

/** Keep the camera centre over the chart so the galaxy can't be dragged off-screen. */
export function clampCenter(center: Vec, extent: Size): Vec {
  return {
    x: clamp(center.x, -extent.width / 2, extent.width / 2),
    y: clamp(center.y, -extent.height / 2, extent.height / 2),
  };
}

/** Chart point under a screen point. */
export function screenToChart(screen: Vec, center: Vec, zoom: number, view: Size): Vec {
  return {
    x: center.x + (screen.x - view.width / 2) / zoom,
    y: center.y + (screen.y - view.height / 2) / zoom,
  };
}

/** Index of the point closest to `target` within `maxDistance`, or null. */
export function nearestWithin(
  points: readonly Vec[],
  target: Vec,
  maxDistance: number,
): number | null {
  let best: number | null = null;
  let bestD2 = maxDistance * maxDistance;
  points.forEach((p, index) => {
    const d2 = (p.x - target.x) ** 2 + (p.y - target.y) ** 2;
    if (d2 <= bestD2) {
      best = index;
      bestD2 = d2;
    }
  });
  return best;
}
