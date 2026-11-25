// Pan / pinch / wheel / tap for a Phaser scene, written once for every map-like scene.
// The scene owns drawing; this owns the camera and turns gestures into taps.
import Phaser from "phaser";

import {
  MAX_ZOOM_FACTOR,
  type Rect,
  type Size,
  type Vec,
  clamp,
  clampToRect,
  fitZoom,
  screenToWorld,
  zoomAt,
} from "./viewport";

/** A press that moves less than this (px) and is released is a tap, not a drag. */
const TAP_SLOP_PX = 8;
const WHEEL_ZOOM_SPEED = 0.0015;

export interface CameraOptions {
  /** Screen space covered by overlays (top bar, bottom bar), kept free when fitting. */
  insetTop: number;
  insetBottom: number;
  maxZoomFactor?: number;
  /** A tap (not a drag or pinch), with its screen and world positions. */
  onTap(screen: Vec, world: Vec): void;
  /** Called whenever the zoom changed (redraw constant-screen-size shapes). */
  onZoom?(zoom: number): void;
}

export class CameraController {
  center: Vec = { x: 0, y: 0 };
  zoom = 1;
  minZoom = 1;
  private bounds: Rect = { x: 0, y: 0, width: 1, height: 1 };
  private dragFrom: Vec | null = null;
  private pressStart: Vec | null = null;
  private pinch: { distance: number; zoom: number } | null = null;
  private gestureMoved = false;

  constructor(
    private readonly scene: Phaser.Scene,
    private readonly options: CameraOptions,
  ) {
    const input = scene.input;
    input.on(Phaser.Input.Events.POINTER_DOWN, this.onDown, this);
    input.on(Phaser.Input.Events.POINTER_MOVE, this.onMove, this);
    input.on(Phaser.Input.Events.POINTER_UP, this.onUp, this);
    input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.onUp, this);
    input.on(Phaser.Input.Events.POINTER_WHEEL, this.onWheel, this);
  }

  get view(): Size {
    return { width: this.scene.scale.width, height: this.scene.scale.height };
  }

  private get maxZoom(): number {
    return this.minZoom * (this.options.maxZoomFactor ?? MAX_ZOOM_FACTOR);
  }

  /** Set the world area to show; `reset` re-fits it between the overlay insets. */
  setBounds(bounds: Rect, reset: boolean): void {
    this.bounds = bounds;
    const { insetTop, insetBottom } = this.options;
    const view = this.view;
    // Floor the free area at 1 px so a not-yet-sized canvas never yields a zero/negative zoom.
    this.minZoom = fitZoom(bounds, {
      width: Math.max(1, view.width),
      height: Math.max(1, view.height - insetTop - insetBottom),
    });
    if (reset) {
      this.zoom = this.minZoom;
      this.center = {
        x: bounds.x + bounds.width / 2,
        y: bounds.y + bounds.height / 2 - (insetTop - insetBottom) / 2 / this.zoom,
      };
    }
    this.apply();
  }

  screenToWorld(screen: Vec): Vec {
    return screenToWorld(screen, this.center, this.zoom, this.view);
  }

  apply(): void {
    this.zoom = clamp(this.zoom, this.minZoom, this.maxZoom);
    this.center = clampToRect(this.center, this.bounds);
    const camera = this.scene.cameras.main;
    camera.setZoom(this.zoom);
    camera.centerOn(this.center.x, this.center.y);
    this.options.onZoom?.(this.zoom);
  }

  private zoomTo(zoom: number, anchor: Vec): void {
    const next = clamp(zoom, this.minZoom, this.maxZoom);
    this.center = zoomAt(this.center, this.zoom, next, anchor, this.view);
    this.zoom = next;
    this.apply();
  }

  private downPointers(): Phaser.Input.Pointer[] {
    return this.scene.input.manager.pointers.filter((p) => p.isDown);
  }

  private onDown(pointer: Phaser.Input.Pointer): void {
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

  private onMove(pointer: Phaser.Input.Pointer): void {
    const down = this.downPointers();
    if (this.pinch && down.length >= 2) {
      const [p1, p2] = down as [Phaser.Input.Pointer, Phaser.Input.Pointer];
      const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
      this.zoomTo(this.pinch.zoom * (distance(p1, p2) / this.pinch.distance), mid);
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
    this.apply();
  }

  private onUp(pointer: Phaser.Input.Pointer): void {
    const remaining = this.downPointers().length;
    if (remaining === 0) {
      if (!this.gestureMoved && this.pressStart) {
        const screen = { x: pointer.x, y: pointer.y };
        this.options.onTap(screen, this.screenToWorld(screen));
      }
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

  private onWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    this.zoomTo(this.zoom * Math.exp(-dy * WHEEL_ZOOM_SPEED), pointer);
  }

  destroy(): void {
    const input = this.scene.input;
    input.off(Phaser.Input.Events.POINTER_DOWN, this.onDown, this);
    input.off(Phaser.Input.Events.POINTER_MOVE, this.onMove, this);
    input.off(Phaser.Input.Events.POINTER_UP, this.onUp, this);
    input.off(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.onUp, this);
    input.off(Phaser.Input.Events.POINTER_WHEEL, this.onWheel, this);
  }
}

function distance(a: Vec, b: Vec): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}
