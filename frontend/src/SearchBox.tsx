import { useEffect, useRef, useState } from 'react'
import { geocode, type GeocodeResult } from './api'

interface Props {
  placeholder: string
  /** Label of the currently selected place (from search, map click, or geolocation). */
  selectedLabel: string | null
  onSelect: (result: GeocodeResult) => void
}

const DEBOUNCE_MS = 300
const MIN_CHARS = 3

export default function SearchBox({ placeholder, selectedLabel, onSelect }: Props) {
  const [text, setText] = useState('')
  const [results, setResults] = useState<GeocodeResult[]>([])
  const [open, setOpen] = useState(false)
  const suppressSearch = useRef(false)

  // Keep the input in sync when the selection comes from outside (map click,
  // geolocation, clear).
  useEffect(() => {
    suppressSearch.current = true
    setText(selectedLabel ?? '')
    setResults([])
    setOpen(false)
  }, [selectedLabel])

  useEffect(() => {
    if (suppressSearch.current) {
      suppressSearch.current = false
      return
    }
    if (text.trim().length < MIN_CHARS) {
      setResults([])
      setOpen(false)
      return
    }
    const timer = setTimeout(() => {
      geocode(text.trim())
        .then((r) => {
          setResults(r)
          setOpen(true)
        })
        .catch(() => setResults([]))
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [text])

  const pick = (result: GeocodeResult) => {
    suppressSearch.current = true
    setText(result.label)
    setResults([])
    setOpen(false)
    onSelect(result)
  }

  return (
    <div className="search">
      <input
        type="text"
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && results.length > 0) pick(results[0])
          if (e.key === 'Escape') setOpen(false)
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && results.length > 0 && (
        <ul className="search-results">
          {results.map((r, i) => (
            <li key={i} onMouseDown={() => pick(r)}>
              {r.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
