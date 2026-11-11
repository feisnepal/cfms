/**
 * The glyph inside an Activity Features point marker, as an inline SVG string.
 *
 * lucide-react exposes each icon's raw shape data (`__iconNode`) next to its component. Reading
 * that directly lets the map build a marker's HTML without rendering a React tree per point (and
 * without pulling in a server renderer). Only the icons listed here are imported, one per kind.
 */
import { __iconNode as axe } from 'lucide-react/dist/esm/icons/axe.js';
import { __iconNode as ban } from 'lucide-react/dist/esm/icons/ban.js';
import { __iconNode as bird } from 'lucide-react/dist/esm/icons/bird.js';
import { __iconNode as binoculars } from 'lucide-react/dist/esm/icons/binoculars.js';
import { __iconNode as circleDot } from 'lucide-react/dist/esm/icons/circle-dot.js';
import { __iconNode as droplets } from 'lucide-react/dist/esm/icons/droplets.js';
import { __iconNode as eye } from 'lucide-react/dist/esm/icons/eye.js';
import { __iconNode as fence } from 'lucide-react/dist/esm/icons/fence.js';
import { __iconNode as flag } from 'lucide-react/dist/esm/icons/flag.js';
import { __iconNode as flame } from 'lucide-react/dist/esm/icons/flame.js';
import { __iconNode as footprints } from 'lucide-react/dist/esm/icons/footprints.js';
import { __iconNode as house } from 'lucide-react/dist/esm/icons/house.js';
import { __iconNode as landmark } from 'lucide-react/dist/esm/icons/landmark.js';
import { __iconNode as leaf } from 'lucide-react/dist/esm/icons/leaf.js';
import { __iconNode as mapPin } from 'lucide-react/dist/esm/icons/map-pin.js';
import { __iconNode as route } from 'lucide-react/dist/esm/icons/route.js';
import { __iconNode as scissors } from 'lucide-react/dist/esm/icons/scissors.js';
import { __iconNode as shield } from 'lucide-react/dist/esm/icons/shield.js';
import { __iconNode as signpost } from 'lucide-react/dist/esm/icons/signpost.js';
import { __iconNode as sprout } from 'lucide-react/dist/esm/icons/sprout.js';
import { __iconNode as target } from 'lucide-react/dist/esm/icons/target.js';
import { __iconNode as towerControl } from 'lucide-react/dist/esm/icons/tower-control.js';
import { __iconNode as treeDeciduous } from 'lucide-react/dist/esm/icons/tree-deciduous.js';
import { __iconNode as treePine } from 'lucide-react/dist/esm/icons/tree-pine.js';
import { __iconNode as trees } from 'lucide-react/dist/esm/icons/trees.js';
import { __iconNode as users } from 'lucide-react/dist/esm/icons/users.js';
import { __iconNode as warehouse } from 'lucide-react/dist/esm/icons/warehouse.js';
import { __iconNode as waves } from 'lucide-react/dist/esm/icons/waves.js';
import { __iconNode as wheat } from 'lucide-react/dist/esm/icons/wheat.js';

type IconNode = Array<[string, Record<string, string>]>;

export const ACTIVITY_KIND_ICONS = {
  axe, ban, bird, binoculars, circleDot, droplets, eye, fence, flag, flame, footprints, house, landmark,
  leaf, mapPin, route, scissors, shield, signpost, sprout, target, towerControl, treeDeciduous,
  treePine, trees, users, warehouse, waves, wheat,
} as Record<string, IconNode>;

export type ActivityKindIconName = keyof typeof ACTIVITY_KIND_ICONS;

/** An inline `<svg>` for one icon, stroked in `color` (white on a coloured marker). */
export function iconSvg(name: string, color: string, sizePx: number): string {
  const nodes = ACTIVITY_KIND_ICONS[name] ?? ACTIVITY_KIND_ICONS.mapPin;
  const body = nodes
    .map(([tag, attrs]) => {
      const a = Object.entries(attrs)
        .filter(([k]) => k !== 'key')
        .map(([k, v]) => `${k}="${v}"`)
        .join(' ');
      return `<${tag} ${a}/>`;
    })
    .join('');
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${sizePx}" height="${sizePx}" viewBox="0 0 24 24" ` +
    `fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`
  );
}
