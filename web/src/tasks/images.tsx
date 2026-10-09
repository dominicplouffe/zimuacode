import { useState, type ClipboardEvent } from 'react'

// Mirrors the server's limits (app/tasks/attachments.py).
export const MAX_IMAGES = 5
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']

export interface PastedImage {
  id: number
  /** For the thumbnail. */
  url: string
  /** What the API takes: the file's bytes in base64. */
  data: string
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

let nextId = 1

/**
 * Images pasted into a text box. Pasting an image file (a screenshot, "Copy Image") adds it
 * here instead of the text box; pasting text is left alone.
 * `supported` is false for agents that can't take images; pasting then explains why.
 */
export function usePastedImages(supported: boolean) {
  const [images, setImages] = useState<PastedImage[]>([])
  const [error, setError] = useState<string | null>(null)

  const onPaste = async (e: ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'))
    if (files.length === 0 || e.clipboardData.types.includes('text/plain')) return
    e.preventDefault()
    if (!supported) {
      setError("This agent can't take images")
      return
    }
    const added: PastedImage[] = []
    let problem: string | null = null
    for (const file of files) {
      if (!TYPES.includes(file.type)) problem = 'Only PNG, JPEG, GIF and WebP images are supported'
      else if (file.size > MAX_IMAGE_BYTES) problem = `Images can be at most ${MAX_IMAGE_BYTES / 1024 / 1024} MB`
      else if (images.length + added.length >= MAX_IMAGES) problem = `At most ${MAX_IMAGES} images per message`
      else {
        const url = await readAsDataUrl(file)
        added.push({ id: nextId++, url, data: url.slice(url.indexOf(',') + 1) })
      }
    }
    setImages((current) => [...current, ...added])
    setError(problem)
  }

  return {
    images,
    /** Why the last paste was refused, if it was. */
    error,
    onPaste,
    remove: (id: number) => setImages((current) => current.filter((i) => i.id !== id)),
    clear: () => {
      setImages([])
      setError(null)
    },
  }
}

/** The pending images under a text box, each removable. */
export function ImageStrip({ images, onRemove }: { images: PastedImage[]; onRemove: (id: number) => void }) {
  if (images.length === 0) return null
  return (
    <div className="image-strip">
      {images.map((image) => (
        <div key={image.id} className="image-thumb">
          <img src={image.url} alt="Pasted" />
          <button className="image-remove" aria-label="Remove image" onClick={() => onRemove(image.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  )
}

/** Images attached to a message in the transcript. They're gone once the task is archived. */
export function SentImages({ taskId, names }: { taskId: string; names: string[] }) {
  const [missing, setMissing] = useState<string[]>([])
  return (
    <div className="image-strip">
      {names
        .filter((name) => !missing.includes(name))
        .map((name) => {
          const src = `/api/tasks/${taskId}/attachments/${name}`
          return (
            <a key={name} className="image-thumb" href={src} target="_blank" rel="noreferrer">
              <img src={src} alt="Attached" onError={() => setMissing((m) => [...m, name])} />
            </a>
          )
        })}
    </div>
  )
}
