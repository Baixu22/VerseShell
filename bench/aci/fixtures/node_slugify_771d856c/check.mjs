import { slugify } from './slugify.mjs';
import assert from 'node:assert/strict';

function test_basicLowercasingAndSeparators() {
  assert.equal(
    slugify('  The Quick--Brown FOX!!  jumps  over 42 Lazy Dogs...  '),
    'the-quick-brown-fox-jumps-over-42-lazy-dogs'
  );
}

function test_collapsesEachRunIntoOneHyphen() {
  assert.equal(
    slugify('alpha    beta---gamma___delta   epsilon'),
    'alpha-beta-gamma-delta-epsilon'
  );
}

function test_stripsEdgePunctuation() {
  assert.equal(
    slugify('!!!Hello, World??? 2024 Release Notes (final)!!!'),
    'hello-world-2024-release-notes-final'
  );
}

function test_allNonAlphanumericYieldsEmptySlug() {
  assert.equal(slugify('   *** ### ---   '), '');
  assert.equal(slugify(''), '');
}

function test_coercesNonStringInput() {
  assert.equal(slugify(2024), '2024');
  assert.equal(slugify('  '), '');
}

test_basicLowercasingAndSeparators();
test_collapsesEachRunIntoOneHyphen();
test_stripsEdgePunctuation();
test_allNonAlphanumericYieldsEmptySlug();
test_coercesNonStringInput();
console.log('all slugify tests passed');
