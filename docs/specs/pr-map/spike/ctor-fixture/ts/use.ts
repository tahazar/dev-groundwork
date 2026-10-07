import { Command } from "commander";
import { Base, Foo, S, fake, ov } from "./lib.js";
export function caller(b: Base, s: S): void { new Foo(1); fake.run(); b.run(); s.run(); ov(1); new Command().action(() => {}); }
