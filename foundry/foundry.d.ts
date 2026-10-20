// The few Foundry VTT v14 globals the SecondChair modules use, typed for `tsc --checkJs`.
// ponytail: hand-written subset; switch to community Foundry types once they cover v14.

interface FoundrySettingConfig {
  name?: string;
  hint?: string;
  scope: "world" | "client" | "user";
  config: boolean;
  type: StringConstructor | NumberConstructor | BooleanConstructor;
  default: unknown;
  choices?: Record<string, string>;
  requiresReload?: boolean;
  onChange?: (value: unknown, options: object, userId?: string) => unknown;
}

declare const game: {
  settings: {
    register(module: string, key: string, config: FoundrySettingConfig): void;
    get(module: string, key: string): unknown;
    set(module: string, key: string, value: unknown): Promise<unknown>;
  };
  user: {
    id: string;
    isGM: boolean;
    getFlag(scope: string, key: string): unknown;
    setFlag(scope: string, key: string, value: unknown): Promise<unknown>;
  };
  users: {
    activeGM: { id: string } | null;
    get(id: string): { name: string; isGM: boolean } | undefined;
  };
  world: { id: string };
  modules: { get(id: string): object | undefined };
  scenes: { get(id: string): { uuid: string } | undefined; active: { uuid: string } | null };
  actors: { get(id: string): { uuid: string } | undefined };
};

declare function fromUuid(uuid: string): Promise<object | null>;

declare const Hooks: {
  once(hook: string, fn: () => unknown): number;
  // biome-ignore lint/suspicious/noExplicitAny: each hook passes its own arguments
  on(hook: string, fn: (...args: any[]) => unknown): number;
};

interface ChatMessageLike {
  whisper: string[];
  blind: boolean;
  author: { name: string } | null;
  speaker: { scene?: string | null; actor?: string | null; alias?: string | null } | null;
  content: string | null;
  flavor: string | null;
  rolls: { formula: string; total: number }[] | null;
}

interface CombatLike {
  id: string;
  round: number;
  turn: number | null;
  scene: { id: string } | null;
  combatant: CombatantLike | null;
  turns: CombatantLike[];
}

interface CombatantLike {
  name: string;
  hidden: boolean;
  actor: { uuid: string } | null;
}

declare const ui: {
  notifications: Record<
    "info" | "warn" | "error",
    (message: string, options?: { permanent?: boolean }) => unknown
  >;
};
