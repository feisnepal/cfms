import sys, os
sys.path.insert(0, 'scripts')
import check_diff_coverage as g

changed = g.changed_lines_by_file('origin/master')
hits_by_file = g.coverage_hits_by_file()

total = 0
unc_total = 0
per_file = {}
for path, lines in sorted(changed.items()):
    file_hits = hits_by_file.get(path)
    if file_hits is None:
        continue
    unc = [ln for ln in sorted(lines) if ln in file_hits and file_hits[ln] == 0]
    if unc:
        unc_total += len(unc)
        per_file[path] = unc
        print(f"{path}: {unc}")
    total += sum(1 for ln in lines if ln in file_hits)
print("EXECUTABLE changed lines:", total, "uncovered:", unc_total)
