import { useEffect, useEffectEvent, useRef } from 'react'

interface UseWebSocketOptions {
  onOpen?: () => void
  onMessage?: (event: MessageEvent<string>) => void
  onClose?: () => void
  onError?: () => void
  retryDelayMs?: number
}

export function useWebSocket(url: string, options: UseWebSocketOptions) {
  const socketRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number | null>(null)

  const handleOpen = useEffectEvent(() => {
    options.onOpen?.()
  })

  const handleMessage = useEffectEvent((event: MessageEvent<string>) => {
    options.onMessage?.(event)
  })

  const handleClose = useEffectEvent(() => {
    options.onClose?.()
  })

  const handleError = useEffectEvent(() => {
    options.onError?.()
  })

  useEffect(() => {
    let disposed = false

    const connect = () => {
      if (disposed) {
        return
      }

      const socket = new WebSocket(url)
      socketRef.current = socket
      socket.onopen = () => handleOpen()
      socket.onmessage = (event) => handleMessage(event)
      socket.onerror = () => handleError()
      socket.onclose = () => {
        socketRef.current = null
        handleClose()
        if (!disposed) {
          retryRef.current = window.setTimeout(connect, options.retryDelayMs ?? 1000)
        }
      }
    }

    connect()

    return () => {
      disposed = true
      if (retryRef.current !== null) {
        window.clearTimeout(retryRef.current)
      }
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [url, options.retryDelayMs])

  return socketRef
}
