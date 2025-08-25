import json, os
import db
from dataclasses import dataclass
from typing import List, Literal, Optional, Dict, Iterable

def build_giveitem_command(player_id: int, item: item, qty: int, quality: int, bp: bool) -> str:
  bp_flag = 1 if bp else 0
  return (
    f"scriptcommand giveitemtoplayer {player_id} "
    f"{item} {qty} {quality} {bp_flag}"
  )

def build_spawn_dino_command(eos_id: str, item: dino, lvl: int, breedable: bool) -> str:
  b_flag = "0" if breedable else "1"
  return (
    f"scriptcommand SpawnDinoinBall "
    f"-p={eos_id} -t={dino} -l={lvl} -f=1 -i=1 -b={b_flag} -h=1"
  )

def build_kit_commands(
    components: Iterable[KitComponent],
    *,
    # kit-level defaults (used when a component doesn't set its own)
    player_id: Optional[int] = None,
    eos_id: Optional[str] = None,
    defaults: Optional[Dict[str, object]] = None,
) -> List[str]:
    """
    Build a kit containing items and/or dinos.
    """
    d = defaults or {}
    cmds: List[str] = []

    for c in components:
        if c.kind == "dino":
            cmd = build_spawn_dino_command(
                eos_id=(c.eos_id or eos_id or ""),
                dino=c.ref,
                lvl=int(c.lvl if c.lvl is not None else d.get("lvl", 225)),
                breedable=bool(c.breedable if c.breedable is not None else d.get("breedable", True)),
            )
            cmds.append(cmd)

        elif c.kind == "item":
            cmd = build_giveitem_command(
                player_id=int(c.player_id or player_id or 1),
                item=c.ref,
                qty=int(c.qty if c.qty is not None else d.get("qty", 1)),
                quality=int(c.quality if c.quality is not None else d.get("quality", 1)),
                bp=bool(c.is_bp if c.is_bp is not None else d.get("is_bp", False)),
            )
            cmds.append(cmd)

        else:
            raise ValueError(f"Unknown component kind: {c.kind}")

    return cmds


def build_kit_string(
    components: Iterable[KitComponent],
    *,
    player_id: Optional[int] = None,
    eos_id: Optional[str] = None,
    defaults: Optional[Dict[str, object]] = None,
    delimiter: str = " | ",
) -> str:
    return delimiter.join(
        build_kit_commands(components, player_id=player_id, eos_id=eos_id, defaults=defaults)
    )
