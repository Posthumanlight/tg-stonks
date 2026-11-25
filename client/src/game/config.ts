import Phaser from "phaser";

import { BootScene } from "../scenes/BootScene";
import { COMBAT_SCENE, CombatScene } from "../scenes/combat/CombatScene";
import { DEPLOY_SCENE, DeployScene } from "../scenes/combat/DeployScene";
import { GALAXY_SCENE, GalaxyScene } from "../scenes/galaxy/GalaxyScene";
import { CHART_COLOURS } from "../scenes/galaxy/palette";

const SCENES = {
  boot: BootScene,
  [GALAXY_SCENE]: GalaxyScene,
  [DEPLOY_SCENE]: DeployScene,
  [COMBAT_SCENE]: CombatScene,
};

export function startGame(parent: HTMLElement): Phaser.Game {
  const game = new Phaser.Game({
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
  });
  // Registered without autostart (a config `scene` array would start the first one):
  // game/host.ts starts the entry scene of whichever screen is shown.
  for (const [key, scene] of Object.entries(SCENES)) game.scene.add(key, scene, false);
  return game;
}
