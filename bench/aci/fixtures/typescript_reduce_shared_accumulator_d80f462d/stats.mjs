// @ts-check
// stats.mjs — cart summary helpers

/**
 * A single cart line item.
 * @typedef {{ sku: string, price: number, qty: number }} LineItem
 */

/** Shared zero-value accumulator reused across calls. */
const ZERO = { count: 0, total: 0 };

/**
 * Summarize a list of cart line items into a count of line items and the
 * total price.
 * @param {LineItem[]} items
 * @returns {{ count: number, total: number }}
 */
export function summarize(items) {
  return items.reduce((acc, item) => {
    acc.count += 1;
    acc.total += item.price * item.qty;
    return acc;
  }, ZERO);
}
