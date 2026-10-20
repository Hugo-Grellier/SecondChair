// The PF2e adapter's acts for the behaviour traces (TRC-02, TRC-03): which act a pf2e check or
// chat card starts, traced as `pf2e.strike`, `pf2e.spell` or `pf2e.action` (late targeting, GM
// manual acts). Free of Foundry globals, so it runs under `node --test`.

/** The roll option pf2e (8.5+) puts on an actual cast, as opposed to a spell sent to chat. */
const CAST = "origin:action:slug:cast-a-spell";

/** Check types that follow an act rather than start one. */
const AFTERMATH = ["damage-roll", "damage-taken"];

/**
 * @param {{type?: string | null, item?: string | null, options?: Iterable<string>, reroll?: boolean}} check
 *   the check's or card's context type, its origin item's type, its roll options, a re-roll
 * @returns {"strike" | "spell" | "action" | null}
 */
export function actOf({ type, item, options = [], reroll = false }) {
  const opts = [...options];
  if (reroll || AFTERMATH.includes(String(type))) return null;
  if (item === "spell") return type === "attack-roll" || opts.includes(CAST) ? "spell" : null;
  if (type === "attack-roll") return "strike";
  if (type === "self-effect" || item === "action" || opts.some((o) => o.startsWith("action:"))) {
    return "action";
  }
  return null;
}
