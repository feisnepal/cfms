"""The branch-generic operations engine (P4a, plan §11.2).

One engine for all six structural operations (equal-area divide, natural-feature
divide/auto-create, cut, merge, delete, reshape, copy/paste) across all four unit
types (block / sub-block / compartment / sub-compartment) -- replacing the
compartment-only `compartment_divide_service.py` and the block-only auto-block
paths this phase retires (lean L3).

Modules land here one at a time as each FS-4a.* task is built:
``virtual_root`` (FS-4a.4) is first -- every other operation in this package
needs it to answer "what am I dividing/creating from" the same way, whether or
not a real parent unit row exists.
"""
