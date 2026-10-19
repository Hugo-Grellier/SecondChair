# The Bell Below the Weir

An original synthetic campaign in English. Starting date and world-turn cursor:
**0302-04-25 RB**. All numbered statements are scenario starting facts, stipulated
by the campaign author; these are import material, not authenticated GM decisions.
All facts start at that date unless stated otherwise. No session has happened yet.

## Public material

### Place and common knowledge

- **B01**: Reedbank (`place-reedbank`) stands beside the floodgate called the Weir
  (`place-weir`). Its warning bell has rung on dry nights for a week.
- **B02**: Every inhabitant of Reedbank knows the bell is ringing and the council
  controls the gate. These are common knowledge; the cause is not.
- **B03**: The party (`party`) consists of four PCs: Ada Fen (`pc-ada`, carpenter),
  Beren Pike (`pc-beren`, courier), Cora Sedge (`pc-cora`, herbalist), and Dain
  Wold (`pc-dain`, surveyor). Individual PCs are not separate knowers.

### Factions

- **B04**: The Lock Council (`faction-council`) controls the gate and wants the
  toll revenue preserved. Its member is Mira Pell (`npc-mira`).
- **B05**: The Reed Union (`faction-union`) represents the boat crews and wants
  safe passage without a toll increase. Its member is Tovan Reed (`npc-tovan`).
- **B06**: The Sounding Circle (`faction-circle`) maintains the warning apparatus
  and wants its independence preserved. Its publicly known member is Edda Vale
  (`npc-edda`); a further membership is recorded in secret-identity.

### NPC identities and acting cues

Exactly six NPCs exist in this sample. The first five live in Reedbank and inherit
its common knowledge. `npc-hidden` lives at the isolated Cistern (`place-cistern`),
with no common knowledge assigned there. Faction membership grants only that
faction's recorded knowledge, never the knowledge of other members.

| ID | Public name | Public description / immediate goal |
|---|---|---|
| npc-mira | Mira Pell | Council clerk; obtain a signed repair estimate. |
| npc-tovan | Tovan Reed | Boat captain; keep the public landing open. |
| npc-edda | Edda Vale | Bell keeper; inspect the bell chain before Bellnight. |
| npc-sella | Sella Marr | Market cook; retrieve her misplaced blue satchel. |
| npc-orin | Orin Doss | Ferry tender; get the ferry rope replaced. |
| npc-hidden | (none) | No party-facing description or public alias. See secret-identity. |

### Small hex map

One adjacent hex costs one day on foot; axial coordinates `(q,r)` use neighbors
`(+1,0)`, `(0,+1)`, `(-1,+1)`, `(-1,0)`, `(0,-1)`, `(+1,-1)`.
These are all six hexes. The three outer sites connect through the central bank.

| Hex | Place ID | Site |
|---|---|---|
| 0,0 | place-reedbank | Reedbank market and public landing |
| 1,0 | place-weir | Weir and bell housing |
| 0,1 | place-archive | Toll Archive |
| -1,1 | place-kiln | Abandoned Kiln |
| -1,0 | place-cistern | Cistern, shuttered maintenance chamber |
| 0,-1 | place-ferry | Rope Ferry |

### Situations

- **B07**: `situation-chain`, Inspect the Chain, is **active**: Edda has hired the
  party to inspect the bell housing. Hook: she offers a repair fee. Deadline
  **0302-05-01**. Its stakes are whether the bell can be trusted on the festival.
  At the deadline, queue a narrative-direction proposal; do not automatically
  fail the engaged party or disclose an outcome.
- **B08**: `situation-ferry`, Replace the Rope, is **available**: Orin offers free
  crossings for a replacement rope. Deadline **0302-06-03**. If still unengaged,
  it expires as a rule effect; only Orin is a named participant. Expiry closes the
  offer, not the ferry, and kills no one.
- **B09**: `situation-satchel`, Find the Satchel, is **available**, with no deadline.
  Hook: Sella offers a hot meal; her blue satchel was last seen at the market.

## Secret zones

Only the four explicitly bounded sections below are secret zones. Their canaries
are inert literal markers, never facts anyone knows. The gold set and review are evaluator-only.

### secret-identity

CANARY-identity-1

- **B10**: `npc-hidden` has only the secret name **Ilex Venn**; it has no public
  name and no alias. The name is known only to `npc-hidden` and Edda at start.
- **B11**: `npc-hidden` maintains the Cistern's pressure relay and belongs to the
  Sounding Circle. Membership is known only to `npc-hidden` and Edda, not to the
  faction as a whole. The NPC wants the relay repaired without exposing its name.

### secret-mystery

CANARY-mystery-1

`mystery-bell`, The Dry Bell, has exactly two conclusions:

- **conclusion-relay** / **B12**: A cracked pressure relay at the Cistern, not rising
  water, is causing the dry-night bell. Known initially to `npc-hidden` only.
- **conclusion-ledger** / **B13**: Mira diverted the relay repair fund into an
  unofficial toll reserve; she did not sabotage the relay. Known initially to
  Mira only. The Circle, Union and Council do not know either conclusion.

Four investigation nodes, with seven clues total. Clues are discoverable evidence,
not facts already known by the party. Inspection requires a disclosure approved by
the GM. No clue contains the hidden NPC's name.

| Node ID | Place | Clue ID / evidence | Supports |
|---|---|---|---|
| node-weir | place-weir | clue-1: the dry gauge remains at zero while the bell rings | conclusion-relay |
| node-weir | place-weir | clue-2: a pressure pulse runs down the Cistern conduit | conclusion-relay |
| node-archive | place-archive | clue-3: the relay repair account is empty | conclusion-ledger |
| node-archive | place-archive | clue-4: Mira signed the transfer to an unofficial toll reserve | conclusion-ledger |
| node-kiln | place-kiln | clue-5: an unused replacement relay bears the repair account number | conclusion-ledger |
| node-kiln | place-kiln | clue-6: a test log ties false bells to a hairline relay crack | conclusion-relay |
| node-cistern | place-cistern | clue-7: the installed relay's visible crack pulses with the bell | conclusion-relay |

- **B14**: Tovan believes the Circle deliberately rings false warnings to close
  the landing. This is never true, and is a belief held only by Tovan, not by the
  Union or the party. No NPC acting cue may state it as established truth.

### secret-world

CANARY-world-1

Two fronts; both start at clock **0/4**, running and anchored at **0302-04-25**.
Their first tick is strictly after the anchor. Rates are one clock segment per
**1w = 6d**. Cap at 4. At a shared date, resolve ticks before threshold steps.

- **B15**: `front-tolls`, Toll Squeeze, is carried by `faction-council`, with Mira
  as its only named participant. Unconditional ticks fall on 0302-05-01,
  0302-06-06, 0302-06-12 and 0302-06-18. At threshold 2, its single agenda step
  records that the Council has drafted a toll increase. This is offscreen,
  known only to the Council and Mira. It does not enact or disclose the increase.
- **B16**: `front-silt`, Silt Choke, is carried by `faction-union`, with Tovan as
  its only named participant. Same tick dates, **unless the bypass is open**.
  `B17` settles the first tick as not suppressed. Each later tick requires a
  cited, temporally valid bypass fact; absent one, ask at the next break and keep
  that tick queued. At threshold 2, its single agenda step records that the Union
  has prepared a dredging petition, known only to Union and Tovan.
- **B17**: The bypass is closed from 0302-04-25 until changed in play. Initially
  the party, Tovan and the Union know this. The fact establishes an ongoing state;
  silence in a later note does not end its validity.

No front spreads knowledge automatically. No offscreen effect teaches the party
anything. Any spread to an additional NPC/faction is a separate derived consequence
citing the originating fact. Disclosure to the party needs GM approval.

### secret-treasure

CANARY-treasure-1

- **B18**: Planned treasure `treasure-fee` is 12 silver coins held by Edda as the
  fee for inspecting the bell chain. Only Edda knows the amount initially. Award
  only after play establishes it; do not count planned treasure as party-owned.
- **B19**: Planned treasure `treasure-case` is a brass survey case hidden under
  the Kiln's cold hearth. It is unclaimed; no knower knows its location initially.
  It contains a campaign-made measuring cord, with no mechanical bonus or rules text.
