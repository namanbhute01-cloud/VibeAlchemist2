import { useEffect, useState, useRef } from 'react'
import { usePlayback } from './usePlayback'

export function useKeyboardShortcuts() {
  const { play, pause, next, prev, setVol, status } = usePlayback()
  const [currentVolume, setCurrentVolume] = useState(70)
  const [previousVolume, setPreviousVolume] = useState(70)
  const [isMuted, setIsMuted] = useState(false)
  const volumeRef = useRef(70)

  // Sync with player status
  useEffect(() => {
    if (status?.volume !== undefined) {
      const newVol = status.volume
      setCurrentVolume(newVol)
      volumeRef.current = newVol
      if (newVol === 0) {
        setIsMuted(true)
      } else if (isMuted) {
        setIsMuted(false)
        setPreviousVolume(newVol)
      }
    }
  }, [status?.volume])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in input fields
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return
      }

      switch (e.code) {
        case 'Space':
        case 'KeyK':
          e.preventDefault()
          // Toggle play/pause
          if (status?.paused) {
            play()
          } else {
            pause()
          }
          break
        case 'ArrowRight':
          e.preventDefault()
          next()
          break
        case 'ArrowLeft':
          e.preventDefault()
          prev()
          break
        case 'ArrowUp':
          e.preventDefault()
          // Volume up by 5
          const newVolUp = Math.min(100, volumeRef.current + 5)
          volumeRef.current = newVolUp
          setCurrentVolume(newVolUp)
          setVol(newVolUp)
          if (isMuted) {
            setIsMuted(false)
          }
          break
        case 'ArrowDown':
          e.preventDefault()
          // Volume down by 5
          const newVolDown = Math.max(0, volumeRef.current - 5)
          volumeRef.current = newVolDown
          setCurrentVolume(newVolDown)
          setVol(newVolDown)
          if (newVolDown === 0) {
            setIsMuted(true)
          }
          break
        case 'KeyM':
          e.preventDefault()
          // Toggle mute
          if (isMuted) {
            // Unmute - restore previous volume
            setVol(previousVolume)
            volumeRef.current = previousVolume
            setIsMuted(false)
          } else {
            // Mute - save current volume and set to 0
            if (volumeRef.current > 0) {
              setPreviousVolume(volumeRef.current)
            }
            setVol(0)
            setIsMuted(true)
          }
          break
        default:
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [play, pause, next, prev, setVol, isMuted, previousVolume])
}
