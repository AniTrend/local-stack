import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import type { PulumiInventory } from "../shared/contracts";
import pulumiInventorySchema from "../shared/pulumi-inventory.schema.json";

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validateSchema = ajv.compile<PulumiInventory>(pulumiInventorySchema);

export function validatePulumiInventory(value: unknown): PulumiInventory {
  if (!validateSchema(value)) {
    const details = validateSchema.errors
      ?.map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`)
      .join("; ");
    throw new Error(`HCloud Pulumi inventory failed schema validation${details ? `: ${details}` : ""}`);
  }
  return value;
}
