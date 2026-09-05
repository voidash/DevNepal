import type { DevNepalAPI } from "./api"
import { MockAdapter } from "./mock-adapter"

/* One instance, one import path. Swapping to Django is changing this line —
   or, method by method while the backend lands, wrapping MockAdapter with a
   DjangoAdapter that overrides only what exists. */
export const api: DevNepalAPI = new MockAdapter()

export type * from "./api"
