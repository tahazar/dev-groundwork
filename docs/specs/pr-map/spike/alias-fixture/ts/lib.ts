export function readClip(): number { return 1; }
export default function loadSet(): number { return 2; }
export interface Base { run(): void; }
export class Mid implements Base { run(): void {} }
export class Impl extends Mid { run(): void {} }
