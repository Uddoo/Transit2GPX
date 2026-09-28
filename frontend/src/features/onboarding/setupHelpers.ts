import { RequestError } from "../../api/client";

export const SETUP_GUIDE = "https://github.com/Uddoo/transit2fog/blob/main/docs/GETTING_STARTED.md";
export const RAIL_GUIDE = "https://github.com/Uddoo/transit2fog/blob/main/rail-routing/README.md";

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof RequestError ? error.message : fallback;
}

