import Phaser from "phaser";

import { BootScene } from "../scenes/BootScene";
import { GalaxyScene } from "../scenes/galaxy/GalaxyScene";
import { CHART_COLOURS } from "../scenes/galaxy/palette";

export function startGame(parent: HTMLElement): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    backgroundColor: CHART_COLOURS.background,
    pixelArt: true,
    roundPixels: true,
    banner: false,
    scale: {
      mode: Phaser.Scale.RESIZE, // canvas follows the #game element (full viewport)
      width: "100%",
      height: "100%",
    },
    input: {
      activePointers: 2, // two touches for pinch-zoom
    },
    scene: [BootScene, GalaxyScene],
  });
}
