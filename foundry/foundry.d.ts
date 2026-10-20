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
    get(
      id: string,
    ): { name: string; isGM: boolean; getFlag(scope: string, key: string): unknown } | undefined;
  };
  world: { id: string };
  socket: {
    emit(event: string, data: unknown): void;
    // Foundry passes the id of the user whose client emitted the message.
    on(event: string, fn: (data: unknown, senderId: string) => unknown): void;
  };
  modules: { get(id: string): object | undefined };
  scenes: {
    get(id: string): { uuid: string } | undefined;
    active: { uuid: string } | null;
    find(fn: (scene: FoundryDoc) => boolean): FoundryDoc;
  };
  actors: {
    get(id: string): { uuid: string } | undefined;
    find(fn: (actor: FoundryDoc) => boolean): FoundryDoc;
    fromCompendium(doc: FoundryDoc): FoundryDoc;
  };
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

declare const canvas: { ready: boolean; mousePosition: { x: number; y: number } } | undefined;

declare const foundry: {
  applications: {
    api: {
      DialogV2: {
        confirm(options: { window: { title: string }; content: string }): Promise<boolean>;
      };
    };
  };
};

declare const ui: {
  players?: { render(): unknown };
  notifications: Record<
    "info" | "warn" | "error",
    (message: string, options?: { permanent?: boolean }) => unknown
  >;
};

// Scene realisation (scenes.js): documents are loosely typed on purpose.
// biome-ignore lint/suspicious/noExplicitAny: Foundry documents, not modelled here
type FoundryDoc = any;
declare const Scene: { create(data: object): Promise<FoundryDoc> };
declare const Actor: { create(data: object): Promise<FoundryDoc> };
