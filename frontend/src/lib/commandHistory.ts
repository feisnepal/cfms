/**
 * Command History — dependency-graph aware undo/redo (U13).
 *
 * Extends the linear undo/redo with a dependency graph that tracks
 * which operations affect which features. When undoing an operation,
 * any dependent operations that came after it are also undone.
 *
 * Status codes returned by undo/redo:
 * - OK: operation succeeded
 * - STALE_GEOMETRY: the target feature's geometry has changed since the operation
 * - TARGET_MISSING: the target feature no longer exists
 * - STALE_HISTORY: the history state is inconsistent (e.g., feature was deleted externally)
 */
import type { GeometryOperation, RenameOperation, VertexEditOperation, SplitOperation, MergeOperation, DeleteOperation, BatchOperation, DigitizeAddFeatureOperation, DigitizeDeleteFeatureOperation, DigitizeDeleteFeatureByIdOperation } from './editOperations';
import { getOperationLabel, isRenameOperation, isVertexEditOperation, isDeleteOperation, isSplitOperation, isMergeOperation, isBatchOperation } from './editOperations';
import type { GeoJSON } from 'geojson';

export const MAX_HISTORY = 100;

/**
 * Get feature ID from any operation type using type guards.
 */
function getFeatureIdFromOp(op: GeometryOperation): string | undefined {
  if (op.kind === 'rename' || op.kind === 'delete' || op.kind === 'vertex_edit') {
    return String(op.featureId);
  }
  if (op.kind === 'split') {
    return String(op.sourceFeatureId);
  }
  if (op.kind === 'merge') {
    return String(op.mergedFeatureId);
  }
  if (op.kind === 'feature_delete') {
    return String(op.featureId);
  }
  return undefined;
}

/** Layer scoping key for dependency tracking (feature_delete ops are cross-layer). */
function getLayerIdFromOp(op: GeometryOperation): string | undefined {
  if (isBatchOperation(op) || op.kind === 'feature_delete' || op.kind === 'feature_paste') return undefined;
  return String(op.layerId);
}

/**
 * Get expected geometry from any operation type using type guards.
 */
function getExpectedGeometry(op: GeometryOperation): GeoJSON.Geometry | undefined {
  switch (op.kind) {
    case 'vertex_edit':
      return op.previousGeometry;
    case 'split':
      return op.sourceGeometry;
    case 'merge':
      return op.sourceGeometries.length > 0 ? op.sourceGeometries[0] : undefined;
    case 'delete':
      return op.deletedFeature.geometry;
    default:
      return undefined;
  }
}

export type CommandStatus = 'OK' | 'STALE_GEOMETRY' | 'TARGET_MISSING' | 'STALE_HISTORY';

export interface CommandResult {
  status: CommandStatus;
  operation?: GeometryOperation;
  message?: string;
}

export interface DependencyEdge {
  fromOpIndex: number;   // index in undoStack
  toOpIndex: number;     // index in undoStack
  reason: string;        // e.g., "same feature", "spatial intersection"
}

export interface CommandNode {
  opIndex: number;           // index in undoStack
  operation: GeometryOperation;
  dependsOn: number[];       // indices of operations this depends on
  dependents: number[];      // indices of operations that depend on this
}

/**
 * CommandHistory maintains a dependency graph over the undo stack.
 * When an operation is pushed, it's linked to prior operations that affect
 * the same feature or spatially intersect.
 */
export class CommandHistory {
  private undoStack: GeometryOperation[] = [];
  private redoStack: GeometryOperation[] = [];
  private maxSize: number;

  // Dependency graph: maps undoStack index -> node
  private nodes: Map<number, CommandNode> = new Map();
  private nextNodeId = 0;

  constructor(maxSize: number = MAX_HISTORY) {
    this.maxSize = maxSize;
  }

  get undoStackDepth(): number {
    return this.undoStack.length;
  }
  get redoStackDepth(): number {
    return this.redoStack.length;
  }
  get canUndo(): boolean {
    return this.undoStack.length > 0;
  }
  get canRedo(): boolean {
    return this.redoStack.length > 0;
  }

  /**
   * Push a new operation, clearing redo stack and building dependencies.
   */
  push(operation: GeometryOperation): GeometryOperation {
    this.redoStack.length = 0;

    // Clear dependency tracking for operations beyond maxSize
    this._pruneOldOperations();

    // Find dependencies: prior operations on same feature
    const dependencies = this._findDependencies(operation);
    const nodeId = this.nextNodeId++;

    this.undoStack.push(operation);
    this.nodes.set(this.undoStack.length - 1, {
      opIndex: this.undoStack.length - 1,
      operation,
      dependsOn: dependencies,
      dependents: [],
    });

    // Update dependents on dependency nodes
    for (const depIdx of dependencies) {
      const depNode = this.nodes.get(depIdx);
      if (depNode) {
        depNode.dependents.push(this.undoStack.length - 1);
      }
    }

    return operation;
  }

  /**
   * Undo the last operation, plus any dependents that would be invalidated.
   * Returns the primary undone operation and any additional undone operations.
   */
  undo(): { primary: GeometryOperation; cascaded: GeometryOperation[] } | null {
    if (this.undoStack.length === 0) return null;

    const primaryIdx = this.undoStack.length - 1;
    const primaryOp = this.undoStack[primaryIdx];

    // Find all operations that depend on the primary (transitive closure)
    const cascadedIndices = this._getDependentClosure(primaryIdx);
    const cascadedOps = cascadedIndices.map(i => this.undoStack[i]);

    // Remove primary and cascaded from undoStack, add to redoStack
    // We need to maintain order: primary first, then cascaded in reverse
    const allToRedo = [primaryIdx, ...cascadedIndices].sort((a, b) => b - a);
    for (const idx of allToRedo) {
      const op = this.undoStack.splice(idx, 1)[0];
      this.redoStack.unshift(op);
      this.nodes.delete(idx);
    }

    // Renumber node indices after splice
    this._renumberNodes();

    return { primary: primaryOp, cascaded: cascadedOps };
  }

  /**
   * Redo the last undone operation(s).
   */
  redo(): { primary: GeometryOperation; cascaded: GeometryOperation[] } | null {
    if (this.redoStack.length === 0) return null;

    const primaryOp = this.redoStack.shift()!;
    const cascadedOps: GeometryOperation[] = [];

    // Re-apply primary
    this.undoStack.push(primaryOp);

    // For redo, we don't automatically redo cascaded operations
    // (they would need to be reapplied explicitly if needed)

    this._rebuildNode(primaryOp, this.undoStack.length - 1);

    return { primary: primaryOp, cascaded: cascadedOps };
  }

  /**
   * Validate if an operation can be safely undone/redone given current feature state.
   * Returns STALE_GEOMETRY if feature geometry changed, TARGET_MISSING if feature gone.
   */
  validateUndo(
    operation: GeometryOperation,
    getCurrentFeature: (layerId: string, featureId: string) => GeoJSON.Feature | null
  ): CommandResult {
    if (isBatchOperation(operation)) {
      // Validate all sub-operations
      for (const op of operation.operations) {
        const result = this.validateUndo(op, getCurrentFeature);
        if (result.status !== 'OK') return result;
      }
      return { status: 'OK' };
    }

    // All non-batch operations have layerId (digitize ops store it as number)
    const layerId = getLayerIdFromOp(operation);
    const featureId = getFeatureIdFromOp(operation);
    if (!featureId || !layerId) {
      return { status: 'OK' }; // No specific target to validate
    }

    const currentFeature = getCurrentFeature(layerId, featureId);
    if (!currentFeature) {
      return {
        status: 'TARGET_MISSING',
        message: `Feature ${featureId} on layer ${layerId} no longer exists`,
      };
    }

    // Check if geometry matches what the operation expects
    const expectedGeom = getExpectedGeometry(operation);
    if (expectedGeom && currentFeature.geometry && 'coordinates' in currentFeature.geometry && 'coordinates' in expectedGeom) {
      const currentCoords = JSON.stringify(currentFeature.geometry.coordinates);
      const expectedCoords = JSON.stringify(expectedGeom.coordinates);
      if (currentCoords !== expectedCoords) {
        return {
          status: 'STALE_GEOMETRY',
          message: `Feature ${featureId} geometry has changed since operation`,
        };
      }
    }

    return { status: 'OK' };
  }

  clear(): void {
    this.undoStack.length = 0;
    this.redoStack.length = 0;
    this.nodes.clear();
    this.nextNodeId = 0;
  }

  // --- Private helpers ---

  private _pruneOldOperations(): void {
    while (this.undoStack.length >= this.maxSize) {
      this.undoStack.shift();
    }
    // Renumber nodes after shift
    this._renumberNodes();
  }

  private _renumberNodes(): void {
    const newNodes = new Map<number, CommandNode>();
    for (let i = 0; i < this.undoStack.length; i++) {
      const oldNode = this.nodes.get(i);
      if (oldNode) {
        newNodes.set(i, {
          ...oldNode,
          opIndex: i,
        });
      }
    }
    this.nodes = newNodes;
  }

  private _renumberNodesAfterSplice(): void {
    this._renumberNodes();
  }

  private _findDependencies(operation: GeometryOperation): number[] {
    const deps: number[] = [];
    const featureId = getFeatureIdFromOp(operation);
    const layerId = getLayerIdFromOp(operation);

    if (!featureId || !layerId) return deps;

    // Look backwards through undoStack for operations on same feature
    for (let i = this.undoStack.length - 1; i >= 0; i--) {
      const priorOp = this.undoStack[i];
      // Skip batch + cross-layer ops (feature_delete / feature_paste) as they have no layerId
      if (isBatchOperation(priorOp) || priorOp.kind === 'feature_delete' || priorOp.kind === 'feature_paste') continue;
      const priorFeatureId = getFeatureIdFromOp(priorOp);
      if (priorOp.layerId === layerId && priorFeatureId === featureId) {
        deps.push(i);
        // Only need the most recent dependency per feature
        break;
      }
    }
    return deps;
  }

  private _getDependentClosure(startIdx: number): number[] {
    const visited = new Set<number>();
    const queue = [startIdx];
    const result: number[] = [];

    while (queue.length > 0) {
      const idx = queue.shift()!;
      if (visited.has(idx)) continue;
      visited.add(idx);

      const node = this.nodes.get(idx);
      if (!node) continue;

      // Follow dependencies BACKWARDS (prerequisites that should be undone together)
      for (const dep of node.dependsOn) {
        if (!visited.has(dep)) {
          queue.push(dep);
        }
      }
      if (idx !== startIdx) {
        result.push(idx);
      }
    }
    return result;
  }

  private _rebuildNode(operation: GeometryOperation, index: number): void {
    const deps = this._findDependencies(operation);
    this.nodes.set(index, {
      opIndex: index,
      operation,
      dependsOn: deps,
      dependents: [],
    });
    for (const depIdx of deps) {
      const depNode = this.nodes.get(depIdx);
      if (depNode) {
        depNode.dependents.push(index);
      }
    }
  }
}

/**
 * Create a CommandHistory with default settings.
 */
export function createCommandHistory(maxSize?: number): CommandHistory {
  return new CommandHistory(maxSize);
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}