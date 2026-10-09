/**
 * Scores `text` against `query` as a case-insensitive subsequence match, or returns null when
 * it doesn't match. Higher is better: consecutive characters, word starts and matches inside
 * the file name (after the last "/") earn bonuses, and shorter texts win ties.
 */
export function fuzzyScore(query: string, text: string): number | null {
  if (!query) return 0
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  const nameStart = t.lastIndexOf('/') + 1
  let score = 0
  let ti = 0
  let prev = -2
  for (const ch of q) {
    const found = t.indexOf(ch, ti)
    if (found < 0) return null
    score += 1
    if (found === prev + 1) score += 3
    if (found === 0 || '/_-. '.includes(t[found - 1])) score += 2
    if (found >= nameStart) score += 1
    prev = found
    ti = found + 1
  }
  return score - t.length * 0.01
}

export function fuzzyFilter<T>(
  items: T[],
  query: string,
  text: (item: T) => string,
  limit = 200,
): T[] {
  if (!query) return items.slice(0, limit)
  const scored: { item: T; score: number }[] = []
  for (const item of items) {
    const score = fuzzyScore(query, text(item))
    if (score !== null) scored.push({ item, score })
  }
  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, limit).map((s) => s.item)
}
