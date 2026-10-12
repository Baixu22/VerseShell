/**
 * Splits an array into consecutive batches of at most `size` elements.
 * The last batch may be smaller, but is never empty.
 *
 * @template T
 * @param {readonly T[]} array - The array to split.
 * @param {number} size - The maximum size of each batch (positive integer).
 * @returns {T[][]} An array of batches, in order.
 * @throws {RangeError} If `size` is not a positive integer.
 */
export function chunk(array, size) {
  if (!Number.isInteger(size) || size < 1) {
    throw new RangeError("size must be a positive integer");
  }

  const batches = [];
  for (let i = 0; i <= array.length; i += size) {
    batches.push(array.slice(i, i + size));
  }
  return batches;
}
