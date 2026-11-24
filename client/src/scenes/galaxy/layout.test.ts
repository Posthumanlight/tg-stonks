import { describe, expect, it } from "vitest";

import {
  chartExtent,
  clampCenter,
  fitZoom,
  isPortrait,
  nearestWithin,
  screenToChart,
  toChart,
  zoomAt,
} from "./layout";

const PHONE = { width: 360, height: 640 };

describe("orientation", () => {
  it("turns the ellipse so its long axis follows the long screen side", () => {
    expect(isPortrait(PHONE)).toBe(true);
    expect(chartExtent(1000, 600, true)).toEqual({ width: 1200, height: 2000 });
    expect(chartExtent(1000, 600, false)).toEqual({ width: 2000, height: 1200 });
    // The ellipse's long-axis end (a, 0) ends up on the vertical axis.
    expect(toChart({ x: 1000, y: 0 }, true)).toEqual({ x: -0, y: 1000 });
    expect(toChart({ x: 3, y: 4 }, false)).toEqual({ x: 3, y: 4 });
  });

  it("rotation preserves distances", () => {
    const a = toChart({ x: 10, y: -20 }, true);
    const b = toChart({ x: -5, y: 40 }, true);
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeCloseTo(Math.hypot(15, -60));
  });
});

describe("fitZoom", () => {
  it("fits the limiting side with a margin", () => {
    const zoom = fitZoom({ width: 1200, height: 2000 }, PHONE, 0);
    expect(zoom).toBeCloseTo(0.3); // 360 / 1200 < 640 / 2000
    expect(fitZoom({ width: 1200, height: 2000 }, PHONE, 0.1)).toBeCloseTo(0.27);
  });
});

describe("zoomAt", () => {
  it("keeps the chart point under the anchor fixed", () => {
    const center = { x: 100, y: -50 };
    const anchor = { x: 300, y: 100 };
    const before = screenToChart(anchor, center, 0.5, PHONE);
    const next = zoomAt(center, 0.5, 2, anchor, PHONE);
    const after = screenToChart(anchor, next, 2, PHONE);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it("zooming at the view centre does not move the camera", () => {
    const center = { x: 7, y: 9 };
    expect(zoomAt(center, 1, 3, { x: 180, y: 320 }, PHONE)).toEqual(center);
  });
});

describe("clampCenter", () => {
  it("keeps the camera over the chart", () => {
    const extent = { width: 1200, height: 2000 };
    expect(clampCenter({ x: 5000, y: -5000 }, extent)).toEqual({ x: 600, y: -1000 });
    expect(clampCenter({ x: 10, y: 20 }, extent)).toEqual({ x: 10, y: 20 });
  });
});

describe("nearestWithin", () => {
  const points = [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 100, y: 100 },
  ];

  it("returns the closest point inside the radius", () => {
    expect(nearestWithin(points, { x: 7, y: 1 }, 20)).toBe(1);
    expect(nearestWithin(points, { x: 2, y: 0 }, 20)).toBe(0);
  });

  it("returns null when nothing is in range", () => {
    expect(nearestWithin(points, { x: 50, y: 50 }, 20)).toBeNull();
    expect(nearestWithin([], { x: 0, y: 0 }, 20)).toBeNull();
  });
});
