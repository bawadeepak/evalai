// Rendering of model and user content: sanitised Markdown or plain text only.
// No raw HTML, no images (nothing is fetched from content), JSON as text.

import ReactMarkdown from 'react-markdown'

const ALLOWED = ['p', 'strong', 'em', 'del', 'code', 'pre', 'ul', 'ol', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'br', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td']

function safeUrl(url: string): string {
  return /^(https?:|mailto:|#)/i.test(url) ? url : ''
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        skipHtml
        allowedElements={ALLOWED}
        unwrapDisallowed
        urlTransform={safeUrl}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

export function PlainText({ text }: { text: string | null | undefined }) {
  if (text === null || text === undefined || text === '') return <span className="muted">(empty)</span>
  return <pre className="wrap-anywhere" style={{ fontFamily: 'var(--font)', fontSize: 14 }}>{text}</pre>
}

export function Json({ value, label }: { value: unknown; label?: string }) {
  let text: string
  try {
    text = JSON.stringify(value, null, 2) ?? 'null'
  } catch {
    text = String(value)
  }
  return (
    <pre className="box mono" aria-label={label} tabIndex={0} style={{ maxHeight: 420, overflow: 'auto' }}>
      {text}
    </pre>
  )
}

/** Output text with a toggle between plain text and Markdown. */
export function OutputText({ text, markdown }: { text: string | null | undefined; markdown: boolean }) {
  if (!text) return <PlainText text={text} />
  return markdown ? <Markdown text={text} /> : <PlainText text={text} />
}
