/**
 * envConfig.mjs
 *
 * Loads, validates, and assembles the application's environment configuration.
 * Every required field must be a non-empty string, otherwise a descriptive
 * Error is thrown listing all offending fields.
 */

/**
 * The shape of the validated configuration object.
 *
 * @typedef {Object} EnvConfig
 * @property {string} DATABASE_URL Connection string for the primary database.
 * @property {string} JWT_SECRET   Secret used to sign authentication tokens.
 * @property {string} PORT         Port the HTTP server listens on.
 * @property {string} API_KEY      Key for the external API.
 * @property {string} NODE_ENV     Runtime environment (e.g. "development").
 * @property {string} LOG_LEVEL    Logging verbosity (e.g. "info").
 */

/**
 * Declaration of a single environment variable.
 *
 * @typedef {Object} FieldSpec
 * @property {keyof EnvConfig} key      Environment variable name.
 * @property {boolean}         required Whether it must be a non-empty string.
 * @property {string}          [fallback] Value used when an optional field is absent.
 */

/** @type {ReadonlyArray<FieldSpec>} */
const SCHEMA = Object.freeze([
  { key: 'DATABASE_URL', required: true },
  { key: 'JWT_SECRET', required: true },
  { key: 'PORT', required: true },
  { key: 'API_KEY', required: true },
  { key: 'NODE_ENV', required: false, fallback: 'development' },
  { key: 'LOG_LEVEL', required: false, fallback: 'info' },
]);

/**
 * Builds a human-readable description of a raw value for error messages.
 *
 * @param {unknown} value
 * @returns {string}
 */
function describeValue(value) {
  if (value === undefined) return 'undefined';
  if (value === null) return 'null';
  if (typeof value === 'string') return JSON.stringify(value);
  return `${typeof value} (${String(value)})`;
}

/**
 * Validates the environment and returns the assembled config object.
 *
 * Every required field must be present and a non-empty string; if any fail,
 * a single descriptive Error is thrown naming each problem. Optional fields
 * fall back to their declared defaults when absent or invalid. The returned
 * object is frozen so the configuration cannot be mutated after load.
 *
 * @param {Record<string, string | undefined>} [source]
 *     Env-like map to read from; defaults to `process.env`. Useful for tests.
 * @returns {Readonly<EnvConfig>} The frozen, fully validated configuration.
 * @throws {Error} If any required field is missing, not a string, or empty.
 */
export function loadConfig(source = process.env) {
  /** @type {Record<string, string>} */
  const config = {};

  /** @type {string[]} */
  const problems = [];

  for (const { key, required, fallback } of SCHEMA) {
    const raw = source?.[key];
    const isNonEmptyString =
      typeof raw === 'string' && /** @type {string} */ (raw).trim().length > 0;

    if (isNonEmptyString) {
      config[key] = /** @type {string} */ (raw);
    } else if (required) {
      problems.push(
        `"${key}" must be a non-empty string, but got ${describeValue(raw)}.`
      );
    } else {
      config[key] = /** @type {string} */ (fallback ?? '');
    }
  }

  if (problems.length > 0) {
    throw new Error(
      `Invalid environment configuration (${problems.length} problem${
        problems.length === 1 ? '' : 's'
      }):\n  - ${problems.join('\n  - ')}`
    );
  }

  return Object.freeze(config);
}
