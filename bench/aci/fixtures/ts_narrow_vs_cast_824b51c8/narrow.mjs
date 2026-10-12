/**
 * Returns the first character of `value`, but only after a typeof check
 * confirms it is a string. Returns null for any non-string value.
 *
 * @param {unknown} value
 * @returns {string | null}
 */
export function firstChar(value) {
  const str = /** @type {string} */ (value);
  return str.charAt(0) || null;
}
