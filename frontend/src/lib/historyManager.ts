import type { GeometryOperation, BatchOperation } from './editOperations';
import { serializeOperation, deserializeOperation, isBatchOperation } from './editOperations';
import { createBatchOperation } from './operationFactories';

export const DEFAULT_MAX_STACK_SIZE = 100;
export const AUTO_SAVE_INTERVAL_MS = 30_000;
const STORAGE_KEY_PREFIX = 'geom_history_';

export interface HistoryManagerOptions {
  maxSize?: number;
  instanceId: string;
  userId: string;
  autoSave?: boolean;
}

export interface HistorySnapshot {
  readonly undoStack: readonly GeometryOperation[];
  readonly redoStack: readonly GeometryOperation[];
  readonly maxSize: number;
  readonly lastSaved: number;
}

export class GeometryHistoryManager {
  private readonly _undoStack: GeometryOperation[] = [];
  private readonly _redoStack: GeometryOperation[] = [];
  private readonly _maxSize: number;
  private readonly _instanceId: string;
  private readonly _userId: string;
  private _lastSaved: number = 0;
  private _autoSaveTimer: ReturnType<typeof setInterval> | null = null;
  private _dirty: boolean = false;

  constructor(options: HistoryManagerOptions) {
    this._maxSize = options.maxSize ?? DEFAULT_MAX_STACK_SIZE;
    this._instanceId = options.instanceId;
    this._userId = options.userId;
    this._lastSaved = Date.now();
    this._tryRestore();
    if (options.autoSave !== false) {
      this._startAutoSave();
    }
  }

  get undoStack(): readonly GeometryOperation[] {
    return this._undoStack as readonly GeometryOperation[];
  }
  get redoStack(): readonly GeometryOperation[] {
    return this._redoStack as readonly GeometryOperation[];
  }
  get canUndo(): boolean {
    return this._undoStack.length > 0;
  }
  get canRedo(): boolean {
    return this._redoStack.length > 0;
  }
  get undoDepth(): number {
    return this._undoStack.length;
  }
  get redoDepth(): number {
    return this._redoStack.length;
  }
  get maxSize(): number {
    return this._maxSize;
  }
  get instanceId(): string {
    return this._instanceId;
  }
  get lastSaved(): number {
    return this._lastSaved;
  }

  push(operation: GeometryOperation): GeometryOperation {
    this._redoStack.length = 0;
    this._undoStack.push(operation);
    while (this._undoStack.length > this._maxSize) {
      this._undoStack.shift();
    }
    this._dirty = true;
    return operation;
  }

  undo(): GeometryOperation | null {
    if (this._undoStack.length === 0) return null;
    const operation = this._undoStack.pop()!;
    this._redoStack.push(operation);
    this._dirty = true;
    return operation;
  }

  redo(): GeometryOperation | null {
    if (this._redoStack.length === 0) return null;
    const operation = this._redoStack.pop()!;
    this._undoStack.push(operation);
    this._dirty = true;
    return operation;
  }

  peekUndo(): GeometryOperation | null {
    if (this._undoStack.length === 0) return null;
    return this._undoStack[this._undoStack.length - 1];
  }

  peekRedo(): GeometryOperation | null {
    if (this._redoStack.length === 0) return null;
    return this._redoStack[this._redoStack.length - 1];
  }

  clear(): void {
    this._undoStack.length = 0;
    this._redoStack.length = 0;
    this._dirty = true;
    this._clearStorage();
  }

  pushBatch(operations: GeometryOperation[]): GeometryOperation {
    const batchOp = createBatchOperation(operations, {
      timestamp: Date.now(),
      label: `Batch: ${operations.map(o => o.kind).join(', ')}`,
    });
    this._undoStack.push(batchOp);
    this._redoStack.length = 0;
    this._dirty = true;
    return batchOp;
  }

  private get _storageKey(): string {
    return `${STORAGE_KEY_PREFIX}${this._instanceId}`;
  }

  toJSON(): HistorySnapshot {
    return {
      undoStack: this._undoStack.map((op) => serializeOperation(op) as GeometryOperation),
      redoStack: this._redoStack.map((op) => serializeOperation(op) as GeometryOperation),
      maxSize: this._maxSize,
      lastSaved: this._lastSaved,
    };
  }

  fromJSON(snapshot: HistorySnapshot): void {
    this._undoStack.length = 0;
    this._redoStack.length = 0;
    for (const op of snapshot.undoStack) {
      this._undoStack.push(deserializeOperation(op));
    }
    for (const op of snapshot.redoStack) {
      this._redoStack.push(deserializeOperation(op));
    }
    this._lastSaved = snapshot.lastSaved ?? Date.now();
    this._dirty = false;
  }

  save(): boolean {
    try {
      const json = this.toJSON();
      localStorage.setItem(this._storageKey, JSON.stringify(json));
      this._lastSaved = Date.now();
      this._dirty = false;
      return true;
    } catch (err) {
      console.error('[GeometryHistoryManager] Save failed:', err);
      return false;
    }
  }

  private _tryRestore(): boolean {
    try {
      const raw = localStorage.getItem(this._storageKey);
      if (!raw) return false;
      const parsed = JSON.parse(raw) as HistorySnapshot;
      if (!parsed || !Array.isArray(parsed.undoStack) || !Array.isArray(parsed.redoStack)) {
        console.warn('[GeometryHistoryManager] Corrupt localStorage data — ignoring');
        this._clearStorage();
        return false;
      }
      this.fromJSON(parsed);
      console.debug(`[GeometryHistoryManager] Restored ${this._undoStack.length} ops from localStorage`);
      return true;
    } catch (err) {
      console.error('[GeometryHistoryManager] Restore failed:', err);
      this._clearStorage();
      return false;
    }
  }

  private _clearStorage(): void {
    try {
      localStorage.removeItem(this._storageKey);
    } catch {
    }
  }

  private _startAutoSave(): void {
    if (this._autoSaveTimer !== null) return;
    this._autoSaveTimer = setInterval(() => {
      if (this._dirty) {
        this.save();
      }
    }, AUTO_SAVE_INTERVAL_MS);
    if (typeof this._autoSaveTimer === 'object' && 'unref' in this._autoSaveTimer) {
      (this._autoSaveTimer as NodeJS.Timeout).unref();
    }
  }

  private _stopAutoSave(): void {
    if (this._autoSaveTimer !== null) {
      clearInterval(this._autoSaveTimer);
      this._autoSaveTimer = null;
    }
  }

  dispose(): void {
    this._stopAutoSave();
    if (this._dirty) {
      this.save();
    }
  }

  flush(): void {
    if (this._dirty) {
      this.save();
    }
  }
}

export function createHistoryManager(
  instanceId: string,
  userId: string,
  options?: Partial<HistoryManagerOptions>,
): GeometryHistoryManager {
  return new GeometryHistoryManager({
    instanceId,
    userId,
    maxSize: options?.maxSize ?? DEFAULT_MAX_STACK_SIZE,
    autoSave: options?.autoSave ?? true,
  });
}
