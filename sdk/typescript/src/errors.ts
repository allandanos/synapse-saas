/** Typed errors mirroring the API's problem+json semantics. */

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  [key: string]: unknown;
}

function named<T extends new (...args: never[]) => Error>(cls: T, name: string): T {
  Object.defineProperty(cls.prototype, "name", { value: name });
  return cls;
}

export class SynapseError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: Problem,
  ) {
    super(String(body.detail ?? body.title ?? `API error ${status}`));
  }
}

export const SynapseAuthError = named(
  class extends SynapseError {},
  "SynapseAuthError",
);
export const SynapseNotFoundError = named(
  class extends SynapseError {},
  "SynapseNotFoundError",
);

export const SynapseFeatureGatedError = named(
  class extends SynapseError {
    get feature(): string | undefined {
      return this.body.feature as string | undefined;
    }
    get availableIn(): string[] {
      return (this.body.available_in as string[] | undefined) ?? [];
    }
  },
  "SynapseFeatureGatedError",
);

export const SynapseLimitError = named(
  class extends SynapseError {
    get metric(): string | undefined {
      return this.body.metric as string | undefined;
    }
    get limit(): number | undefined {
      return this.body.limit as number | undefined;
    }
  },
  "SynapseLimitError",
);

export function errorFor(status: number, body: Problem): SynapseError {
  if (status === 401) return new SynapseAuthError(status, body);
  if (status === 404) return new SynapseNotFoundError(status, body);
  if (status === 402) return new SynapseLimitError(status, body);
  if (status === 403 && "feature" in body) return new SynapseFeatureGatedError(status, body);
  return new SynapseError(status, body);
}
