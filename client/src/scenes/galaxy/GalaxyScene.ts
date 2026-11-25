import { effect } from "@preact/signals";
import Phaser from "phaser";

import type { GalaxyView } from "../../protocol";
import { selectedStarIndex } from "../../state/galaxy";
import { CameraController } from "../shared/camera";
import { centredRect } from "../shared/viewport";
import {
  TAP_RADIUS_PX,
  type Size,
  type Vec,
  chartExtent,
  isPortrait,
  nearestWithin,
  toChart,
} from "./layout";
import { CHART_COLOURS, starColour, starRadiusPx } from "./palette";

export const GALAXY_SCENE = "galaxy";

/** Star names appear once the player has zoomed in this far past fit-to-screen. */
const STAR_LABEL_ZOOM_FACTOR = 2.5;
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
  private camera!: CameraController;

  private portrait = true;
  private extent: Size = { width: 1, height: 1 };
  private starPoints: Vec[] = [];
  private clusterPoints: Vec[] = [];
  private drawnZoom = 0;

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

    this.camera = new CameraController(this, {
      insetTop: UI_INSET_TOP,
      insetBottom: UI_INSET_BOTTOM,
      onTap: (_screen, world) => {
        selectedStarIndex.value = nearestWithin(
          this.starPoints,
          world,
          TAP_RADIUS_PX / this.camera.zoom,
        );
      },
      onZoom: (zoom) => {
        if (zoom !== this.drawnZoom) this.redraw();
      },
    });
    this.layoutChart(true);
    this.scale.on(Phaser.Scale.Events.RESIZE, this.onResize, this);

    const dispose = effect(() => {
      void selectedStarIndex.value; // subscribe
      this.redraw();
    });
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      dispose();
      this.camera.destroy();
      this.scale.off(Phaser.Scale.Events.RESIZE, this.onResize, this);
    });
  }

  // --- layout -----------------------------------------------------------------------

  /** (Re)compute chart coordinates for the current orientation. */
  private layoutChart(resetCamera: boolean): void {
    const { semi_axis_a: a, semi_axis_b: b } = this.galaxy;
    this.portrait = isPortrait(this.camera.view);
    this.extent = chartExtent(a, b, this.portrait);
    this.starPoints = this.galaxy.stars.map((s) => toChart(s, this.portrait));
    this.clusterPoints = this.galaxy.clusters.map((c) => toChart(c, this.portrait));
    this.camera.setBounds(centredRect(this.extent), resetCamera);
  }

  private onResize(): void {
    this.layoutChart(isPortrait(this.camera.view) !== this.portrait);
  }

  // --- drawing ----------------------------------------------------------------------

  /** Redraw everything with sizes in screen pixels (divided by zoom). Cheap: ~250 shapes. */
  private redraw(): void {
    if (!this.graphics || !this.camera) return;
    const zoom = this.camera.zoom;
    const px = 1 / zoom;
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

    const showStarLabels = zoom >= this.camera.minZoom * STAR_LABEL_ZOOM_FACTOR;
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
    this.drawnZoom = zoom;
  }
}
