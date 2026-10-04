// Detective mode's view of one turn (ADR-0019). For now the raw trace, folded under the reply: the
// plumbing proven end to end. The designed panel replaces it.

import type { TurnTrace } from "@pattern-blue/contracts";
import { useId, useState } from "react";
import type { Dictionary } from "../../i18n";

export function TraceFold({ trace, dict }: { trace: TurnTrace; dict: Dictionary }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="pb-proof" data-detective>
      <button className="pb-proof__more" type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}>
        {open ? dict.chat.detective.hide : dict.chat.detective.show} · {trace.events.length} · {Math.round(trace.total_ms)} ms
      </button>
      <div id={id} hidden={!open}>
        <pre className="pb-proof__ref">{JSON.stringify(trace, null, 2)}</pre>
      </div>
    </div>
  );
}
