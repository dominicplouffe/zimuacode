// eslint-disable-next-line no-control-regex
const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]/g
// GitHub Actions prefixes every line with an ISO timestamp.
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z ?/
const BOM = /^\uFEFF/

/** Makes a GitHub Actions job log readable: no color codes, no timestamps, groups marked. */
export function cleanLog(raw: string): string {
  return raw
    .replace(BOM, '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) =>
      line
        .replace(TIMESTAMP, '')
        .replace(ANSI, '')
        .replace(/^##\[group\]/, '▸ ')
        .replace(/^##\[endgroup\]$/, '')
        .replace(/^##\[(error|warning|notice)\]/, (_, level: string) => `${level.toUpperCase()}: `),
    )
    .join('\n')
}
