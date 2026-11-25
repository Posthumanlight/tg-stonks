import { effect } from "@preact/signals";
import Phaser from "phaser";

import { combat } from "../../state/combat";
import type { BoardView, CombatView } from "../../protocol";
import { type Highlights, isAlive, squareAt } from "../../combat/interaction";
import { CameraController } from "../shared/camera";
import { TILE, TokenLabels, drawTerrain, drawToken, fillSquares } from "./boardRenderer";
import { COMBAT_COLOURS } from "./palette";

export const COMBAT_SCENE = "combat";

export { TILE } from "./boardRenderer";
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
  private labels!: TokenLabels;
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
    this.labels = new TokenLabels(this);
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
    drawTerrain(g, board);
    this.fitBoard(true);
  }

  private drawState(view: CombatView | null, marks: Highlights, inspected: number | null): void {
    const m = this.marks.clear();
    const g = this.units.clear();
    if (!view) {
      this.labels.sync([]);
      return;
    }

    for (const overlay of view.overlays) {
      fillSquares(m, overlay.square, 1, COMBAT_COLOURS.overlay, 0.45);
    }
    for (const move of marks.moves) {
      const colour = move.provokes.length ? COMBAT_COLOURS.moveProvokes : COMBAT_COLOURS.move;
      fillSquares(m, move.to, 1, colour, 0.28, 2);
    }
    for (const square of marks.targetSquares) {
      fillSquares(m, square, 1, COMBAT_COLOURS.abilitySquare, 0.3);
    }

    const living = view.units.filter(isAlive);
    const targets = new Set(marks.targetUnits);
    for (const unit of living) {
      const ring = targets.has(unit.uid)
        ? COMBAT_COLOURS.target
        : unit.uid === view.active?.uid
          ? COMBAT_COLOURS.active
          : unit.uid === inspected
            ? COMBAT_COLOURS.inspected
            : null;
      drawToken(g, unit, ring);
      if (unit.wounded) {
        const span = unit.size * TILE;
        g.fillStyle(COMBAT_COLOURS.wounded, 1).fillCircle(unit.origin[0] * TILE + span - 7, unit.origin[1] * TILE + 7, 3);
      }
    }
    this.labels.sync(living.map((unit) => ({ key: String(unit.uid), text: String(unit.models), token: unit })));
  }
}
