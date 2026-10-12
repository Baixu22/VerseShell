// @ts-check
// stats.mjs — cart summary helpers

/**
 * A single cart line item.
 * @typedef {{ sku: string, price: number, qty: number }} LineItem
 */

/**
 * Summarize a list of cart line items into a count of line items and the
 * total price. Each call returns a fresh, independent summary object.
 * @param {LineItem[]} items
 * @returns {{ count: number, total: number }}
 */
export function summarize(items) {
  return items.reduce(
    (acc, item) => {
      acc.count += 1;
      acc.total += item.price * item.qty;
      return acc;
    },
    { count: 0, total: 0 },
  );
}
