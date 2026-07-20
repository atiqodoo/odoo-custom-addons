# POS COD Tinted Oversell Bridge

This technical addon connects the existing COD dispatch path to the existing
POS tracked-lot preassignment path.

It activates only when a picking is completed with `cod_dispatch=True`, is an
outgoing POS picking, and contains a tinted lot/serial-tracked move whose lot
allocation is below demand. It then calls
`_preassign_missing_pos_tracked_lots()` before continuing the unchanged COD
`_action_done()` flow.

The addon intentionally does not change how the existing allocator chooses
positive lots or temporary `POS-...` lots.

Diagnostic log events use the prefix `[COD_TINT_OVERSELL_BRIDGE]`:

- `action_done_enter` / `action_done_exit`
- `skipped` with an explicit reason
- `preassignment_start`
- `preassignment_complete` / `preassignment_incomplete`
- `preassignment_failed` with a traceback
