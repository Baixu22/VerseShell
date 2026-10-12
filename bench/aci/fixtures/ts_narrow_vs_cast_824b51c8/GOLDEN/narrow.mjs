/**
 * Returns the first character of `value`, but only after a typeof check
 * confirms it is a string. Returns null for any non-string value.
 *
 * @param {unknown} value
 * @returns {string | null}
 */
export function firstChar(value) {
  if (typeof value === "string") {
    return value.length > 0 ? value[0] : null;
  }
  return null;
}
