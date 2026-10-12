import { chunk } from './chunk.mjs';
import assert from 'node:assert/strict';

function test_chunk_splits_into_consecutive_batches() {
  assert.deepStrictEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
}

function test_chunk_exact_multiple_of_size() {
  assert.deepStrictEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]]);
}

function test_chunk_empty_array_returns_no_batches() {
  assert.deepStrictEqual(chunk([], 3), []);
}

function test_chunk_size_larger_than_array_length() {
  assert.deepStrictEqual(chunk([1, 2], 5), [[1, 2]]);
}

function test_chunk_size_of_one_makes_singletons() {
  assert.deepStrictEqual(chunk(['a', 'b', 'c'], 1), [['a'], ['b'], ['c']]);
}

function test_chunk_rejects_non_positive_or_non_integer_size() {
  assert.throws(() => chunk([1], 0), RangeError);
  assert.throws(() => chunk([1], -2), RangeError);
  assert.throws(() => chunk([1], 1.5), RangeError);
  assert.throws(() => chunk([1], NaN), RangeError);
}

test_chunk_splits_into_consecutive_batches();
test_chunk_exact_multiple_of_size();
test_chunk_empty_array_returns_no_batches();
test_chunk_size_larger_than_array_length();
test_chunk_size_of_one_makes_singletons();
test_chunk_rejects_non_positive_or_non_integer_size();
