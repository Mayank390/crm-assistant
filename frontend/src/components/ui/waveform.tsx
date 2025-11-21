
import { useEffect, useRef, useState, useCallback } from "react"

export interface WaveformProps {
  data?: number[]
  barWidth?: number
  barHeight?: number
  barGap?: number
  barRadius?: number
  barColor?: string
  fadeEdges?: boolean
  fadeWidth?: number
  height?: string | number
  onBarClick?: (index: number, value: number) => void
  dynamicColor?: boolean
}

export function Waveform({
  data = [],
  barWidth = 4,
  barHeight = 4,
  barGap = 2,
  barRadius = 2,
  barColor,
  fadeEdges = true,
  fadeWidth = 24,
  height = 128,
  onBarClick,
  dynamicColor = false,
}: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height: containerHeight } = entry.contentRect
        const dpr = window.devicePixelRatio || 1
        canvas.width = width * dpr
        canvas.height = containerHeight * dpr
        canvas.style.width = `${width}px`
        canvas.style.height = `${containerHeight}px`
        ctx.scale(dpr, dpr)
        draw()
      }
    })

    resizeObserver.observe(container)

    const draw = () => {
      const width = container.clientWidth
      const height = container.clientHeight
      ctx.clearRect(0, 0, width, height)

      if (data.length === 0) return

      const totalBarWidth = barWidth + barGap
      const maxBars = Math.floor(width / totalBarWidth)
      const barsToShow = Math.min(data.length, maxBars)
      const startX = (width - barsToShow * totalBarWidth + barGap) / 2

      for (let i = 0; i < barsToShow; i++) {
        const value = data[i] ?? 0
        const x = startX + i * totalBarWidth
        const barHeightValue = value * height
        const y = (height - barHeightValue) / 2

        let alpha = 1
        if (fadeEdges) {
          const distanceFromStart = i
          const distanceFromEnd = barsToShow - 1 - i
          const minDistance = Math.min(distanceFromStart, distanceFromEnd)
          if (minDistance < fadeWidth) {
            alpha = minDistance / fadeWidth
          }
        }

        // Dynamic color based on amplitude
        let currentColor = barColor || getComputedStyle(document.documentElement).getPropertyValue("--foreground").trim() || "#000"

        if (dynamicColor) {
          if (value < 0.3) {
            currentColor = "#10b981" // Green for low amplitude
          } else if (value < 0.7) {
            currentColor = "#f59e0b" // Yellow for medium amplitude
          } else {
            currentColor = "#ef4444" // Red for high amplitude
          }
        }

        ctx.fillStyle = currentColor
        ctx.globalAlpha = alpha
        ctx.beginPath()
        ctx.roundRect(x, y, barWidth, barHeightValue, barRadius)
        ctx.fill()
      }

      ctx.globalAlpha = 1
    }

    draw()

    return () => {
      resizeObserver.disconnect()
    }
  }, [data, barWidth, barHeight, barGap, barRadius, barColor, fadeEdges, fadeWidth, height])

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!onBarClick || !canvasRef.current || !containerRef.current) return

      const rect = canvasRef.current.getBoundingClientRect()
      const x = e.clientX - rect.left
      const totalBarWidth = barWidth + barGap
      const barIndex = Math.floor(x / totalBarWidth)

      if (barIndex >= 0 && barIndex < data.length) {
        onBarClick(barIndex, data[barIndex] ?? 0)
      }
    },
    [onBarClick, barWidth, barGap, data]
  )

  return (
    <div ref={containerRef} style={{ height: typeof height === "number" ? `${height}px` : height, width: "100%" }}>
      <canvas ref={canvasRef} onClick={handleClick} style={{ display: "block", width: "100%", height: "100%" }} />
    </div>
  )
}

export interface ScrollingWaveformProps extends Omit<WaveformProps, "data" | "onBarClick"> {
  speed?: number
  barCount?: number
}

export function ScrollingWaveform({ speed = 50, barCount = 60, ...props }: ScrollingWaveformProps) {
  const [data, setData] = useState<number[]>(() => Array(barCount).fill(0.1))
  const animationRef = useRef<number>()
  const lastTimeRef = useRef<number>(performance.now())

  useEffect(() => {
    const animate = (currentTime: number) => {
      const deltaTime = currentTime - lastTimeRef.current
      lastTimeRef.current = currentTime

      setData((prev) => {
        const newData = [...prev]
        const scrollAmount = (speed * deltaTime) / 1000
        const barWidth = (props.barWidth ?? 4) + (props.barGap ?? 2)
        const barsToShift = Math.floor(scrollAmount / barWidth)

        if (barsToShift > 0) {
          newData.splice(0, barsToShift)
          while (newData.length < barCount) {
            newData.push(0.1 + Math.random() * 0.4)
          }
        }

        return newData
      })

      animationRef.current = requestAnimationFrame(animate)
    }

    animationRef.current = requestAnimationFrame(animate)

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [speed, barCount, props.barWidth, props.barGap])

  return <Waveform data={data} {...props} />
}

export interface MicrophoneWaveformProps extends Omit<WaveformProps, "data" | "onBarClick"> {
  active?: boolean
  fftSize?: number
  smoothingTimeConstant?: number
  sensitivity?: number
  onError?: (error: Error) => void
}

export function MicrophoneWaveform({
  active = false,
  fftSize = 256,
  smoothingTimeConstant = 0.3,
  sensitivity = 2,
  onError,
  ...props
}: MicrophoneWaveformProps) {
  const [data, setData] = useState<number[]>(Array(50).fill(0.05))
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const animationRef = useRef<number>()

  useEffect(() => {
    if (!active) {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      analyserRef.current = null
      setData(Array(50).fill(0.1))
      return
    }

    let mounted = true

    const initMicrophone = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (!mounted) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }

        streamRef.current = stream
        const audioContext = new AudioContext()
        audioContextRef.current = audioContext

        const analyser = audioContext.createAnalyser()
        analyser.fftSize = fftSize
        analyser.smoothingTimeConstant = smoothingTimeConstant
        analyserRef.current = analyser

        const source = audioContext.createMediaStreamSource(stream)
        source.connect(analyser)

        const bufferLength = analyser.frequencyBinCount
        const dataArray = new Uint8Array(bufferLength)

        const update = () => {
          if (!mounted || !analyserRef.current) return

          analyserRef.current.getByteFrequencyData(dataArray)

          const barCount = 50
          const newData: number[] = []

          // Use more frequency bins and focus on the lower frequencies which are more responsive to voice
          const usableBins = Math.min(bufferLength, barCount * 3)
          const step = Math.floor(usableBins / barCount)

          let totalAmplitude = 0

          for (let i = 0; i < barCount; i++) {
            let sum = 0
            const startIdx = i * step
            const endIdx = Math.min(startIdx + step, usableBins)

            for (let j = startIdx; j < endIdx; j++) {
              sum += dataArray[j] ?? 0
            }

            const average = sum / (endIdx - startIdx)
            // Apply logarithmic scaling for better visual response
            const normalized = Math.min(1, Math.pow(average / 255, 0.7) * sensitivity)
            // Ensure minimum height and smooth transitions
            newData.push(Math.max(0.02, normalized))
            totalAmplitude += normalized
          }

          // Calculate average amplitude for dynamic coloring
          const avgAmplitude = totalAmplitude / barCount

          // Update the waveform with dynamic data
          setData(newData)
          animationRef.current = requestAnimationFrame(update)
        }

        update()
      } catch (error) {
        if (mounted && onError) {
          onError(error instanceof Error ? error : new Error(String(error)))
        }
      }
    }

    initMicrophone()

    return () => {
      mounted = false
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      analyserRef.current = null
    }
  }, [active, fftSize, smoothingTimeConstant, sensitivity, onError])

  return <Waveform data={data} {...props} />
}

export interface AudioScrubberProps extends WaveformProps {
  currentTime: number
  duration?: number
  onSeek?: (time: number) => void
  showHandle?: boolean
}

export function AudioScrubber({
  data = [],
  currentTime,
  duration = 100,
  onSeek,
  showHandle = true,
  ...props
}: AudioScrubberProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const isDraggingRef = useRef(false)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height: containerHeight } = entry.contentRect
        const dpr = window.devicePixelRatio || 1
        canvas.width = width * dpr
        canvas.height = containerHeight * dpr
        canvas.style.width = `${width}px`
        canvas.style.height = `${containerHeight}px`
        ctx.scale(dpr, dpr)
        draw()
      }
    })

    resizeObserver.observe(container)

    const draw = () => {
      const width = container.clientWidth
      const height = container.clientHeight
      ctx.clearRect(0, 0, width, height)

      if (data.length === 0) return

      const totalBarWidth = (props.barWidth ?? 4) + (props.barGap ?? 2)
      const maxBars = Math.floor(width / totalBarWidth)
      const barsToShow = Math.min(data.length, maxBars)
      const startX = (width - barsToShow * totalBarWidth + (props.barGap ?? 2)) / 2

      const color = props.barColor || getComputedStyle(document.documentElement).getPropertyValue("--foreground").trim() || "#000"
      const progress = currentTime / duration
      const progressX = startX + progress * (barsToShow * totalBarWidth - (props.barGap ?? 2))

      for (let i = 0; i < barsToShow; i++) {
        const value = data[i] ?? 0
        const x = startX + i * totalBarWidth
        const barHeightValue = value * height
        const y = (height - barHeightValue) / 2

        const isPast = i * totalBarWidth < progressX - startX
        ctx.fillStyle = isPast ? color : `${color}40`
        ctx.globalAlpha = 1
        ctx.beginPath()
        ctx.roundRect(x, y, props.barWidth ?? 4, barHeightValue, props.barRadius ?? 2)
        ctx.fill()
      }

      if (showHandle) {
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(progressX, height / 2, 6, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    draw()

    return () => {
      resizeObserver.disconnect()
    }
  }, [data, currentTime, duration, showHandle, props])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!onSeek || !canvasRef.current || !containerRef.current) return
      isDraggingRef.current = true

      const rect = canvasRef.current.getBoundingClientRect()
      const x = e.clientX - rect.left
      const width = containerRef.current.clientWidth
      const totalBarWidth = (props.barWidth ?? 4) + (props.barGap ?? 2)
      const maxBars = Math.floor(width / totalBarWidth)
      const barsToShow = Math.min(data.length, maxBars)
      const startX = (width - barsToShow * totalBarWidth + (props.barGap ?? 2)) / 2
      const relativeX = Math.max(0, Math.min(width - startX, x - startX))
      const progress = relativeX / (barsToShow * totalBarWidth - (props.barGap ?? 2))
      const time = progress * duration
      onSeek(time)
    },
    [onSeek, duration, data, props]
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!isDraggingRef.current || !onSeek || !canvasRef.current || !containerRef.current) return

      const rect = canvasRef.current.getBoundingClientRect()
      const x = e.clientX - rect.left
      const width = containerRef.current.clientWidth
      const totalBarWidth = (props.barWidth ?? 4) + (props.barGap ?? 2)
      const maxBars = Math.floor(width / totalBarWidth)
      const barsToShow = Math.min(data.length, maxBars)
      const startX = (width - barsToShow * totalBarWidth + (props.barGap ?? 2)) / 2
      const relativeX = Math.max(0, Math.min(width - startX, x - startX))
      const progress = relativeX / (barsToShow * totalBarWidth - (props.barGap ?? 2))
      const time = progress * duration
      onSeek(time)
    },
    [onSeek, duration, data, props]
  )

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = false
  }, [])

  useEffect(() => {
    const handleGlobalMouseUp = () => {
      isDraggingRef.current = false
    }
    window.addEventListener("mouseup", handleGlobalMouseUp)
    return () => window.removeEventListener("mouseup", handleGlobalMouseUp)
  }, [])

  return (
    <div
      ref={containerRef}
      style={{ height: typeof props.height === "number" ? `${props.height}px` : props.height || 128, width: "100%" }}
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        style={{ display: "block", width: "100%", height: "100%", cursor: onSeek ? "pointer" : "default" }}
      />
    </div>
  )
}

export interface StaticWaveformProps extends Omit<WaveformProps, "data" | "onBarClick"> {
  bars?: number
  seed?: number
}

export function StaticWaveform({ bars = 40, seed, ...props }: StaticWaveformProps) {
  const random = useRef<() => number>()

  useEffect(() => {
    let s = seed ?? Math.floor(Math.random() * 2 ** 32)
    random.current = () => {
      s = (s * 9301 + 49297) % 233280
      return s / 233280
    }
  }, [seed])

  const data = Array.from({ length: bars }, () => {
    if (!random.current) return 0.1
    return 0.1 + random.current() * 0.6
  })

  return <Waveform data={data} {...props} />
}

export interface LiveMicrophoneWaveformProps extends ScrollingWaveformProps {
  active?: boolean
  historySize?: number
  updateRate?: number
  enableAudioPlayback?: boolean
  playbackRate?: number
  savedHistoryRef?: React.MutableRefObject<number[]>
  dragOffset?: number
  setDragOffset?: (offset: number) => void
}

export function LiveMicrophoneWaveform({
  active = false,
  historySize = 150,
  updateRate = 50,
  enableAudioPlayback = true,
  playbackRate = 1,
  savedHistoryRef,
  dragOffset,
  setDragOffset,
  ...props
}: LiveMicrophoneWaveformProps) {
  const [data, setData] = useState<number[]>(() => Array(historySize).fill(0.1))
  const historyRef = useRef<number[]>([])
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const animationRef = useRef<number>()
  const intervalRef = useRef<number>()

  useEffect(() => {
    if (savedHistoryRef) {
      historyRef.current = savedHistoryRef.current
    }
  }, [savedHistoryRef])

  useEffect(() => {
    if (!active) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      analyserRef.current = null
      return
    }

    let mounted = true

    const initMicrophone = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (!mounted) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }

        streamRef.current = stream
        const audioContext = new AudioContext()
        audioContextRef.current = audioContext

        const analyser = audioContext.createAnalyser()
        analyser.fftSize = 256
        analyserRef.current = analyser

        const source = audioContext.createMediaStreamSource(stream)
        source.connect(analyser)

        const bufferLength = analyser.frequencyBinCount
        const dataArray = new Uint8Array(bufferLength)

        intervalRef.current = setInterval(() => {
          if (!mounted || !analyserRef.current) return

          analyserRef.current.getByteFrequencyData(dataArray)
          const average = dataArray.reduce((sum, val) => sum + val, 0) / bufferLength
          const normalized = Math.min(1, average / 255)

          historyRef.current.push(normalized)
          if (historyRef.current.length > historySize) {
            historyRef.current.shift()
          }

          if (savedHistoryRef) {
            savedHistoryRef.current = [...historyRef.current]
          }

          setData([...historyRef.current])
        }, updateRate)
      } catch (error) {
        console.error("Microphone error:", error)
      }
    }

    initMicrophone()

    return () => {
      mounted = false
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      analyserRef.current = null
    }
  }, [active, historySize, updateRate, savedHistoryRef])

  return <Waveform data={data} {...props} />
}

export interface RecordingWaveformProps extends WaveformProps {
  recording?: boolean
  onRecordingComplete?: (data: number[]) => void
  showHandle?: boolean
  updateRate?: number
}

export function RecordingWaveform({
  recording = false,
  onRecordingComplete,
  showHandle = true,
  updateRate = 50,
  ...props
}: RecordingWaveformProps) {
  const [data, setData] = useState<number[]>([])
  const [currentTime, setCurrentTime] = useState(0)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const intervalRef = useRef<number>()
  const startTimeRef = useRef<number>(0)

  useEffect(() => {
    if (!recording) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      analyserRef.current = null
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop()
      }
      return
    }

    let mounted = true

    const startRecording = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (!mounted) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }

        streamRef.current = stream
        const audioContext = new AudioContext()
        audioContextRef.current = audioContext

        const analyser = audioContext.createAnalyser()
        analyser.fftSize = 256
        analyserRef.current = analyser

        const source = audioContext.createMediaStreamSource(stream)
        source.connect(analyser)

        const mediaRecorder = new MediaRecorder(stream)
        mediaRecorderRef.current = mediaRecorder

        mediaRecorder.ondataavailable = () => {}
        mediaRecorder.onstop = () => {
          if (onRecordingComplete && mounted) {
            onRecordingComplete([...data])
          }
        }

        mediaRecorder.start()
        startTimeRef.current = Date.now()
        setData([])
        setCurrentTime(0)

        const bufferLength = analyser.frequencyBinCount
        const dataArray = new Uint8Array(bufferLength)

        intervalRef.current = setInterval(() => {
          if (!mounted || !analyserRef.current) return

          analyserRef.current.getByteFrequencyData(dataArray)
          const average = dataArray.reduce((sum, val) => sum + val, 0) / bufferLength
          const normalized = Math.min(1, average / 255)

          setData((prev) => [...prev, normalized])
          setCurrentTime((Date.now() - startTimeRef.current) / 1000)
        }, updateRate)
      } catch (error) {
        console.error("Recording error:", error)
      }
    }

    startRecording()

    return () => {
      mounted = false
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      analyserRef.current = null
    }
  }, [recording, onRecordingComplete, updateRate, data])

  if (showHandle && data.length > 0) {
    return (
      <AudioScrubber
        data={data}
        currentTime={currentTime}
        duration={currentTime || 100}
        onSeek={(time) => {
          const index = Math.floor((time / (currentTime || 100)) * data.length)
          setData(data.slice(0, index))
          setCurrentTime(time)
        }}
        {...props}
      />
    )
  }

  return <Waveform data={data} {...props} />
}

