export interface Base { run(): void; }
export class Foo { constructor(public n: number) {} }
export class S { run(): void {} }
export const fake: Base = { run() {} };
export function ov(x: number): number;
export function ov(x: string): string;
export function ov(x: number | string): number | string { return x; }
