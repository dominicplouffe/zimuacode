// Service worker: shows push notifications from the Zimua server and focuses the IDE
// (or opens it) when one is clicked.
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { title: 'Zimua Code', body: event.data ? event.data.text() : '' }
  }
  event.waitUntil(
    self.registration.showNotification(data.title || 'Zimua Code', {
      body: data.body || '',
      tag: data.tag || undefined,
      data: { url: data.url || '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL(event.notification.data?.url || '/', self.location.origin)
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const existing = windows.find((w) => new URL(w.url).origin === url.origin)
      if (existing) {
        await existing.focus()
        return existing.navigate(url.href)
      }
      return self.clients.openWindow(url.href)
    })(),
  )
})
