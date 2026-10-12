/**
 * Converts a title into a URL slug by lowercasing, trimming,
 * and collapsing every run of non-alphanumeric characters
 * into a single hyphen.
 *
 * @param {string} title - The input title to convert.
 * @returns {string} The resulting URL slug.
 */
export function slugify(title) {
  return String(title)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
