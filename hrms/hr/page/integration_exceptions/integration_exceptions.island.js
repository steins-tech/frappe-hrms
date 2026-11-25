// Desk imports this entry and calls mount for the Frappe UI page.
import { mountVueIsland } from "@framework/ui/island";

import Page from "./integration_exceptions.vue";

export const mount = (el, context) => mountVueIsland(el, { ...context, component: Page });
