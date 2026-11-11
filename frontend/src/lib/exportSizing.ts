export const A5_150DPI_WIDTH = 874
export const A5_150DPI_HEIGHT = 1240

export function fitA5Size(width: number, height: number): { width: number; height: number } {
  const scale = Math.min(A5_150DPI_WIDTH / width, A5_150DPI_HEIGHT / height)
  if (scale >= 1) return { width, height }
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}
