import loader, { readClip as rc, Base } from "./lib.js";
export function caller(b: Base): number { b.run(); return rc() + loader(); }
