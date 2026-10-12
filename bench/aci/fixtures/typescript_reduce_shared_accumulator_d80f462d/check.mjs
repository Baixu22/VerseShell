// @ts-check
// check.mjs — behavioural checks for stats.mjs (do not edit)
import { summarize } from './stats.mjs';

let failures = 0;

/** Structural equality for flat objects; throws on mismatch. */
function deepEqual(actual, expected, msg = '') {
  const ka = Object.keys(actual);
  const kb = Object.keys(expected);
  if (
    ka.length !== kb.length ||
    ka.some((k) => actual[k] !== expected[k])
  ) {
    throw new Error(
      `${msg}expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

function check(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (err) {
    failures += 1;
    console.error(`FAIL - ${name}: ${err.message}`);
  }
}

const cart = [
  { sku: 'pen', price: 2, qty: 3 },
  { sku: 'book', price: 5, qty: 1 },
];

check('empty cart summarizes to zeros', () => {
  deepEqual(summarize([]), { count: 0, total: 0 });
});

check('empty cart is unaffected by earlier calls', () => {
  summarize(cart);
  deepEqual(summarize([]), { count: 0, total: 0 });
});

check('line items are counted and priced', () => {
  deepEqual(summarize(cart), { count: 2, total: 11 });
});

check('empty cart stays zeros after repeated data calls', () => {
  summarize(cart);
  summarize(cart);
  deepEqual(summarize([]), { count: 0, total: 0 });
});

check('earlier summaries are not mutated by later calls', () => {
  const first = summarize(cart);
  summarize([]);
  summarize(cart);
  deepEqual(first, { count: 2, total: 11 });
});

check('interleaved empty and data calls stay independent', () => {
  deepEqual(summarize([]), { count: 0, total: 0 });
  deepEqual(summarize([{ sku: 'x', price: 1, qty: 4 }]), { count: 1, total: 4 });
  deepEqual(summarize([]), { count: 0, total: 0 });
});

if (failures > 0) {
  console.error(`${failures} check(s) failed`);
  process.exit(1);
}
console.log('all checks passed');
