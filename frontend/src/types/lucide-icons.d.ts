// lucide-react ships each icon's raw shape data (`__iconNode`) but no declaration for the deep
// module path; lib/activityKindIcons.ts reads it to build marker SVGs without rendering React.
declare module 'lucide-react/dist/esm/icons/*.js' {
  export const __iconNode: Array<[string, Record<string, string>]>;
}
