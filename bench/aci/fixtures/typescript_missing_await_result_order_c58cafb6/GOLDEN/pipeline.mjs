// @ts-check
/**
 * A tiny report pipeline: each step produces a payload after an
 * async delay, and the caller assembles a report from the payloads.
 *
 * @typedef {Object} Step
 * @property {string} id
 * @property {number} ms
 * @property {string} payload
 */

/**
 * Runs every step and resolves with one payload per step, in the
 * same order as the input array.
 *
 * @param {Step[]} steps
 * @returns {Promise<string[]>}
 */
export async function runSteps(steps) {
  const results = await Promise.all(steps.map((step) => stepWork(step)));
  return results;
}

/**
 * Simulated async work: resolves with the step's payload after `ms`.
 *
 * @param {Step} step
 * @returns {Promise<string>}
 */
function stepWork(step) {
  return new Promise((resolve) => {
    setTimeout(() => resolve(`${step.id}:${step.payload}`), step.ms);
  });
}
