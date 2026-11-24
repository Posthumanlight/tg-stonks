import { effect } from "@preact/signals";
import Phaser from "phaser";

import { galaxyState } from "../state/galaxy";
import { GALAXY_SCENE } from "./galaxy/GalaxyScene";

/** Waits for the galaxy data (loading/error UI is the Preact overlay), then hands off. */
export class BootScene extends Phaser.Scene {
  constructor() {
    super("boot");
  }

  create(): void {
    const dispose = effect(() => {
      const state = galaxyState.value;
      if (state.status === "ready") {
        // Defer: starting a scene from inside the effect would dispose it re-entrantly.
        queueMicrotask(() => {
          dispose();
          this.scene.start(GALAXY_SCENE, { galaxy: state.galaxy });
        });
      }
    });
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, dispose);
  }
}
