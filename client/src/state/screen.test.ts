import { describe, expect, it } from "vitest";

import { screenAfterAuth } from "./screen";

describe("screenAfterAuth", () => {
  it("sends signed-out players to login from anywhere", () => {
    for (const current of ["boot", "login", "lobby", "galaxy", "combat"] as const) {
      expect(screenAfterAuth(current, false)).toBe("login");
    }
  });

  it("sends freshly signed-in players to the lobby, and keeps others where they are", () => {
    expect(screenAfterAuth("boot", true)).toBe("lobby");
    expect(screenAfterAuth("login", true)).toBe("lobby");
    expect(screenAfterAuth("galaxy", true)).toBe("galaxy");
    expect(screenAfterAuth("combat", true)).toBe("combat");
  });
});
