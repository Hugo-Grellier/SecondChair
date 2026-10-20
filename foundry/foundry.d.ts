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

interface FoundryModule {
  id: string;
  active: boolean;
  version: string;
}

interface FoundryPack {
  collection: string;
  getIndex(options: { fields: string[] }): Promise<
    Iterable<{
      _id: string;
      name: string;
      system?: { slug?: string | null };
      flags?: { babele?: { originalName?: string } };
    }>
  >;
}

declare const game: {
  settings: {
    register(module: string, key: string, config: FoundrySettingConfig): void;
    get(module: string, key: string): unknown;
    set(module: string, key: string, value: unknown): Promise<unknown>;
    settings: Map<string, unknown>;
  };
  user: {
    id: string;
    isGM: boolean;
    /** pf2e's per-user settings: whether checks and damage rolls open their dialog. */
    settings: { showCheckDialogs: boolean; showDamageDialogs: boolean };
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
  keybindings: {
    register(
      module: string,
      key: string,
      config: {
        name: string;
        editable: { key: string; modifiers?: string[] }[];
        restricted?: boolean;
        onDown: () => boolean;
      },
    ): void;
  };
  /** A Foundry Collection: iterating it yields the values. */
  modules: Iterable<FoundryModule> & {
    get(id: string): (FoundryModule & { api?: object }) | undefined;
  };
  packs: Iterable<FoundryPack>;
  version: string;
  release: { generation: number };
  system: { id: string; version: string };
  time: { worldTime: number; advance(seconds: number): Promise<unknown> };
  /** The pf2e system: its world clock is Luxon's DateTime, Gregorian. */
  pf2e: {
    worldClock: { worldTime: { year: number; month: number; day: number } };
    system: { sluggify(text: string): string };
    /** The system actions (Demoralize, Trip, …), by slug. */
    actions: { get(slug: string): FoundryDoc };
    ConditionManager: {
      updateConditionValue(id: string, actor: FoundryDoc, value: number): Promise<void>;
    };
  };
  scenes: {
    get(id: string): { uuid: string } | undefined;
    active: { uuid: string } | null;
    find(fn: (scene: FoundryDoc) => boolean): FoundryDoc;
  };
  combat: FoundryDoc | null;
  actors: {
    contents: FoundryDoc[];
    get(id: string): { uuid: string } | undefined;
    find(fn: (actor: FoundryDoc) => boolean): FoundryDoc;
    fromCompendium(doc: FoundryDoc): FoundryDoc;
  };
};

declare function fromUuid(uuid: string): Promise<object | null>;
declare function fromUuidSync(uuid: string, options?: { strict?: boolean }): FoundryDoc;

declare const Hooks: {
  // biome-ignore lint/suspicious/noExplicitAny: each hook passes its own arguments
  once(hook: string, fn: (...args: any[]) => unknown): number;
  // biome-ignore lint/suspicious/noExplicitAny: each hook passes its own arguments
  on(hook: string, fn: (...args: any[]) => unknown): number;
  callAll(hook: string, ...args: unknown[]): boolean;
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
  isOwner: boolean;
  hasPlayerOwner: boolean;
}

declare const canvas: { ready: boolean; mousePosition: { x: number; y: number } } | undefined;

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
declare const ChatMessage: {
  create(data: object): Promise<FoundryDoc>;
  getSpeaker(options: { token?: FoundryDoc }): object;
};
declare const Actor: { create(data: object): Promise<FoundryDoc> };

declare namespace foundry.applications.api {
  class ApplicationV2 {
    constructor(options?: object);
    rendered: boolean;
    render(options?: { force?: boolean }): Promise<this>;
  }
  const DialogV2: {
    confirm(options: { window: { title: string }; content: string }): Promise<boolean>;
  };
}
