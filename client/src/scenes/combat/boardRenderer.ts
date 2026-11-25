// Drawing shared by the combat and deploy scenes, so both show the board the same way:
// terrain + grid, unit tokens, and the model-count labels on them.
import Phaser from "phaser";

import { COMBAT_COLOURS, sideColour, terrainColour } from "./palette";

/** World units per board square. */
export const TILE = 32;

export interface TerrainBoard {
  readonly width: number;
  readonly height: number;
  readonly terrain: readonly string[];
}

export interface Token {
  readonly origin: readonly [number, number];
  readonly size: number; // footprint, squares per side
  readonly side: number;
}

/** Terrain colours and the grid. Terrain never changes during a fight or a deployment. */
export function drawTerrain(g: Phaser.GameObjects.Graphics, board: TerrainBoard): void {
  board.terrain.forEach((id, index) => {
    const x = (index % board.width) * TILE;
    const y = Math.floor(index / board.width) * TILE;
    g.fillStyle(terrainColour(id), 1).fillRect(x, y, TILE, TILE);
  });
  g.lineStyle(1, COMBAT_COLOURS.gridLine, 0.25);
  for (let x = 0; x <= board.width; x++) g.lineBetween(x * TILE, 0, x * TILE, board.height * TILE);
  for (let y = 0; y <= board.height; y++) g.lineBetween(0, y * TILE, board.width * TILE, y * TILE);
}

/** A unit token in its side colour, with an optional ring (active, selected, target…). */
export function drawToken(
  g: Phaser.GameObjects.Graphics,
  token: Token,
  ring: number | null,
  alpha = 0.9,
): void {
  const [px, py] = [token.origin[0] * TILE, token.origin[1] * TILE];
  const span = token.size * TILE;
  g.fillStyle(sideColour(token.side), alpha).fillRoundedRect(px + 3, py + 3, span - 6, span - 6, 6);
  if (ring !== null) g.lineStyle(3, ring, 1).strokeRoundedRect(px + 1.5, py + 1.5, span - 3, span - 3, 7);
}

/** A filled footprint (highlights, zones, the drag ghost). */
export function fillSquares(
  g: Phaser.GameObjects.Graphics,
  origin: readonly [number, number],
  size: number,
  colour: number,
  alpha: number,
  inset = 0,
): void {
  const span = size * TILE;
  g.fillStyle(colour, alpha).fillRect(origin[0] * TILE + inset, origin[1] * TILE + inset, span - 2 * inset, span - 2 * inset);
}

export interface LabelSpec {
  readonly key: string;
  readonly text: string;
  readonly token: Token;
}

/** One centred text per token, keyed so labels are reused and stale ones removed. */
export class TokenLabels {
  private readonly labels = new Map<string, Phaser.GameObjects.Text>();

  constructor(private readonly scene: Phaser.Scene) {}

  sync(specs: readonly LabelSpec[]): void {
    const keep = new Set(specs.map((s) => s.key));
    for (const [key, label] of this.labels) {
      if (!keep.has(key)) {
        label.destroy();
        this.labels.delete(key);
      }
    }
    for (const { key, text, token } of specs) {
      let label = this.labels.get(key);
      if (!label) {
        label = this.scene.add
          .text(0, 0, "", {
            fontFamily: "system-ui, sans-serif",
            fontSize: "13px",
            fontStyle: "bold",
            color: COMBAT_COLOURS.unitText,
            resolution: (window.devicePixelRatio || 1) * 2,
          })
          .setOrigin(0.5);
        this.labels.set(key, label);
      }
      const centre = (token.size * TILE) / 2;
      label.setText(text).setPosition(token.origin[0] * TILE + centre, token.origin[1] * TILE + centre);
    }
  }

  clear(): void {
    this.labels.clear(); // the scene destroys its game objects on shutdown
  }
}
