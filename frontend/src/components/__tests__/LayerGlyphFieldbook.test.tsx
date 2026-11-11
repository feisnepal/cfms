import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import LayerGlyph from '../LayerGlyph'

const colours = (type: 'fieldbook' | 'sample_plots') => {
  const { container } = render(<LayerGlyph type={type} />)
  const html = container.innerHTML.toLowerCase()
  return { sky: html.includes('#38bdf8') || html.includes('#0ea5e9'), amber: html.includes('#fbbf24') || html.includes('#f59e0b') }
}

describe('LayerGlyph — Field Book and Sample Plots read as different layers', () => {
  it('Field Book is sky blue, with no amber', () => {
    expect(colours('fieldbook')).toEqual({ sky: true, amber: false })
  })

  it('Sample Plots stay amber, with no sky blue', () => {
    expect(colours('sample_plots')).toEqual({ sky: false, amber: true })
  })
})
