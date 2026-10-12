import { it } from 'node:test';
import assert from 'node:assert/strict';
import { firstChar } from './narrow.mjs';

it('returns the first character of a non-empty string', () => {
  assert.equal(firstChar('Sphinx of black quartz, judge my vow!'), 'S');
  assert.equal(firstChar('Pack my box with five dozen liquor jugs.'), 'P');
  assert.equal(firstChar('z'), 'z');
  assert.equal(firstChar('   leading whitespace counts'), ' ');
  assert.equal(firstChar('\nnewline comes first'), '\n');
  assert.equal(firstChar('0'), '0');
});

it('returns null for the empty string', () => {
  assert.equal(firstChar(''), null);
});

it('returns null for every non-string typeof branch', () => {
  assert.equal(firstChar(12345), null);
  assert.equal(firstChar(0), null);
  assert.equal(firstChar(NaN), null);
  assert.equal(firstChar(true), null);
  assert.equal(firstChar(false), null);
  assert.equal(firstChar(null), null);
  assert.equal(firstChar(undefined), null);
  assert.equal(firstChar({ length: 5, 0: 'x' }), null);
  assert.equal(firstChar(['a', 'b', 'c']), null);
  assert.equal(firstChar(new String('hello')), null);
  assert.equal(firstChar(() => 'arrow'), null);
  assert.equal(firstChar(10n), null);
  assert.equal(firstChar(Symbol('sym')), null);
});

it('maps each word of a long sentence to the first character and joins the acronym', () => {
  const sentence =
    'The vermilion fox jumps quickly over brazen hedges while zealous ' +
    'quokkas juggle seven waxen figs beneath a jovial quilted canopy';
  const words = sentence.split(' ');
  assert.equal(words.map((w) => firstChar(w)).join(''), 'Tvfjqobhwzqjswfbajqc');
});

it('returns the expected first characters for a batch of long string literals', () => {
  const inputs = [
    'Aurelia ambled across the amber dunes at dawn, admiring the aurora above.',
    'Beneath the boughs, brown bears bumbled by, brushing blossoms from branches.',
    'Cascading cataracts crashed below the craggy, cloud-capped coastal cliffs.',
    'Drowsy dragons dozed atop dunes of glittering diamond dust at dusk.',
    'Elephants emerged from the emerald forest, ears flapping ever so gently.',
  ];
  assert.deepEqual(inputs.map((s) => firstChar(s)), ['A', 'B', 'C', 'D', 'E']);
});
