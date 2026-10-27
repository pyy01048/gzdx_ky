/**
 * Aurora v3 · Animated icon library
 *
 * Every icon carries a motion recipe (draw / pop / swing / ring / ...).
 * Motion is triggered by hover, keyboard focus, or an active route, and is
 * disabled under prefers-reduced-motion by motion.css.
 *
 * Existing Lucide-style path data is reused from the legacy icon module so the
 * visual vocabulary stays consistent; new paths use the same 24×24 grid.
 */
import React from 'react'
import * as Legacy from '../../components/Icon'

const MOTION = {
  Home: 'bounce',
  Book: 'swing',
  Clock: 'spin',
  User: 'nod',
  LogOut: 'slide',
  Shield: 'pop',
  Calendar: 'pop',
  Map: 'draw',
  Target: 'pop',
  Brain: 'breathe',
  Folder: 'nod',
  Settings: 'spin',
  Plus: 'pop',
  Check: 'pop',
  X: 'pop',
  Trash: 'wiggle',
  Edit: 'wiggle',
  Search: 'scan',
  Filter: 'slide',
  MoreVertical: 'pop',
  AlertCircle: 'pop',
  CheckCircle: 'pop',
  Info: 'pop',
  Warning: 'pop',
  GraduationCap: 'bounce',
  FileText: 'slide',
  MessageSquare: 'pop',
  Timer: 'spin',
  Play: 'pop',
  Pause: 'pop',
  Cloud: 'float',
  RefreshCw: 'spin',
  ChevronLeft: 'slide',
  ChevronRight: 'slide',
  ChevronDown: 'slide',
  Upload: 'bounce',
  Download: 'bounce',
  Sun: 'spin',
  Moon: 'spin',
  Activity: 'draw',
  Command: 'pop',
  Keyboard: 'type',
  Flame: 'flicker',
  Trophy: 'pop',
  Zap: 'flicker',
  Camera: 'nod',
  Layers: 'pop',
  Type: 'type',
  ExternalLink: 'slide',
  Database: 'pop',
}

const IDLE = {
  Brain: 'breathe',
  Sparkles: 'spin',
  Bot: 'float',
  Flame: 'flicker',
}

function legacyIcon(name, props) {
  const C = Legacy[name]
  if (!C) return null
  const { className = '', ...rest } = props
  return (
    <C
      {...rest}
      className={`v3-icon ${className}`.trim()}
      data-motion={rest['data-motion'] || MOTION[name] || 'draw'}
      data-idle={rest['data-idle'] || IDLE[name] || undefined}
    />
  )
}

function make(name) {
  function AnimatedIcon(props) {
    return legacyIcon(name, props)
  }
  AnimatedIcon.displayName = `AIcon(${name})`
  return AnimatedIcon
}

/* -------------------------------------------------------------------------- */
/* New glyphs                                                                 */
/* -------------------------------------------------------------------------- */

function Base({ size = 20, className = '', strokeWidth = 2, motion = 'draw', idle, children, ...props }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`v3-icon ${className}`.trim()}
      aria-hidden="true"
      data-motion={motion}
      data-idle={idle}
      {...props}
    >
      {children}
    </svg>
  )
}

export const Sparkles = (p) => (
  <Base motion="spin" idle="spin" {...p}>
    <path d="M12 3l1.7 4.9L18.6 9.6l-4.9 1.7L12 16.2l-1.7-4.9L5.4 9.6l4.9-1.7z" />
    <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
    <path d="M5 2l.6 1.6L7.2 4.2 5.6 4.8 5 6.4l-.6-1.6L2.8 4.2l1.6-.6z" />
  </Base>
)

export const Send = (p) => (
  <Base motion="slide" {...p}>
    <path d="M22 2 11 13" />
    <path d="M22 2 15 22l-4-9-9-4z" />
  </Base>
)

export const Mic = (p) => (
  <Base motion="bounce" {...p}>
    <rect x="9" y="2" width="6" height="12" rx="3" />
    <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
    <path d="M12 18v4" />
    <path d="M8 22h8" />
  </Base>
)

export const Paperclip = (p) => (
  <Base motion="wiggle" {...p}>
    <path d="m21.4 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </Base>
)

export const Bell = (p) => (
  <Base motion="ring" {...p}>
    <path d="M10.27 21a2 2 0 0 0 3.46 0" />
    <path d="M3.26 15.5A1 1 0 0 1 4 14h16a1 1 0 0 1 .74 1.68C19.41 17.02 18 18.9 18 20H6c0-1.1-1.41-2.98-2.74-4.32a1 1 0 0 1 0-.18z" />
    <path d="M18 8a6 6 0 0 0-12 0c0 5-2 6-2 6" />
  </Base>
)

export const Bot = (p) => (
  <Base motion="nod" idle="float" {...p}>
    <rect x="4" y="7" width="16" height="12" rx="4" />
    <path d="M12 3v4" />
    <path d="M8 12h.01M16 12h.01" />
    <path d="M9 16h6" />
    <path d="M2 12v3M22 12v3" />
  </Base>
)

export const Cpu = (p) => (
  <Base motion="spin" {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
    <rect x="9" y="9" width="6" height="6" rx="1" />
    <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
  </Base>
)

export const Wand = (p) => (
  <Base motion="wiggle" {...p}>
    <path d="m15 4 5 5" />
    <path d="M3 21 14.5 9.5" />
    <path d="m17 2 .8 2.2L20 5l-2.2.8L17 8l-.8-2.2L14 5l2.2-.8z" />
    <path d="m8 2 .5 1.5L10 4l-1.5.5L8 6l-.5-1.5L6 4l1.5-.5z" />
  </Base>
)

export const BookOpen = (p) => (
  <Base motion="swing" {...p}>
    <path d="M12 7c-1.5-2-4-3-8-3v14c4 0 6.5 1 8 3 1.5-2 4-3 8-3V4c-4 0-6.5 1-8 3z" />
    <path d="M12 7v14" />
  </Base>
)

export const Library = (p) => (
  <Base motion="draw" {...p}>
    <path d="m3 3 6 2v16l-6-2z" />
    <path d="m9 5 6-2v16l-6 2z" />
    <path d="M15 5h6v16h-6" />
  </Base>
)

export const NotebookPen = (p) => (
  <Base motion="wiggle" {...p}>
    <path d="M4 4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
    <path d="M8 2v20" />
    <path d="m13 13 4-4 2 2-4 4-2 .5z" />
  </Base>
)

export const ListChecks = (p) => (
  <Base motion="pop" {...p}>
    <path d="m3 7 2 2 3-3" />
    <path d="m3 17 2 2 3-3" />
    <path d="M13 8h8M13 18h8" />
  </Base>
)

export const CalendarClock = (p) => (
  <Base motion="pop" {...p}>
    <path d="M21 13V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h8" />
    <path d="M16 2v4M8 2v4M3 10h18" />
    <circle cx="18" cy="18" r="4" />
    <path d="M18 16v2l1.5 1" />
  </Base>
)

export const BarChart3 = (p) => (
  <Base motion="draw" {...p}>
    <path d="M3 3v18h18" />
    <path d="M8 17V9M13 17V5M18 17v-6" />
  </Base>
)

export const PieChart = (p) => (
  <Base motion="draw" {...p}>
    <path d="M21.2 15.9A10 10 0 1 1 8.1 2.8" />
    <path d="M22 12A10 10 0 0 0 12 2v10z" />
  </Base>
)

export const LineChart = (p) => (
  <Base motion="draw" {...p}>
    <path d="M3 3v18h18" />
    <path d="m7 14 4-4 4 3 5-6" />
  </Base>
)

export const TrendingUp = (p) => (
  <Base motion="bounce" {...p}>
    <path d="m3 17 6-6 4 4 8-8" />
    <path d="M15 7h6v6" />
  </Base>
)

export const TrendingDown = (p) => (
  <Base motion="bounce" {...p}>
    <path d="m3 7 6 6 4-4 8 8" />
    <path d="M15 17h6v-6" />
  </Base>
)

export const ArrowRight = (p) => (
  <Base motion="slide" {...p}>
    <path d="M5 12h14" />
    <path d="m13 6 6 6-6 6" />
  </Base>
)

export const ArrowUpRight = (p) => (
  <Base motion="slide" {...p}>
    <path d="M7 17 17 7" />
    <path d="M8 7h9v9" />
  </Base>
)

export const ChevronUp = (p) => (
  <Base motion="slide" {...p}>
    <path d="m6 15 6-6 6 6" />
  </Base>
)

export const PanelLeftClose = (p) => (
  <Base motion="slide" {...p}>
    <rect x="3" y="3" width="18" height="18" rx="3" />
    <path d="M9 3v18" />
    <path d="m15 9-3 3 3 3" />
  </Base>
)

export const PanelLeftOpen = (p) => (
  <Base motion="slide" {...p}>
    <rect x="3" y="3" width="18" height="18" rx="3" />
    <path d="M9 3v18" />
    <path d="m12 9 3 3-3 3" />
  </Base>
)

export const MoreHorizontal = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="5" cy="12" r="1" />
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
  </Base>
)

export const CircleHelp = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4" />
    <path d="M12 17h.01" />
  </Base>
)

export const SquarePen = (p) => (
  <Base motion="wiggle" {...p}>
    <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.4 2.6a2 2 0 0 1 3 3L12 15l-4 1 1-4z" />
  </Base>
)

export const SlidersHorizontal = (p) => (
  <Base motion="slide" {...p}>
    <path d="M3 6h18M3 12h18M3 18h18" />
    <circle cx="8" cy="6" r="2" />
    <circle cx="16" cy="12" r="2" />
    <circle cx="10" cy="18" r="2" />
  </Base>
)

export const LayoutGrid = (p) => (
  <Base motion="pop" {...p}>
    <rect x="3" y="3" width="7" height="7" rx="2" />
    <rect x="14" y="3" width="7" height="7" rx="2" />
    <rect x="3" y="14" width="7" height="7" rx="2" />
    <rect x="14" y="14" width="7" height="7" rx="2" />
  </Base>
)

export const List = (p) => (
  <Base motion="slide" {...p}>
    <path d="M8 6h13M8 12h13M8 18h13" />
    <path d="M3 6h.01M3 12h.01M3 18h.01" />
  </Base>
)

export const RotateCcw = (p) => (
  <Base motion="spin" {...p}>
    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
    <path d="M3 3v5h5" />
  </Base>
)

export const PlayCircle = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="m10 8 6 4-6 4z" />
  </Base>
)

export const PauseCircle = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M10 9v6M14 9v6" />
  </Base>
)

export const Volume2 = (p) => (
  <Base motion="slide" {...p}>
    <path d="M11 5 6 9H2v6h4l5 4z" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7" />
    <path d="M18.5 5.5a9 9 0 0 1 0 13" />
  </Base>
)

export const Star = (p) => (
  <Base motion="spin" {...p}>
    <path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z" />
  </Base>
)

export const Bookmark = (p) => (
  <Base motion="nod" {...p}>
    <path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
  </Base>
)

export const Heart = (p) => (
  <Base motion="pop" {...p}>
    <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z" />
  </Base>
)

export const Share2 = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <path d="m8.6 10.5 6.8-4M8.6 13.5l6.8 4" />
  </Base>
)

export const Copy = (p) => (
  <Base motion="pop" {...p}>
    <rect x="9" y="9" width="13" height="13" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </Base>
)

export const LogIn = (p) => (
  <Base motion="slide" {...p}>
    <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
    <path d="m10 17 5-5-5-5" />
    <path d="M15 12H3" />
  </Base>
)

export const KeyRound = (p) => (
  <Base motion="nod" {...p}>
    <path d="M2 18v3h3l2-2 1 1 2-2-1-1 1.5-1.5a6 6 0 1 0-4-4z" />
    <circle cx="16" cy="8" r="1" />
  </Base>
)

export const Mail = (p) => (
  <Base motion="nod" {...p}>
    <rect x="2" y="4" width="20" height="16" rx="3" />
    <path d="m3 7 9 6 9-6" />
  </Base>
)

export const Lock = (p) => (
  <Base motion="nod" {...p}>
    <rect x="4" y="10" width="16" height="11" rx="3" />
    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    <path d="M12 15v2" />
  </Base>
)

export const Eye = (p) => (
  <Base motion="pop" {...p}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
    <circle cx="12" cy="12" r="3" />
  </Base>
)

export const EyeOff = (p) => (
  <Base motion="pop" {...p}>
    <path d="M10.7 5.1A10.9 10.9 0 0 1 12 5c6.5 0 10 7 10 7a17.4 17.4 0 0 1-3.2 4.2" />
    <path d="M6.6 6.6A17.6 17.6 0 0 0 2 12s3.5 7 10 7a10.8 10.8 0 0 0 5.4-1.4" />
    <path d="m2 2 20 20" />
  </Base>
)

export const School = (p) => (
  <Base motion="bounce" {...p}>
    <path d="m3 9 9-6 9 6-9 6z" />
    <path d="M6 11v6c0 1.5 3 3 6 3s6-1.5 6-3v-6" />
    <path d="M21 9v6" />
  </Base>
)

export const Compass = (p) => (
  <Base motion="spin" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="m16 8-2.5 5.5L8 16l2.5-5.5z" />
  </Base>
)

export const Globe = (p) => (
  <Base motion="spin" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M2 12h20" />
    <path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z" />
  </Base>
)

export const Server = (p) => (
  <Base motion="pop" {...p}>
    <rect x="3" y="3" width="18" height="7" rx="2" />
    <rect x="3" y="14" width="18" height="7" rx="2" />
    <path d="M7 6.5h.01M7 17.5h.01" />
  </Base>
)

export const HardDrive = (p) => (
  <Base motion="pop" {...p}>
    <path d="M22 12H2" />
    <path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z" />
    <path d="M6 16h.01M10 16h.01" />
  </Base>
)

export const FileUp = (p) => (
  <Base motion="bounce" {...p}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
    <path d="M12 18v-6M9 15l3-3 3 3" />
  </Base>
)

export const Image = (p) => (
  <Base motion="pop" {...p}>
    <rect x="3" y="3" width="18" height="18" rx="3" />
    <circle cx="9" cy="9" r="2" />
    <path d="m21 15-5-5L5 21" />
  </Base>
)

export const Music = (p) => (
  <Base motion="bounce" {...p}>
    <path d="M9 18V5l12-2v13" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
  </Base>
)

export const Video = (p) => (
  <Base motion="pop" {...p}>
    <rect x="2" y="6" width="14" height="12" rx="3" />
    <path d="m16 10 6-3v10l-6-3z" />
  </Base>
)

export const FolderOpen = (p) => (
  <Base motion="nod" {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1" />
    <path d="M3 7v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2l1-8H7l-2 8" />
  </Base>
)

export const Tag = (p) => (
  <Base motion="pop" {...p}>
    <path d="M20.6 13.4 12 22l-9-9V4a1 1 0 0 1 1-1h9z" />
    <circle cx="7.5" cy="7.5" r="1" />
  </Base>
)

export const Hash = (p) => (
  <Base motion="pop" {...p}>
    <path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18" />
  </Base>
)

export const Quote = (p) => (
  <Base motion="type" {...p}>
    <path d="M3 21c3-1 5-3 5-7V7H3v7h3" />
    <path d="M14 21c3-1 5-3 5-7V7h-5v7h3" />
  </Base>
)

export const Lightbulb = (p) => (
  <Base motion="flicker" {...p}>
    <path d="M9 18h6" />
    <path d="M10 22h4" />
    <path d="M8.5 14a6 6 0 1 1 7 0c-.8.6-1.5 1.6-1.5 3H10c0-1.4-.7-2.4-1.5-3z" />
  </Base>
)

export const Rocket = (p) => (
  <Base motion="bounce" {...p}>
    <path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.8-.9.7-2.2-.1-3-.8-.8-2.1-.9-2.9 0z" />
    <path d="M12 15 9 12a22 22 0 0 1 2-4 12.7 12.7 0 0 1 9-5 12.7 12.7 0 0 1-5 9 22 22 0 0 1-4 2z" />
    <path d="M9 12H4s.5-2.5 2-4c1.7-1.7 4-2 4-2M12 15v5s2.5-.5 4-2c1.7-1.7 2-4 2-4" />
  </Base>
)

export const Flag = (p) => (
  <Base motion="swing" {...p}>
    <path d="M4 22V4c0-1 1-2 2-2 3 2 5 2 8 1s5-1 8 1v9c-3-2-5-2-8-1s-5 1-8-1" />
  </Base>
)

export const Pin = (p) => (
  <Base motion="nod" {...p}>
    <path d="M12 17v5" />
    <path d="M9 10.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.8a2 2 0 0 0-1.1-1.7l-1.8-.9a2 2 0 0 1-1.1-1.8V7a1 1 0 0 1 1-1 1 1 0 0 0 0-2H8a1 1 0 0 0 0 2 1 1 0 0 1 1 1z" />
  </Base>
)

export const BellRing = (p) => (
  <Base motion="ring" {...p}>
    <path d="M10.3 21a2 2 0 0 0 3.4 0" />
    <path d="M3.3 15.5A1 1 0 0 1 4 14h16a1 1 0 0 1 .7 1.7C19.4 17 18 18.9 18 20H6c0-1.1-1.4-3-2.7-4.3a1 1 0 0 1 0-.2z" />
    <path d="M18 8a6 6 0 0 0-12 0c0 5-2 6-2 6" />
    <path d="M2 3c1.5-1 3-1 4 0M22 3c-1.5-1-3-1-4 0" />
  </Base>
)

export const Gauge = (p) => (
  <Base motion="spin" {...p}>
    <path d="M12 14 15 9" />
    <path d="M3.5 18a9 9 0 1 1 17 0" />
    <circle cx="12" cy="14" r="1.5" />
  </Base>
)

export const Crosshair = (p) => (
  <Base motion="spin" {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
  </Base>
)

export const Menu = (p) => (
  <Base motion="slide" {...p}>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </Base>
)

export const Loader = (p) => (
  <Base motion="spin" idle="spin" {...p}>
    <path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" />
  </Base>
)

export const InfoCircle = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 11v5M12 8h.01" />
  </Base>
)

export const CheckCircle2 = (p) => (
  <Base motion="pop" {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="m8 12 3 3 5-6" />
  </Base>
)

export const AlertTriangle = (p) => (
  <Base motion="pop" {...p}>
    <path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z" />
    <path d="M12 9v4M12 17h.01" />
  </Base>
)

export const Maximize2 = (p) => (
  <Base motion="pop" {...p}>
    <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
  </Base>
)

export const Minimize2 = (p) => (
  <Base motion="pop" {...p}>
    <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" />
  </Base>
)

export const FilterX = (p) => (
  <Base motion="slide" {...p}>
    <path d="M13.5 3H5a1 1 0 0 0-.8 1.6L10 12v7l3 2v-9l4.3-5.1" />
    <path d="m17 17 5 5M22 17l-5 5" />
  </Base>
)

/* -------------------------------------------------------------------------- */
/* Named exports                                                              */
/* -------------------------------------------------------------------------- */
export const Home = make('Home')
export const Book = make('Book')
export const Clock = make('Clock')
export const User = make('User')
export const LogOut = make('LogOut')
export const Shield = make('Shield')
export const Calendar = make('Calendar')
export const Map = make('Map')
export const Target = make('Target')
export const Brain = make('Brain')
export const Folder = make('Folder')
export const Settings = make('Settings')
export const Plus = make('Plus')
export const Check = make('Check')
export const X = make('X')
export const Trash = make('Trash')
export const Edit = make('Edit')
export const Search = make('Search')
export const Filter = make('Filter')
export const MoreVertical = make('MoreVertical')
export const AlertCircle = make('AlertCircle')
export const CheckCircle = make('CheckCircle')
export const Info = make('Info')
export const Warning = make('Warning')
export const GraduationCap = make('GraduationCap')
export const FileText = make('FileText')
export const MessageSquare = make('MessageSquare')
export const Timer = make('Timer')
export const Play = make('Play')
export const Pause = make('Pause')
export const Cloud = make('Cloud')
export const RefreshCw = make('RefreshCw')
export const ChevronLeft = make('ChevronLeft')
export const ChevronRight = make('ChevronRight')
export const ChevronDown = make('ChevronDown')
export const Upload = make('Upload')
export const Download = make('Download')
export const Sun = make('Sun')
export const Moon = make('Moon')
export const Activity = make('Activity')
export const Command = make('Command')
export const Keyboard = make('Keyboard')
export const Flame = make('Flame')
export const Trophy = make('Trophy')
export const Zap = make('Zap')
export const Camera = make('Camera')
export const Layers = make('Layers')
export const Type = make('Type')
export const ExternalLink = make('ExternalLink')
export const Database = make('Database')
