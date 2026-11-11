import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReportSectionFixLinks } from '../Report/ReportSectionFixLinks';
import { reportSectionFixes, DATA_KEY_LINKS } from '../../lib/exportRequirementLinks';

describe('report section fix links', () => {
  it('links a section with missing data to the page that provides each kind (once per page)', () => {
    const fixes = reportSectionFixes('c1', 'missing_data', ['households', 'committees', 'inventory', 'basic_info', 'raster_analysis']);
    const urls = fixes.map((f) => f.url);
    expect(urls).toContain('/calculations/c1?surface=base%2Funified&open=households');
    expect(urls).toContain('/calculations/c1?surface=base%2Funified&open=committee');
    expect(urls).toContain('/calculations/c1?surface=field%2Ffieldinventory');
    expect(new Set(urls).size).toBe(urls.length);                         // basic_info and raster_analysis share the Map page
  });

  it('sends a hand-written section to the Operational Plan', () => {
    expect(reportSectionFixes('c1', 'manual_input', [])[0].url).toBe('/calculations/c1?surface=plan%2Fmgmtplan');
  });

  it('offers nothing for an available section or an unknown data name', () => {
    expect(reportSectionFixes('c1', 'available', [])).toEqual([]);
    expect(reportSectionFixes('c1', 'missing_data', ['nope'])).toEqual([]);
    expect(reportSectionFixes('', 'manual_input', [])).toEqual([]);
  });

  it('every data name the report asks for has a destination', () => {
    for (const k of ['basic_info', 'boundary', 'species', 'raster_analysis', 'households', 'committees', 'inventory', 'blocks', 'sampling', 'activities', 'biodiversity', 'user_group']) {
      expect(DATA_KEY_LINKS[k], k).toBeTruthy();
    }
  });

  it('renders the links', () => {
    render(<ReportSectionFixLinks calculationId="c1" status="missing_data" missing={['sampling']} />);
    expect(screen.getByTestId('report-fix-sampling').getAttribute('href')).toBe('/calculations/c1?surface=field%2Fsampling');
  });
});
