// Flat-key i18n: t("galaxy.loading"), t("galaxy.summary", { stars: 100 }).
// Keys live in /locales/{en,ua}.json; every key must exist in both (see locales.test.ts).
import { signal } from "@preact/signals";

import en from "@locales/en.json";
import ua from "@locales/ua.json";

export type Dictionary = Readonly<Record<string, string>>;
export type MessageKey = keyof typeof en;
export type Params = Readonly<Record<string, string | number>>;

export const LOCALES = { en, ua } as const satisfies Record<string, Dictionary>;
export type Locale = keyof typeof LOCALES;
export const DEFAULT_LOCALE: Locale = "en";

/** Current UI language. Reading it inside a component re-renders on change. */
export const locale = signal<Locale>(DEFAULT_LOCALE);

/** Map language tags (e.g. Telegram's "uk", navigator's "en-GB") to a supported locale. */
export function resolveLocale(tags: readonly (string | undefined)[]): Locale {
  for (const tag of tags) {
    const primary = tag?.toLowerCase().split(/[-_]/)[0];
    if (primary === "uk" || primary === "ua") return "ua";
    if (primary === "en") return "en";
  }
  return DEFAULT_LOCALE;
}

/** Pure lookup: current locale -> English -> the key itself. Fills `{name}` params. */
export function translate(
  dictionaries: Readonly<Record<string, Dictionary>>,
  current: string,
  key: string,
  params?: Params,
): string {
  const template =
    dictionaries[current]?.[key] ?? dictionaries[DEFAULT_LOCALE]?.[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

export function initI18n(languageCode: string | undefined): void {
  locale.value = resolveLocale([languageCode, ...navigator.languages]);
  document.documentElement.lang = locale.value === "ua" ? "uk" : locale.value;
}

/** Translate a statically known key (checked at compile time). */
export function t(key: MessageKey, params?: Params): string {
  return translate(LOCALES, locale.value, key, params);
}

/** Translate a key built at runtime, e.g. a content `name_key` from the server. */
export function tKey(key: string, params?: Params): string {
  return translate(LOCALES, locale.value, key, params);
}

/** An error `reason_key` from the server, or a generic message for unknown keys. */
export function tError(reasonKey: string): string {
  const known = reasonKey in LOCALES[DEFAULT_LOCALE];
  return tKey(known ? reasonKey : "error.generic");
}
