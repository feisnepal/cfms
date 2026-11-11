// Forest Structure depth model (migration 094). Mirrors
// backend/app/services/forest_units/model.py: every TOP-LEVEL unit — block or
// compartment — lives at depth 1; any sub-unit at depth 2+; the boundary is
// depth 0 but is never a unit row. Since blocks and compartments share depth 1,
// callers must branch on `is_compartment` (the branch), never on depth alone
// (I10), and only use the depth to separate a top-level compartment from a
// sub-unit.
export const DEPTH_ROOT = 0;
export const DEPTH_TOP_BLOCK = 1;
export const DEPTH_TOP_COMPARTMENT = 1;
export const DEPTH_SUB = 2;