import { effect } from "@preact/signals";
import Phaser from "phaser";

import { combat } from "../../state/combat";
import type { BoardView, CombatView, UnitView } from "../../protocol";
import { type Highlights, isAlive, squareAt } from "../../combat/interaction";
import { CameraController } from "../shared/camera";
import { COMBAT_COLOURS, sideColour, terrainColour } from "./palette";

export const COMBAT_SCENE = "combat";

/** World units per board square. */
export const TILE = 32;
/** Screen space the DOM overlay uses: top bar, bottom action panel. */
const UI_INSET_TOP = 56;
const UI_INSET_BOTTOM = 210;

/**
 * The ground-combat board: terrain, overlays, units, highlights. Everything is drawn from
 * the combat store's signals; taps go back to the store, which turns them into intents.
 */
export class CombatScene extends Phaser.Scene {
  private terrain!: Phaser.GameObjects.Graphics;
  private marks!: Phaser.GameObjects.Graphics;
  private units!: Phaser.GameObjects.Graphics;
  private labels = new Map<number, Phaser.GameObjects.Text>();
  private camera!: CameraController;
  private drawnBoard: BoardView | null = null;

  constructor() {
    super(COMBAT_SCENE);
  }

  create(): void {
    this.cameras.main.setBackgroundColor(COMBAT_COLOURS.background);
    this.terrain = this.add.graphics();
    this.marks = this.add.graphics();
    this.units = this.add.graphics();
    this.camera = new CameraController(this, {
      insetTop: UI_INSET_TOP,
      insetBottom: UI_INSET_BOTTOM,
      onTap: (_screen, world) => {
        const board = combat.board.peek();
        const square = board && squareAt(board, TILE, world.x, world.y);
        if (square) combat.tap(square);
      },
    });

    const dispose = effect(() => {
      const board = combat.board.value;
      const view = combat.view.value;
      const marks = combat.marks.value;
      const inspected = combat.shownUnit.value?.uid ?? null;
      if (board !== this.drawnBoard) this.drawBoard(board);
      this.drawState(view, marks, inspected);
    });
    const onResize = () => this.fitBoard(false);
    this.scale.on(Phaser.Scale.Events.RESIZE, onResize);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      dispose();
      this.camera.destroy();
      this.scale.off(Phaser.Scale.Events.RESIZE, onResize);
      this.labels.clear();
      this.drawnBoard = null;
    });
  }

  private fitBoard(reset: boolean): void {
    const board = this.drawnBoard;
    if (!board) return;
    this.camera.setBounds(
      { x: 0, y: 0, width: board.width * TILE, height: board.height * TILE },
      reset,
    );
  }

  /** Terrain never changes during a fight: drawn once per snapshot board. */
  private drawBoard(board: BoardView | null): void {
    this.drawnBoard = board;
    const g = this.terrain.clear();
    if (!board) return;
    board.terrain.forEach((id, index) => {
      const x = (index % board.width) * TILE;
      const y = Math.floor(index / board.width) * TILE;
      g.fillStyle(terrainColour(id), 1).fillRect(x, y, TILE, TILE);
    });
    g.lineStyle(1, COMBAT_COLOURS.gridLine, 0.25);
    for (let x = 0; x <= board.width; x++) g.lineBetween(x * TILE, 0, x * TILE, board.height * TILE);
    for (let y = 0; y <= board.height; y++) g.lineBetween(0, y * TILE, board.width * TILE, y * TILE);
    this.fitBoard(true);
  }

  private drawState(view: CombatView | null, marks: Highlights, inspected: number | null): void {
    const m = this.marks.clear();
    const g = this.units.clear();
    if (!view) {
      this.syncLabels([]);
      return;
    }

    for (const overlay of view.overlays) {
      const [x, y] = overlay.square;
      m.fillStyle(COMBAT_COLOURS.overlay, 0.45).fillRect(x * TILE, y * TILE, TILE, TILE);
    }
    for (const move of marks.moves) {
      const colour = move.provokes.length ? COMBAT_COLOURS.moveProvokes : COMBAT_COLOURS.move;
      const [x, y] = move.to;
      m.fillStyle(colour, 0.28).fillRect(x * TILE + 2, y * TILE + 2, TILE - 4, TILE - 4);
    }
    for (const [x, y] of marks.targetSquares) {
      m.fillStyle(COMBAT_COLOURS.abilitySquare, 0.3).fillRect(x * TILE, y * TILE, TILE, TILE);
    }

    const living = view.units.filter(isAlive);
    const targets = new Set(marks.targetUnits);
    for (const unit of living) {
      const [px, py] = [unit.origin[0] * TILE, unit.origin[1] * TILE];
      const span = unit.size * TILE;
      g.fillStyle(sideColour(unit.side), 0.9).fillRoundedRect(px + 3, py + 3, span - 6, span - 6, 6);
      if (unit.wounded) g.fillStyle(COMBAT_COLOURS.wounded, 1).fillCircle(px + span - 7, py + 7, 3);
      const ring = targets.has(unit.uid)
        ? COMBAT_COLOURS.target
        : unit.uid === view.active?.uid
          ? COMBAT_COLOURS.active
          : unit.uid === inspected
            ? COMBAT_COLOURS.inspected
            : null;
      if (ring !== null) {
        g.lineStyle(3, ring, 1).strokeRoundedRect(px + 1.5, py + 1.5, span - 3, span - 3, 7);
      }
    }
    this.syncLabels(living);
  }

  /** One model-count label per living unit; labels of dead units are removed. */
  private syncLabels(living: readonly UnitView[]): void {
    const keep = new Set(living.map((u) => u.uid));
    for (const [uid, label] of this.labels) {
      if (!keep.has(uid)) {
        label.destroy();
        this.labels.delete(uid);
      }
    }
    for (const unit of living) {
      let label = this.labels.get(unit.uid);
      if (!label) {
        label = this.add
          .text(0, 0, "", {
            fontFamily: "system-ui, sans-serif",
            fontSize: "13px",
            fontStyle: "bold",
            color: COMBAT_COLOURS.unitText,
            resolution: (window.devicePixelRatio || 1) * 2,
          })
          .setOrigin(0.5);
        this.labels.set(unit.uid, label);
      }
      const centre = (unit.size * TILE) / 2;
      label
        .setText(String(unit.models))
        .setPosition(unit.origin[0] * TILE + centre, unit.origin[1] * TILE + centre);
    }
  }
}
