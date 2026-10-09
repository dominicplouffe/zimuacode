import type { Components } from 'react-markdown'

/** Links in rendered Markdown open outside the IDE. */
export const markdownComponents: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
}
