/** TypeScript client SDK for the Synapse SaaS Framework API.
 *
 * Two credential modes:
 * - API key (`sk_…`): programmatic org access — org is pinned server-side
 * - Access token: user session from the console login flow
 *
 * Zero runtime dependencies: uses the platform fetch (Node 18+/browsers).
 */

export * from "./errors.js";
export { SynapseClient } from "./client.js";
