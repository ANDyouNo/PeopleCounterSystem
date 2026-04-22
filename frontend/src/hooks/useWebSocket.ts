import { useEffect, useRef, useState, useCallback } from 'react'
import type { AppState } from '../api/client'

interface WsMessage {
  type: string
  data: AppState
}

interface UseWebSocketReturn {
  state: AppState
  connected: boolean
}

const DEFAULT_STATE: AppState = {
  people_now: 0,
  fps: 0,
  inference_ms: 0,
  total_unique: 0,
  today_visits: 0,
  today_minutes: 0,
  max_people_today: 0,
  showcase_connected: false,
  light_connected: false,
  showcase_forced: [],
  light_forced: false,
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [state, setState] = useState<AppState | null>(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmounted = useRef(false)

  const connect = useCallback(() => {
    if (unmounted.current) return

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (unmounted.current) return
        setConnected(true)
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current)
          reconnectTimer.current = null
        }
      }

      ws.onmessage = (event) => {
        if (unmounted.current) return
        try {
          const msg: WsMessage = JSON.parse(event.data)
          if (msg.type === 'state') {
            setState(msg.data)
          }
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        if (unmounted.current) return
        setConnected(false)
        // Reconnect after 3 seconds
        reconnectTimer.current = setTimeout(() => {
          if (!unmounted.current) connect()
        }, 3000)
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      reconnectTimer.current = setTimeout(() => {
        if (!unmounted.current) connect()
      }, 3000)
    }
  }, [url])

  useEffect(() => {
    unmounted.current = false
    connect()
    return () => {
      unmounted.current = true
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [connect])

  return { state: state ?? DEFAULT_STATE as AppState, connected }
}
