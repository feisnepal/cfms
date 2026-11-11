/**
 * WorkflowStepper — the primary working surface.
 *
 * The tests concentrate on the governing rule, because it is the one a component
 * like this erodes by accident: **nothing is ever locked.** Every assertion about
 * an unmet prerequisite checks that the control is still enabled and still
 * clickable, because "sequence, don't enforce" is one refactor away from becoming
 * a wizard that traps a user whose data is not ready.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import WorkflowStepper from '../WorkflowStepper';

vi.mock('../../../i18n/hooks', () => ({
  useT: () => (k: string, o?: Record<string, unknown>) =>
    o ? `${k}:${Object.values(o).join(',')}` : k,
}));

const never = () => false;
const base = {
  onNavigate: vi.fn(),
  isDone: never,
  stale: [] as { step: string; seen: number }[],
  loading: false,
};

describe('WorkflowStepper', () => {
  it('shows the position in the flow and the current step', () => {
    render(<WorkflowStepper {...base} activeContext="unified" />);
    expect(screen.getByText(/workflow\.stepper\.stepOf:1,16/)).toBeInTheDocument();
    expect(screen.getByText('workspace.sidebar.map')).toBeInTheDocument();
  });

  it('renders one segment per step, marking the current one', () => {
    render(<WorkflowStepper {...base} activeContext="sampling" />);
    const current = document.querySelectorAll('[aria-current="step"]');
    expect(current).toHaveLength(1);
    expect(document.querySelectorAll('ol li')).toHaveLength(16);
  });

  it('Next advances to the next incomplete input step', () => {
    const onNavigate = vi.fn();
    render(<WorkflowStepper {...base} onNavigate={onNavigate} activeContext="unified" />);
    fireEvent.click(screen.getByText('workflow.stepper.next'));
    expect(onNavigate).toHaveBeenCalledWith('base', 'usergroup');
  });

  it('the Next chevron advances to the same place as the Next button', () => {
    // Two controls, one rule — they must not drift apart. The chevron is
    // selected by test id because both it and the text button carry the same
    // accessible name, and `getByLabelText` cannot tell them apart.
    const onNavigate = vi.fn();
    render(<WorkflowStepper {...base} onNavigate={onNavigate} activeContext="unified" />);
    fireEvent.click(screen.getByTestId('workflow-stepper-next'));
    expect(onNavigate).toHaveBeenCalledWith('base', 'usergroup');
  });

  it('Back is disabled on the first step and navigates elsewhere', () => {
    const onNavigate = vi.fn();
    const { unmount } = render(
      <WorkflowStepper {...base} onNavigate={onNavigate} activeContext="unified" />,
    );
    expect(screen.getByLabelText('workflow.stepper.back')).toBeDisabled();
    unmount();

    render(<WorkflowStepper {...base} onNavigate={onNavigate} activeContext="sampling" />);
    fireEvent.click(screen.getByTestId('workflow-stepper-back'));
    // Step 4 (Sampling) -> step 3 (Fieldbook), which is in the `field` phase.
    expect(onNavigate).toHaveBeenCalledWith('field', 'fieldbook');
  });

  it('a step segment is clickable and navigates to that step', () => {
    const onNavigate = vi.fn();
    render(<WorkflowStepper {...base} onNavigate={onNavigate} activeContext="unified" />);
    fireEvent.click(screen.getByTitle('5. inventory.title'));
    expect(onNavigate).toHaveBeenCalledWith('field', 'fieldinventory');
  });

  // ── the governing rule ──────────────────────────────────────────────────
  it('shows what a step is waiting on WITHOUT blocking it', () => {
    const onNavigate = vi.fn();
    render(
      <WorkflowStepper
        {...base}
        onNavigate={onNavigate}
        activeContext="fieldinventory"
        isDone={(id) => id !== 'sampling'}
      />,
    );
    // It says what is missing…
    expect(screen.getByText(/workflow\.stepper\.waitingOn/)).toBeInTheDocument();
    // …and every control still works.
    expect(screen.queryByLabelText('workflow.stepper.back')).not.toBeDisabled();
    expect(screen.getAllByLabelText('workflow.stepper.next')[0]).toBeEnabled();
    fireEvent.click(screen.getAllByLabelText('workflow.stepper.next')[0]);
    expect(onNavigate).toHaveBeenCalled();
  });

  it('Skip for now advances without pretending anything is done', () => {
    // Progress comes from the server, so navigating cannot fake it. The step
    // still reports not-done afterwards.
    const onNavigate = vi.fn();
    render(<WorkflowStepper {...base} onNavigate={onNavigate} activeContext="unified" />);
    fireEvent.click(screen.getByText('workflow.stepper.skip'));
    expect(onNavigate).toHaveBeenCalledWith('base', 'usergroup');
    expect(screen.queryByText('workflow.stepper.done')).not.toBeInTheDocument();
  });

  it('marks a done step', () => {
    render(<WorkflowStepper {...base} activeContext="unified" isDone={() => true} />);
    expect(screen.getByText('workflow.stepper.done')).toBeInTheDocument();
  });

  it('shows a staleness flag with the version it predates', () => {
    render(
      <WorkflowStepper
        {...base}
        activeContext="sampling"
        stale={[{ step: 'sampling', seen: 2 }]}
      />,
    );
    expect(screen.getByText(/workflow\.stepper\.stale:2/)).toBeInTheDocument();
  });

  it('shows nothing extra when there is nothing to report', () => {
    const { container } = render(<WorkflowStepper {...base} activeContext="unified" />);
    expect(container.textContent).not.toContain('workflow.stepper.waitingOn');
    expect(container.textContent).not.toContain('workflow.stepper.stale');
  });

  it('shows a checking state while readiness loads', () => {
    render(<WorkflowStepper {...base} activeContext="unified" loading />);
    expect(screen.getByText('workflow.stepper.checking')).toBeInTheDocument();
  });

  it('falls back to the first step for an unknown context, without crashing', () => {
    // e.g. a legacy deep link that resolved to a passthrough view.
    render(<WorkflowStepper {...base} activeContext="block_naming" />);
    expect(screen.getByText('workspace.sidebar.map')).toBeInTheDocument();
  });

  it('prints each step number as a small chip (name in the tooltip), green when done and grey when not', () => {
    render(<WorkflowStepper activeContext="fieldinventory" onNavigate={() => {}} isDone={(id) => id === 'sampling'} />);
    const done = screen.getByTitle('4. navigation.sampling');
    const notDone = screen.getByTitle('5. inventory.title');
    // the text is the step itself, not only its tooltip
    expect(done.textContent).toBe('4'); // the number is the text; the name is the tooltip
    expect(notDone.textContent).toBe('5');
    expect(done.getAttribute('data-done')).toBe('true');
    expect(done.className).toContain('text-green-800');
    expect(done.className).toContain('bg-green-200'); // a snug tint only: no fill-width box
    expect(notDone.getAttribute('data-done')).toBe('false');
    const idle = screen.getByTitle('3. workspace.sidebar.fieldbook'); // not done and not the current step
    expect(idle.className).toContain('text-gray-700');
    expect(idle.className).toContain('bg-gray-200');
    expect(notDone.className).toContain('font-bold');
  });

  it('marks the step the user is on with an underline and its own colour, whether it is done or not', () => {
    const { unmount } = render(<WorkflowStepper activeContext="fieldinventory" onNavigate={() => {}} isDone={(id) => id === 'sampling'} />);
    const current = screen.getByTitle('5. inventory.title'); // not done
    expect(current.className).toContain('text-blue-900');
    expect(current.className).toContain('underline');
    expect(screen.getByTitle('4. navigation.sampling').className).toContain('text-green-800'); // done, not current
    expect(screen.getByTitle('3. workspace.sidebar.fieldbook').className).toContain('text-gray-700'); // not done, not current
    unmount();

    render(<WorkflowStepper activeContext="sampling" onNavigate={() => {}} isDone={(id) => id === 'sampling'} />);
    expect(screen.getByTitle('4. navigation.sampling').className).toContain('text-green-950'); // current AND done
  });

  it('outlines the steps the system fills in (optional / review), keeps required steps solid, and names the kind in the tooltip', () => {
    render(<WorkflowStepper activeContext="unified" onNavigate={() => {}} isDone={() => false} />);
    const required = screen.getByTitle('1. workspace.sidebar.map');
    const optional = screen.getByTitle(/^9\. .*\(workflow\.need\.optional\)$/);
    const review = screen.getByTitle(/^13\. .*\(workflow\.need\.review\)$/);
    expect(required.className).not.toContain('border');
    expect(optional.className).toContain('border-dashed');
    expect(review.className).toContain('border-amber-500');
    expect(screen.getByTitle('6. workspace.sidebar.forestMetadata (workflow.stepper.incomplete)').className).not.toContain('border'); // Forest Metadata is required
  });

  it('shows the Forest Metadata step RED until the form is complete, and green once the server says it is done', () => {
    const { unmount } = render(<WorkflowStepper activeContext="unified" onNavigate={() => {}} isDone={() => false} />);
    expect(screen.getByTitle(/^6\. .* \(workflow\.stepper\.incomplete\)$/).className).toContain('bg-red-200');
    expect(screen.getByTitle('7. workspace.sidebar.biodiversity').className).not.toContain('red'); // only the strict form step goes red
    unmount();
    render(<WorkflowStepper activeContext="unified" onNavigate={() => {}} isDone={(id) => id === 'forestmetadata'} />);
    const done = screen.getByTitle('6. workspace.sidebar.forestMetadata');
    expect(done.className).toContain('bg-green-200');
    expect(done.className).not.toContain('red');
  });

  it('outlines the steps the system fills in (optional / review) and keeps required steps solid, with the kind in the tooltip', () => {
    render(<WorkflowStepper activeContext="unified" onNavigate={() => {}} isDone={() => false} />);
    const required = screen.getByTitle('1. workspace.sidebar.map');
    const optional = screen.getByTitle(/^9\. .*\(workflow\.need\.optional\)$/);
    const review = screen.getByTitle(/^13\. .*\(workflow\.need\.review\)$/);
    expect(required.className).not.toContain('border');
    expect(optional.className).toContain('border-dashed');
    expect(review.className).toContain('border-amber-500');
    expect(screen.getByTitle('6. workspace.sidebar.forestMetadata (workflow.stepper.incomplete)').className).not.toContain('border'); // Forest Metadata is required
  });
});
