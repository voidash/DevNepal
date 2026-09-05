/**
 * Live screens — drawn boards with behaviour. Each module below registers
 * enhancers as a side effect of import, so this list is the complete set of
 * screens that work rather than merely render.
 *
 *   public.ts    A2.1 catalog · A2.2/A2.3 project detail with the apply gate
 *   member.ts    B2.3 apply · B5.5 dashboard · B2.4 accepted · B2.6 evidence ·
 *                B2.8 recognised · B6.5 timeline
 *   ministry.ts  C3.1 overview and inbox · C3.2 decide · C4.2 verify
 *
 * The registry must load before the modules, which is why it lives in its own
 * file: importing it from here first avoids the temporal-dead-zone trap of a
 * module registering into a map its importer has not finished defining.
 */
export { live, registerLive } from "./registry"
export type { Enhancer, LiveCtx } from "./registry"

import "./public"
import "./member"
import "./ministry"
