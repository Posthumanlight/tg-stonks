import { describe, expect, it } from "vitest";

import en from "@locales/en.json";
import ua from "@locales/ua.json";

import { resolveLocale, translate } from "./index";

describe("locale files", () => {
  it("en and ua define exactly the same keys", () => {
    expect(Object.keys(ua).sort()).toEqual(Object.keys(en).sort());
  });

  it("have no empty values", () => {
    for (const dict of [en, ua]) {
      for (const [key, value] of Object.entries(dict)) {
        expect(value.trim(), key).not.toBe("");
      }
    }
  });
});

describe("resolveLocale", () => {
  it("maps Ukrainian tags to ua", () => {
    expect(resolveLocale(["uk"])).toBe("ua");
    expect(resolveLocale(["uk-UA"])).toBe("ua");
  });

  it("takes the first supported tag", () => {
    expect(resolveLocale([undefined, "de-DE", "en-GB", "uk"])).toBe("en");
  });

  it("falls back to en", () => {
    expect(resolveLocale(["fr", undefined])).toBe("en");
    expect(resolveLocale([])).toBe("en");
  });
});

describe("translate", () => {
  const dicts = { en: { a: "A", hi: "Hi {name}" }, ua: { a: "А" } };

  it("uses the current locale, then en, then the key", () => {
    expect(translate(dicts, "ua", "a")).toBe("А");
    expect(translate(dicts, "ua", "hi", { name: "x" })).toBe("Hi x");
    expect(translate(dicts, "ua", "missing.key")).toBe("missing.key");
  });

  it("leaves unknown placeholders intact", () => {
    expect(translate(dicts, "en", "hi")).toBe("Hi {name}");
    expect(translate(dicts, "en", "hi", { other: 1 })).toBe("Hi {name}");
  });
});
