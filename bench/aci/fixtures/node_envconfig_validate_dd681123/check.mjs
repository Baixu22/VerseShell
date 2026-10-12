import { loadConfig } from './envConfig.mjs';
import assert from 'node:assert/strict';

const FULL = {
  DATABASE_URL: 'postgres://user:pass@db.internal:5432/app_prod?sslmode=require&connect_timeout=10',
  JWT_SECRET: 's3cr3t-signing-key-with-plenty-of-entropy-0123456789abcdef',
  PORT: '8443',
  API_KEY: 'sk-live-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6',
  NODE_ENV: 'production',
  LOG_LEVEL: 'debug',
};

function test_loadsValidConfigAndFreezesIt() {
  const cfg = loadConfig(FULL);
  assert.deepStrictEqual({ ...cfg }, FULL);
  assert.ok(Object.isFrozen(cfg));
}

function test_appliesFallbacksForOptionalFields() {
  const cfg = loadConfig({ DATABASE_URL: 'postgres://localhost/app', JWT_SECRET: 'jwt-secret-value', PORT: '3000', API_KEY: 'key-9876543210' });
  assert.deepStrictEqual({ ...cfg }, {
    DATABASE_URL: 'postgres://localhost/app', JWT_SECRET: 'jwt-secret-value',
    PORT: '3000', API_KEY: 'key-9876543210', NODE_ENV: 'development', LOG_LEVEL: 'info',
  });
}

function test_reportsEveryProblemInOneError() {
  assert.throws(
    () => loadConfig({ JWT_SECRET: '', PORT: '3000', API_KEY: 'k' }),
    (err) => err.message === 'Invalid environment configuration (2 problems):\n  - "DATABASE_URL" must be a non-empty string, but got undefined.\n  - "JWT_SECRET" must be a non-empty string, but got "".'
  );
}

function test_singularWordingForSingleProblem() {
  assert.throws(
    () => loadConfig({ DATABASE_URL: 'db://x', JWT_SECRET: 's', PORT: 8080, API_KEY: 'k' }),
    (err) => err.message === 'Invalid environment configuration (1 problem):\n  - "PORT" must be a non-empty string, but got number (8080).'
  );
  assert.equal(loadConfig({ ...FULL, LOG_LEVEL: '   ' }).LOG_LEVEL, 'info');
}
test_loadsValidConfigAndFreezesIt();
test_appliesFallbacksForOptionalFields();
test_reportsEveryProblemInOneError();
test_singularWordingForSingleProblem();
