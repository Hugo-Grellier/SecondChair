// The few Foundry VTT v14 globals the SecondChair modules use, typed for `tsc --checkJs`.
// ponytail: hand-written subset; switch to community Foundry types once they cover v14.

interface FoundrySettingConfig {
  name?: string;
  hint?: string;
  scope: "world" | "client" | "user";
  config: boolean;
  type: StringConstructor | NumberConstructor | BooleanConstructor;
  default: unknown;
  requiresReload?: boolean;
}

declare const game: {
  settings: {
    register(module: string, key: string, config: FoundrySettingConfig): void;
    get(module: string, key: string): unknown;
    set(module: string, key: string, value: unknown): Promise<unknown>;
  };
  user: { id: string; isGM: boolean };
  users: { activeGM: { id: string } | null };
  world: { id: string };
};

declare const Hooks: {
  once(hook: string, fn: () => unknown): number;
};

declare const ui: {
  notifications: Record<
    "info" | "warn" | "error",
    (message: string, options?: { permanent?: boolean }) => unknown
  >;
};
