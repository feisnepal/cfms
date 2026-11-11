declare module 'rbush' {
  export interface RBushBBox {
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
  }

  export default class RBush<T extends RBushBBox = RBushBBox> {
    constructor(maxEntries?: number);
    load(items: T[]): this;
    insert(item: T): this;
    remove(item: T, equalsFn?: (a: T, b: T) => boolean): this;
    clear(): this;
    search(bbox: RBushBBox): T[];
    all(): T[];
    toJSON(): { children?: unknown[] };
    fromJSON(data: unknown): this;
  }
}