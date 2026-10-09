import { ApiError } from './api/client'
import { useMe } from './api/hooks'
import { Workbench } from './layout/Workbench'
import { LoginScreen } from './LoginScreen'

export function App() {
  const me = useMe()
  if (me.isLoading) return null
  if (me.error) {
    const signedOut = me.error instanceof ApiError && me.error.status === 401
    return <LoginScreen error={signedOut ? undefined : me.error.message} />
  }
  return <Workbench />
}
