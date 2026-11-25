// Pure camera maths shared by every pannable/zoomable scene (no Phaser).
// "World" coordinates are whatever the scene draws in; the camera maps them to screen
// pixels with a centre and a zoom.

export interface Vec {
  readonly x: number;
  readonly y: number;
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

/** An axis-aligned world rectangle: top-left corner + size. */
export interface Rect extends Vec, Size {}

/** Half of a 44 px tap target, in screen pixels. */
export const TAP_RADIUS_PX = 22;
/** How far in the player may zoom, relative to the fit-to-screen zoom. */
export const MAX_ZOOM_FACTOR = 10;

export const isPortrait = (view: Size): boolean => view.height > view.width;

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Zoom at which `extent` fits the view, leaving `margin` (fraction) free. */
export function fitZoom(extent: Size, view: Size, margin = 0.06): number {
  const zoom = Math.min(view.width / extent.width, view.height / extent.height);
  return zoom * (1 - margin);
}

/**
 * New camera centre after a zoom change, keeping the world point under `screen` fixed
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

/** World point under a screen point. */
export function screenToWorld(screen: Vec, center: Vec, zoom: number, view: Size): Vec {
  return {
    x: center.x + (screen.x - view.width / 2) / zoom,
    y: center.y + (screen.y - view.height / 2) / zoom,
  };
}

/** Keep the camera centre over the content so it can't be dragged off-screen. */
export function clampToRect(center: Vec, rect: Rect): Vec {
  return {
    x: clamp(center.x, rect.x, rect.x + rect.width),
    y: clamp(center.y, rect.y, rect.y + rect.height),
  };
}

/** A rectangle of the given size centred on the world origin. */
export const centredRect = (extent: Size): Rect => ({
  x: -extent.width / 2,
  y: -extent.height / 2,
  width: extent.width,
  height: extent.height,
});

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
