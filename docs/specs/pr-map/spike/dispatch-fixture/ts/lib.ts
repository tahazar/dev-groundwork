export interface Task { run(): void; size: number; }
export class Runner { run(a: string, b: number): number { return b; } }
export class Shaped { size = 1; run(): void {} }
export class Foo { constructor(public n: number) {} static make(): Foo { return new this(1); } }
export class Baz extends Foo { constructor() { super(2); } }
export function use(t: Task): void { t.run(); new Baz(); }
export class Plain extends Foo {}
export function build(): Plain { return new Plain(3); }
