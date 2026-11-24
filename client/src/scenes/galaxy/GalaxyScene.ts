import { effect } from "@preact/signals";
import Phaser from "phaser";

import type { GalaxyView } from "../../protocol";
import { selectedStarIndex } from "../../state/galaxy";
import {
  MAX_ZOOM_FACTOR,
  TAP_RADIUS_PX,
  type Size,
  type Vec,
  chartExtent,
  clamp,
  clampCenter,
  fitZoom,
  isPortrait,
  nearestWithin,
  screenToChart,
  toChart,
  zoomAt,
} from "./layout";
import { CHART_COLOURS, starColour, starRadiusPx } from "./palette";

export const GALAXY_SCENE = "galaxy";

/** Star names appear once the player has zoomed in this far past fit-to-screen. */
const STAR_LABEL_ZOOM_FACTOR = 2.5;
/** A press that moves less than this (px) and is released is a tap, not a drag. */
const TAP_SLOP_PX = 8;
const WHEEL_ZOOM_SPEED = 0.0015;
/** Screen space the overlay uses (top bar, hint line), kept free at fit-to-screen. */
const UI_INSET_TOP = 72;
const UI_INSET_BOTTOM = 36;

interface SceneData {
  galaxy: GalaxyView;
}

/** The galaxy star chart: clusters, hyperlanes, stars. Pan, zoom, tap to select. */
export class GalaxyScene extends Phaser.Scene {
  private galaxy!: GalaxyView;
  private graphics!: Phaser.GameObjects.Graphics;
  private clusterLabels: Phaser.GameObjects.Text[] = [];
  private starLabels: Phaser.GameObjects.Text[] = [];

  private portrait = true;
  private extent: Size = { width: 1, height: 1 };
  private starPoints: Vec[] = [];
  private clusterPoints: Vec[] = [];

  private center: Vec = { x: 0, y: 0 };
  private zoom = 1;
  private minZoom = 1;
  private drawnZoom = 0;

  private dragFrom: Vec | null = null;
  private pressStart: Vec | null = null;
  private pinch: { distance: number; zoom: number } | null = null;
  private gestureMoved = false;

  constructor() {
    super(GALAXY_SCENE);
  }

  init(data: SceneData): void {
    this.galaxy = data.galaxy;
  }

  create(): void {
    this.graphics = this.add.graphics();
    const resolution = window.devicePixelRatio || 1;
    this.clusterLabels = this.galaxy.clusters.map((cluster) =>
      this.add
        .text(0, 0, cluster.name.toUpperCase(), {
          fontFamily: "system-ui, sans-serif",
          fontSize: "11px",
          color: CHART_COLOURS.label,
          resolution,
        })
        .setOrigin(0.5, 0)
        .setAlpha(0.85),
    );
    this.starLabels = this.galaxy.stars.map((star) =>
      this.add
        .text(0, 0, star.name, {
          fontFamily: "system-ui, sans-serif",
          fontSize: "10px",
          color: CHART_COLOURS.starLabel,
          resolution,
        })
        .setOrigin(0.5, 0),
    );

    this.layoutChart(true);
    this.bindInput();
    this.scale.on(Phaser.Scale.Events.RESIZE, this.onResize, this);

    const dispose = effect(() => {
      void selectedStarIndex.value; // subscribe
      this.redraw();
    });
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      dispose();
      this.scale.off(Phaser.Scale.Events.RESIZE, this.onResize, this);
    });
  }

  // --- layout -----------------------------------------------------------------------

  private get view(): Size {
    return { width: this.scale.width, height: this.scale.height };
  }

  /** (Re)compute chart coordinates for the current orientation. */
  private layoutChart(resetCamera: boolean): void {
    const { semi_axis_a: a, semi_axis_b: b } = this.galaxy;
    this.portrait = isPortrait(this.view);
    this.extent = chartExtent(a, b, this.portrait);
    this.starPoints = this.galaxy.stars.map((s) => toChart(s, this.portrait));
    this.clusterPoints = this.galaxy.clusters.map((c) => toChart(c, this.portrait));
    const view = this.view;
    const free = { width: view.width, height: view.height - UI_INSET_TOP - UI_INSET_BOTTOM };
    this.minZoom = fitZoom(this.extent, free);

    if (resetCamera) {
      this.zoom = this.minZoom;
      // Centre the chart in the area between the top bar and the hint line.
      this.center = { x: 0, y: -(UI_INSET_TOP - UI_INSET_BOTTOM) / 2 / this.zoom };
    }
    this.applyCamera();
  }

  private onResize(): void {
    const orientationChanged = isPortrait(this.view) !== this.portrait;
    this.layoutChart(orientationChanged);
  }

  private applyCamera(): void {
    this.zoom = clamp(this.zoom, this.minZoom, this.minZoom * MAX_ZOOM_FACTOR);
    this.center = clampCenter(this.center, this.extent);
    const camera = this.cameras.main;
    camera.setZoom(this.zoom);
    camera.centerOn(this.center.x, this.center.y);
    if (this.zoom !== this.drawnZoom) this.redraw();
  }

  // --- drawing ----------------------------------------------------------------------

  /** Redraw everything with sizes in screen pixels (divided by zoom). Cheap: ~250 shapes. */
  private redraw(): void {
    if (!this.graphics) return;
    const px = 1 / this.zoom;
    const g = this.graphics.clear();

    for (const [i, cluster] of this.galaxy.clusters.entries()) {
      const p = this.clusterPoints[i];
      if (!p) continue;
      g.fillStyle(CHART_COLOURS.clusterFill, 0.07).fillCircle(p.x, p.y, cluster.radius);
      g.lineStyle(px, CHART_COLOURS.clusterStroke, 0.25);
      g.strokeCircle(p.x, p.y, cluster.radius);
    }

    for (const link of this.galaxy.links) {
      const a = this.starPoints[link.a];
      const b = this.starPoints[link.b];
      if (!a || !b) continue;
      if (link.kind === "bridge") {
        g.lineStyle(2 * px, CHART_COLOURS.bridge, 0.8);
      } else {
        g.lineStyle(1.25 * px, CHART_COLOURS.lane, 0.9);
      }
      g.lineBetween(a.x, a.y, b.x, b.y);
    }

    const showStarLabels = this.zoom >= this.minZoom * STAR_LABEL_ZOOM_FACTOR;
    for (const [i, star] of this.galaxy.stars.entries()) {
      const p = this.starPoints[i];
      if (!p) continue;
      const radius = starRadiusPx(star.star_class) * px;
      g.fillStyle(starColour(star.colour), 1).fillCircle(p.x, p.y, radius);
      this.starLabels[i]
        ?.setPosition(p.x, p.y + radius + 3 * px)
        .setScale(px)
        .setVisible(showStarLabels);
    }

    const selected = selectedStarIndex.value;
    const sp = selected === null ? undefined : this.starPoints[selected];
    if (sp) {
      g.lineStyle(2 * px, CHART_COLOURS.selection, 1).strokeCircle(sp.x, sp.y, 12 * px);
    }

    // Cluster names sit just below each cluster's halo, at constant screen size.
    for (const [i, cluster] of this.galaxy.clusters.entries()) {
      const p = this.clusterPoints[i];
      if (p) this.clusterLabels[i]?.setPosition(p.x, p.y + cluster.radius + 8 * px).setScale(px);
    }
    this.drawnZoom = this.zoom;
  }

  // --- input ------------------------------------------------------------------------

  private bindInput(): void {
    const input = this.input;
    input.on(Phaser.Input.Events.POINTER_DOWN, this.onPointerDown, this);
    input.on(Phaser.Input.Events.POINTER_MOVE, this.onPointerMove, this);
    input.on(Phaser.Input.Events.POINTER_UP, this.onPointerUp, this);
    input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.onPointerUp, this);
    input.on(Phaser.Input.Events.POINTER_WHEEL, this.onWheel, this);
  }

  private downPointers(): Phaser.Input.Pointer[] {
    return this.input.manager.pointers.filter((p) => p.isDown);
  }

  private onPointerDown(pointer: Phaser.Input.Pointer): void {
    const down = this.downPointers();
    if (down.length >= 2) {
      const [p1, p2] = down as [Phaser.Input.Pointer, Phaser.Input.Pointer];
      this.pinch = { distance: distance(p1, p2), zoom: this.zoom };
      this.dragFrom = null;
      this.gestureMoved = true; // a pinch is never a tap
      return;
    }
    this.dragFrom = { x: pointer.x, y: pointer.y };
    this.pressStart = { x: pointer.x, y: pointer.y };
    this.gestureMoved = false;
  }

  private onPointerMove(pointer: Phaser.Input.Pointer): void {
    const down = this.downPointers();
    if (this.pinch && down.length >= 2) {
      const [p1, p2] = down as [Phaser.Input.Pointer, Phaser.Input.Pointer];
      const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
      const next = this.pinch.zoom * (distance(p1, p2) / this.pinch.distance);
      this.zoomTo(next, mid);
      return;
    }
    if (!this.dragFrom || !pointer.isDown) return;
    const dx = pointer.x - this.dragFrom.x;
    const dy = pointer.y - this.dragFrom.y;
    this.dragFrom = { x: pointer.x, y: pointer.y };
    if (this.pressStart && distance(pointer, this.pressStart) > TAP_SLOP_PX) {
      this.gestureMoved = true;
    }
    this.center = { x: this.center.x - dx / this.zoom, y: this.center.y - dy / this.zoom };
    this.applyCamera();
  }

  private onPointerUp(pointer: Phaser.Input.Pointer): void {
    const remaining = this.downPointers().length;
    if (remaining === 0) {
      if (!this.gestureMoved && this.pressStart) this.tap(pointer);
      this.pinch = null;
      this.dragFrom = null;
      this.pressStart = null;
    } else if (remaining === 1) {
      // Pinch ended with one finger still down: continue as a drag from it.
      this.pinch = null;
      const [still] = this.downPointers();
      this.dragFrom = still ? { x: still.x, y: still.y } : null;
    }
  }

  private onWheel(
    pointer: Phaser.Input.Pointer,
    _over: unknown,
    _dx: number,
    dy: number,
  ): void {
    this.zoomTo(this.zoom * Math.exp(-dy * WHEEL_ZOOM_SPEED), pointer);
  }

  private zoomTo(zoom: number, anchor: Vec): void {
    const next = clamp(zoom, this.minZoom, this.minZoom * MAX_ZOOM_FACTOR);
    this.center = zoomAt(this.center, this.zoom, next, anchor, this.view);
    this.zoom = next;
    this.applyCamera();
  }

  private tap(screen: Vec): void {
    const point = screenToChart(screen, this.center, this.zoom, this.view);
    const hit = nearestWithin(this.starPoints, point, TAP_RADIUS_PX / this.zoom);
    selectedStarIndex.value = hit;
  }
}

function distance(a: Vec, b: Vec): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}
