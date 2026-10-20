// The contracts' schemas, compiled once for the module's tests (ARC-17a).
import { readFileSync } from "node:fs";
import { Ajv2020 } from "ajv/dist/2020.js";

/** @param {string} name */
const contract = (name) =>
  JSON.parse(readFileSync(new URL(`../../docs/contracts/${name}`, import.meta.url), "utf8"));

const ajv = new Ajv2020({
  formats: { "date-time": (/** @type {string} */ s) => !Number.isNaN(Date.parse(s)) },
});
const envelope = contract("event-envelope.schema.json");
ajv.addSchema(envelope);

/** A Foundry bridge message (foundry-bridge.schema.json), which refers to the envelope. */
export const validMessage = ajv.compile(contract("foundry-bridge.schema.json"));
/** A `pf2e.outcome` observation's payload (pf2e-outcome.schema.json). */
export const validOutcome = ajv.compile(contract("pf2e-outcome.schema.json"));
/** An event envelope (event-envelope.schema.json). */
export const validEnvelope = /** @type {import("ajv").ValidateFunction} */ (
  ajv.getSchema(envelope.$id)
);
