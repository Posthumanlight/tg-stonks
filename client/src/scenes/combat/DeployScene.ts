import { effect } from "@preact/signals";
import Phaser from "phaser";

import { type DragSource, carried } from "../../builder/drag";
import { type Draft, type Issue, type UnitRef, sameRef, unitCard } from "../../builder/draft";
import { type Square, zoneFor } from "../../builder/placement";
import { boardPointer, overTray } from "../../builder/pointer";
import { squareAt } from "../../combat/interaction";
import type { BuilderView } from "../../protocol";
import { builder } from "../../state/builder";
import type { Ghost } from "../../state/builderStore";
import { CameraController } from "../shared/camera";
import type { Vec } from "../shared/viewport";
import { type LabelSpec, TILE, TokenLabels, drawTerrain, drawToken, fillSquares } from "./boardRenderer";
import { COMBAT_COLOURS, sideColour } from "./palette";

export const DEPLOY_SCENE = "deploy";

/** Screen space the DOM overlay uses: keep in sync with .builder-top / .builder-dock. */
const UI_INSET_TOP = 96;
const UI_INSET_BOTTOM = 230;

/**
 * Deployment for a custom battle (docs/client.md "Custom battle screen"): the map, the
 * zones, both armies' tokens and the drag ghost, all drawn from the builder store.
 * Gestures on tokens become drags; everything else pans and zooms.
 */
export class DeployScene extends Phaser.Scene {
  private terrain!: Phaser.GameObjects.Graphics;
  private zones!: Phaser.GameObjects.Graphics;
  private units!: Phaser.GameObjects.Graphics;
  private ghost!: Phaser.GameObjects.Graphics;
  private labels!: TokenLabels;
  private camera!: CameraController;
  private drawnBoard: BuilderView["board"] | null = null;
  /** A pressed token: where in its footprint it was grabbed, so it doesn't jump. */
  private grabbed: { side: number; index: number; offset: Square } | null = null;

  constructor() {
    super(DEPLOY_SCENE);
  }

  create(): void {
    this.cameras.main.setBackgroundColor(COMBAT_COLOURS.background);
    this.terrain = this.add.graphics();
    this.zones = this.add.graphics();
    this.units = this.add.graphics();
    this.ghost = this.add.graphics();
    this.labels = new TokenLabels(this);
    this.camera = new CameraController(this, {
      insetTop: UI_INSET_TOP,
      insetBottom: UI_INSET_BOTTOM,
      onTap: (_screen, world) => {
        const square = this.square(world);
        if (square) builder.tapSquare(square);
      },
      grab: (_screen, world) => this.grab(world),
      onGrabMove: (_screen, world) => this.carry(world),
      onGrabEnd: (screen, world) => this.drop(screen, world),
      onGrabCancel: () => {
        this.grabbed = null;
        builder.endDrag({ kind: "none" });
      },
    });
    boardPointer.install((x, y) => this.squareAtClient(x, y));

    const dispose = effect(() => {
      const view = builder.view.value;
      if (view?.board !== this.drawnBoard) this.drawBoard(view);
      this.drawState(
        view,
        builder.draft.value,
        builder.activeSide.value,
        builder.issues.value,
        builder.ghost.value,
        builder.selected.value,
        carried(builder.drag.value),
      );
    });
    const onResize = () => this.fitBoard(false);
    this.scale.on(Phaser.Scale.Events.RESIZE, onResize);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      dispose();
      boardPointer.install(null);
      this.camera.destroy();
      this.scale.off(Phaser.Scale.Events.RESIZE, onResize);
      this.labels.clear();
      this.drawnBoard = null;
      this.grabbed = null;
    });
  }

  // --- input -----------------------------------------------------------------------------

  private square(world: Vec): Square | null {
    const board = builder.view.peek()?.board;
    return board ? squareAt(board, TILE, world.x, world.y) : null;
  }

  private squareAtClient(clientX: number, clientY: number): Square | null {
    const rect = this.game.canvas.getBoundingClientRect();
    const screen = { x: clientX - rect.left, y: clientY - rect.top };
    if (screen.x < 0 || screen.y < 0 || screen.x > rect.width || screen.y > rect.height) return null;
    return this.square(this.camera.screenToWorld(screen));
  }

  /** Take the gesture when it starts on one of the active side's tokens. */
  private grab(world: Vec): boolean {
    const square = this.square(world);
    const ref = square && builder.draggableAt(square);
    const unit = ref && builder.draft.peek()?.sides[ref.side]?.units[ref.index];
    if (!square || !ref || !unit) return false;
    this.grabbed = { ...ref, offset: [square[0] - unit.origin[0], square[1] - unit.origin[1]] };
    return true;
  }

  /** The footprint's origin when the grabbed square is over `world`. */
  private originUnder(world: Vec): Square | null {
    const square = this.square(world);
    const grabbed = this.grabbed;
    return square && grabbed ? [square[0] - grabbed.offset[0], square[1] - grabbed.offset[1]] : square;
  }

  private carry(world: Vec): void {
    const grabbed = this.grabbed;
    if (!grabbed) return;
    if (builder.drag.peek().phase !== "dragging") {
      builder.beginDrag({ kind: "token", ref: { side: grabbed.side, index: grabbed.index } });
    }
    builder.hoverSquare(this.originUnder(world));
  }

  private drop(screen: Vec, world: Vec): void {
    if (!this.grabbed) return;
    const rect = this.game.canvas.getBoundingClientRect();
    const origin = this.originUnder(world);
    this.grabbed = null;
    if (overTray(rect.left + screen.x, rect.top + screen.y)) builder.endDrag({ kind: "tray" });
    else builder.endDrag(origin ? { kind: "square", square: origin } : { kind: "none" });
  }

  // --- drawing ---------------------------------------------------------------------------

  private fitBoard(reset: boolean): void {
    const board = this.drawnBoard;
    if (!board) return;
    this.camera.setBounds({ x: 0, y: 0, width: board.width * TILE, height: board.height * TILE }, reset);
  }

  private drawBoard(view: BuilderView | null): void {
    this.drawnBoard = view?.board ?? null;
    const g = this.terrain.clear();
    if (!view) return;
    drawTerrain(g, view.board);
    this.fitBoard(true);
  }

  private drawState(
    view: BuilderView | null,
    draft: Draft | null,
    activeSide: number,
    issues: readonly Issue[],
    ghost: Ghost | null,
    selected: UnitRef | null,
    moving: DragSource | null,
  ): void {
    const z = this.zones.clear();
    const g = this.units.clear();
    const gh = this.ghost.clear();
    if (!view || !draft) {
      this.labels.sync([]);
      return;
    }

    for (const [x, y, w, h] of zoneFor(view.zones, activeSide) ?? []) {
      z.fillStyle(sideColour(activeSide), 0.14).fillRect(x * TILE, y * TILE, w * TILE, h * TILE);
    }

    const flagged = issues.filter((i) => i.unit !== null);
    const labels: LabelSpec[] = [];
    draft.sides.forEach((setup, side) =>
      setup.units.forEach((unit, index) => {
        const ref = { side, index };
        const token = { origin: unit.origin, size: unitCard(view, unit.unit_type)?.footprint ?? 1, side };
        const isMoving = moving?.kind === "token" && sameRef(moving.ref, ref);
        const ring = flagged.some((i) => i.side === side && i.unit === index)
          ? COMBAT_COLOURS.target
          : sameRef(selected, ref)
            ? COMBAT_COLOURS.inspected
            : null;
        drawToken(g, token, ring, isMoving ? 0.3 : side === activeSide ? 0.9 : 0.45);
        labels.push({ key: `${side}:${index}`, text: String(unit.models), token });
      }),
    );
    this.labels.sync(labels);

    if (ghost) {
      const colour = ghost.issue ? COMBAT_COLOURS.target : COMBAT_COLOURS.move;
      fillSquares(gh, ghost.origin, ghost.size, colour, 0.5, 2);
    }
  }
}
