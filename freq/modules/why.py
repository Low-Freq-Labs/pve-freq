"""FREQ WHY — explain what FREQ can do to a VM and why.

Shows: category, tier, production status, protected status,
allowed actions, blocked actions. Answers "why can't I destroy VM 100?"
"""
from freq.core import fmt
from freq.core.config import FreqConfig


# All possible VM actions
ALL_ACTIONS = ["view", "start", "stop", "restart", "destroy", "clone", "migrate", "snapshot"]


def cmd_why(cfg: FreqConfig, pack, args) -> int:
    """Explain permissions and protections for a VM."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq why <vmid>")
        fmt.info("  Shows category, tier, and what actions are allowed/blocked")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error("Invalid VMID: {}".format(target))
        return 1

    fb = cfg.fleet_boundaries
    cat_name, tier = fb.categorize(vmid)
    allowed = fb.allowed_actions(vmid)
    blocked = [a for a in ALL_ACTIONS if a not in allowed]
    is_prod = fb.is_prod(vmid)
    is_protected = fb.is_protected(vmid)
    description = fb.category_description(vmid)

    fmt.header("Why: VM {}".format(vmid))
    fmt.blank()

    fmt.line("  {b}Category:{r}   {c}{cat}{r}".format(
        b=fmt.C.BOLD, r=fmt.C.RESET, c=fmt.C.CYAN, cat=cat_name))
    fmt.line("  {b}Description:{r} {d}".format(
        b=fmt.C.BOLD, r=fmt.C.RESET, d=description))
    fmt.line("  {b}Tier:{r}       {c}{t}{r}".format(
        b=fmt.C.BOLD, r=fmt.C.RESET, c=fmt.C.CYAN, t=tier))
    fmt.blank()

    # Status flags
    prod_color = fmt.C.RED if is_prod else fmt.C.GREEN
    prod_label = "YES" if is_prod else "no"
    fmt.line("  {b}Production:{r}  {c}{v}{r}".format(
        b=fmt.C.BOLD, r=fmt.C.RESET, c=prod_color, v=prod_label))

    prot_color = fmt.C.YELLOW if is_protected else fmt.C.GREEN
    prot_label = "YES" if is_protected else "no"
    fmt.line("  {b}Protected:{r}  {c}{v}{r}".format(
        b=fmt.C.BOLD, r=fmt.C.RESET, c=prot_color, v=prot_label))
    fmt.blank()

    # Allowed actions
    if allowed:
        fmt.line("  {b}Allowed:{r}    {g}{a}{r}".format(
            b=fmt.C.BOLD, r=fmt.C.RESET, g=fmt.C.GREEN,
            a=", ".join(allowed)))

    # Blocked actions
    if blocked:
        fmt.line("  {b}Blocked:{r}    {red}{a}{r}".format(
            b=fmt.C.BOLD, r=fmt.C.RESET, red=fmt.C.RED,
            a=", ".join(blocked)))

    fmt.blank()

    # Helpful explanation
    if cat_name == "unknown":
        fmt.line("  {d}This VMID is not in any fleet-boundaries category.{r}".format(
            d=fmt.C.DIM, r=fmt.C.RESET))
        fmt.line("  {d}It gets default 'probe' tier (view only).{r}".format(
            d=fmt.C.DIM, r=fmt.C.RESET))
        fmt.line("  {d}Add it to conf/fleet-boundaries.toml for more permissions.{r}".format(
            d=fmt.C.DIM, r=fmt.C.RESET))
    elif blocked:
        fmt.line("  {d}Tier '{t}' doesn't allow: {b}{r}".format(
            d=fmt.C.DIM, t=tier, b=", ".join(blocked), r=fmt.C.RESET))
        fmt.line("  {d}Change tier in conf/fleet-boundaries.toml to unlock.{r}".format(
            d=fmt.C.DIM, r=fmt.C.RESET))

    fmt.blank()
    fmt.footer()
    return 0
