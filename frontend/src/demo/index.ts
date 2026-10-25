/**
 * Demo seed barrel — delete this folder when deploying against a real database.
 * Gate: only imported while VITE_USE_MOCKS is enabled.
 */
export * from "./seed";
export * from "./enrichment";

export const DEMO_DATA_ENABLED =
  import.meta.env.VITE_USE_MOCKS === "1" ||
  import.meta.env.VITE_USE_MOCKS === undefined ||
  import.meta.env.VITE_USE_MOCKS === "";
